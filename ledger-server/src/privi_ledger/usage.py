"""Count MCP tool calls per tool per day (no arguments, no caller identity) and serve /stats.

Wraps the streamable-HTTP ASGI app: peeks at JSON-RPC bodies POSTed to /mcp, counts
"tools/call" by tool name, and replays the body to the app unchanged.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS tool_calls (
    day TEXT NOT NULL, tool TEXT NOT NULL, calls INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (day, tool));
"""
MAX_PEEK = 1_000_000


class UsageMiddleware:
    def __init__(self, app, db: sqlite3.Connection, lock: threading.Lock, service: str):
        self.app, self._db, self._lock, self.service = app, db, lock, service
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.commit()

    def _count(self, tools: list[str]) -> None:
        day = datetime.now(timezone.utc).date().isoformat()
        with self._lock:
            for t in tools:
                self._db.execute("INSERT INTO tool_calls (day, tool, calls) VALUES (?,?,1) "
                                 "ON CONFLICT(day, tool) DO UPDATE SET calls = calls + 1", (day, t[:80]))
            self._db.commit()

    def stats(self) -> dict:
        today = datetime.now(timezone.utc).date()
        since = (today - timedelta(days=29)).isoformat()
        rows = self._db.execute("SELECT tool, SUM(calls) c FROM tool_calls GROUP BY tool ORDER BY c DESC").fetchall()
        recent = self._db.execute("SELECT tool, SUM(calls) c FROM tool_calls WHERE day >= ? GROUP BY tool "
                                  "ORDER BY c DESC", (since,)).fetchall()
        daily = self._db.execute("SELECT day, SUM(calls) c FROM tool_calls WHERE day >= ? GROUP BY day ORDER BY day",
                                 (since,)).fetchall()
        return {"service": self.service, "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "total_tool_calls": sum(r["c"] for r in rows),
                "last_30_days": sum(r["c"] for r in recent),
                "today": next((r["c"] for r in daily if r["day"] == today.isoformat()), 0),
                "by_tool_all_time": {r["tool"]: r["c"] for r in rows},
                "by_tool_last_30_days": {r["tool"]: r["c"] for r in recent},
                "daily_last_30_days": {r["day"]: r["c"] for r in daily},
                "note": "Counts of MCP tools/call requests by tool name. No arguments or caller identities are stored."}

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path, method = scope.get("path", ""), scope.get("method", "")
        if path == "/stats" and method == "GET":
            body = json.dumps(self.stats()).encode()
            await send({"type": "http.response.start", "status": 200,
                        "headers": [(b"content-type", b"application/json"), (b"access-control-allow-origin", b"*"),
                                    (b"cache-control", b"no-store")]})
            await send({"type": "http.response.body", "body": body})
            return
        if not (method == "POST" and path.rstrip("/") == "/mcp"):   # not /gw/<id>/mcp: those are other people's tools
            return await self.app(scope, receive, send)
        chunks, more, size = [], True, 0
        while more:
            msg = await receive()
            if msg["type"] != "http.request":
                return await self.app(scope, receive, send)
            chunks.append(msg.get("body", b""))
            size += len(chunks[-1])
            more = msg.get("more_body", False)
            if size > MAX_PEEK:
                break
        raw = b"".join(chunks)
        try:
            data = json.loads(raw) if not more else None
            msgs = data if isinstance(data, list) else [data]
            tools = [m["params"]["name"] for m in msgs
                     if isinstance(m, dict) and m.get("method") == "tools/call"
                     and isinstance(m.get("params"), dict) and isinstance(m["params"].get("name"), str)]
            if tools:
                self._count(tools)
        except (ValueError, KeyError, TypeError, sqlite3.Error):
            pass
        sent = False

        async def replay():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": raw, "more_body": more}
            return await receive()

        return await self.app(scope, replay, send)
