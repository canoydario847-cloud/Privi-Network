"""Report this service's activity to the Privi Quantum Ledger (one ledger for every Privi service).

Shared, file-for-file, by Privi Verify, Anchor, Quantum, Call and Wallet. Standard library only.

  app = link(app, "privi-verify", __version__, settings.db_path)      # outermost ASGI wrapper

What is reported: every MCP tool call (tool name, outcome) and every state-changing HTTP request (method and
route, with ids masked), each with a keyed fingerprint (HMAC-SHA256 under the report key) of the request body, so
the same request can be matched later but nothing can be guessed back from it. Never the contents, the caller
or a header.
Events wait in a small SQLite outbox and are retried until the Ledger accepts them, so a Ledger restart loses
nothing; the Ledger drops duplicates by event id. A heartbeat tells the Ledger this service is still linked.
Requests to routes that do not exist (404/405) are not activity and are not reported, and a burst above
MAX_PER_MIN events a minute is reported as one "reports.throttled" count, so junk traffic cannot flood the ledger.

Reporting can never break the service: every failure here is swallowed and retried later. With no
PRIVI_LEDGER_REPORT_KEY set the reporter is off and the middleware passes requests straight through.

Loop note: the Ledger settles its blocks through Privi Anchor. If Anchor reported those calls, each report
would grow the ledger, which seals and settles another block, forever. The Ledger marks its own Anchor calls
with a header derived from the report key and the middleware skips exactly those (they are already on the
ledger as block settlements).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

DEFAULT_LEDGER_URL = "https://privi-ledger.onrender.com"
SETTLEMENT_HEADER = b"x-privi-ledger-settlement"
MUTATING = ("POST", "PUT", "PATCH", "DELETE")
MAX_CAPTURE = 1_000_000            # request bytes kept for hashing/parsing; larger bodies are reported unhashed
MAX_RESPONSE_PEEK = 262_144
MAX_OUTBOX = 50_000                # oldest events are dropped beyond this (the Ledger has been down for a long time)
BATCH = 100
MAX_PER_MIN = int(os.getenv("PRIVI_LEDGER_REPORT_MAX_PER_MIN", "120"))
_ID_SEG = re.compile(r"^(0x[0-9a-fA-F]{8,}|[0-9a-fA-F]{16,}|[0-9]{4,}|(?=[^/]*[0-9])[A-Za-z0-9_.:-]{12,})$")

SCHEMA = """CREATE TABLE IF NOT EXISTS outbox (
    n INTEGER PRIMARY KEY AUTOINCREMENT, event TEXT NOT NULL);"""


def settlement_token(report_key: str) -> str:
    return hashlib.sha256(("privi-ledger-settlement:" + report_key).encode()).hexdigest()


def mask_path(path: str) -> str:
    """/kya/0xabc...def/bind -> /kya/{id}/bind: route names are reported, identifiers are not."""
    return "/".join("{id}" if _ID_SEG.match(seg) else seg for seg in path.split("/"))[:160]


def _post(url: str, key: str, body: dict, timeout: float = 20.0) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {key}", "User-Agent": "PriviLedgerReporter/1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode() or "{}")


class LedgerReporter:
    def __init__(self, service: str, url: str = "", key: str = "", version: str = "", outbox_path: str | None = None,
                 interval: float = 20.0, heartbeat: float = 300.0, post: Callable[[str, str, dict], dict] = _post):
        self.service, self.version, self.key = service, str(version or ""), key or ""
        self.url = (url or DEFAULT_LEDGER_URL).rstrip("/") + "/quantum-ledger/report"
        self.interval, self.heartbeat, self._post = interval, heartbeat, post
        self._lock = threading.Lock()
        self._last_beat = 0.0
        self._window, self._in_window, self._throttled = 0, 0, 0
        self._thread: threading.Thread | None = None
        self.sent = self.failed = 0
        self.last_error: str | None = None
        try:
            self._db = sqlite3.connect(outbox_path or ":memory:", check_same_thread=False)
            self._db.executescript(SCHEMA)
        except sqlite3.Error:           # unwritable disk: fall back to memory rather than stop the service
            self._db = sqlite3.connect(":memory:", check_same_thread=False)
            self._db.executescript(SCHEMA)

    @classmethod
    def from_env(cls, service: str, version: str = "", outbox_path: str | None = None) -> "LedgerReporter":
        key = os.getenv("PRIVI_LEDGER_REPORT_KEY", "").strip()
        return cls(service, os.getenv("PRIVI_LEDGER_URL", DEFAULT_LEDGER_URL), key, version,
                   outbox_path if key else None,
                   float(os.getenv("PRIVI_LEDGER_REPORT_INTERVAL", "20")))

    @property
    def enabled(self) -> bool:
        return bool(self.key)

    def report(self, kind: str, name: str, outcome: str = "success", request_hash: str | None = None,
               meta: dict[str, Any] | None = None) -> None:
        """Queue one event. Safe to call from anywhere; never raises."""
        if not self.enabled:
            return
        try:
            evs = []
            with self._lock:
                minute = int(time.time() // 60)
                if minute != self._window:
                    if self._throttled:
                        evs.append(self._event("system", "reports.throttled", "blocked", None,
                                               {"not_reported": self._throttled, "limit_per_minute": MAX_PER_MIN}))
                    self._window, self._in_window, self._throttled = minute, 0, 0
                self._in_window += 1
                if self._in_window > MAX_PER_MIN:
                    self._throttled += 1
                else:
                    evs.append(self._event(kind, name, outcome, request_hash, meta))
                for ev in evs:
                    self._db.execute("INSERT INTO outbox (event) VALUES (?)", (json.dumps(ev),))
                self._db.execute("DELETE FROM outbox WHERE n <= (SELECT MAX(n) FROM outbox) - ?", (MAX_OUTBOX,))
                self._db.commit()
        except Exception as e:
            self.last_error = f"queue: {e}"[:200]

    @staticmethod
    def _event(kind: str, name: str, outcome: str, request_hash: str | None, meta: dict[str, Any] | None) -> dict:
        ev = {"id": f"{int(time.time() * 1000):x}-{secrets.token_hex(8)}", "kind": kind, "name": str(name)[:200],
              "outcome": outcome, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "meta": meta or {}}
        if request_hash:
            ev["hash"] = request_hash
        return ev

    def pending(self) -> int:
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0]

    def flush(self) -> int:
        """Send waiting events (and a heartbeat when one is due). Returns events the Ledger accepted."""
        if not self.enabled:
            return 0
        done = 0
        while True:
            with self._lock:
                rows = self._db.execute("SELECT n, event FROM outbox ORDER BY n LIMIT ?", (BATCH,)).fetchall()
            beat_due = time.time() - self._last_beat >= self.heartbeat
            if not rows and not beat_due:
                return done
            try:
                self._post(self.url, self.key, {"service": self.service, "version": self.version,
                                                "events": [json.loads(r[1]) for r in rows]})
            except Exception as e:      # Ledger unreachable: keep everything and try again next round
                self.failed += 1
                self.last_error = f"{type(e).__name__}: {e}"[:200]
                return done
            self._last_beat, self.last_error = time.time(), None
            if rows:
                # Accepted, duplicate or rejected as malformed: either way the Ledger has answered for these.
                with self._lock:
                    self._db.execute("DELETE FROM outbox WHERE n <= ?", (rows[-1][0],))
                    self._db.commit()
                done += len(rows)
                self.sent += len(rows)
            if len(rows) < BATCH:
                return done

    def start(self) -> None:
        if not self.enabled:
            print(f"{self.service}: ledger reporting is OFF (set PRIVI_LEDGER_REPORT_KEY to link this service "
                  "to the Privi Quantum Ledger)", flush=True)
            return
        if self._thread:
            return
        self.report("system", "service.started", meta={"version": self.version})

        def loop():
            time.sleep(5)
            while True:
                try:
                    self.flush()
                except Exception as e:
                    self.last_error = f"flush: {e}"[:200]
                time.sleep(self.interval)

        self._thread = threading.Thread(target=loop, daemon=True, name=f"{self.service}-ledger-report")
        self._thread.start()
        print(f"{self.service}: reporting to the Privi Quantum Ledger at {self.url}", flush=True)

    def status(self) -> dict[str, Any]:
        return {"linked": self.enabled, "ledger": self.url, "pending": self.pending() if self.enabled else 0,
                "sent": self.sent, "last_error": self.last_error}


class ReportMiddleware:
    """ASGI wrapper that reports tool calls and state-changing requests. Put it outermost."""

    def __init__(self, app, reporter: LedgerReporter, mcp_path: str = "/mcp", skip_paths: Iterable[str] = ()):
        self.app, self.reporter, self.mcp_path = app, reporter, mcp_path
        self.skip_paths = tuple(skip_paths)
        self._settlement = settlement_token(reporter.key).encode() if reporter.enabled else b""

    async def __call__(self, scope, receive, send):
        if (scope["type"] != "http" or not self.reporter.enabled or scope.get("method") not in MUTATING
                or scope.get("path", "").startswith(self.skip_paths or ("\x00",))):
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        if self._settlement and headers.get(SETTLEMENT_HEADER) == self._settlement:
            await self.app(scope, receive, send)      # the Ledger settling its own block: already on the ledger
            return
        started = time.time()
        body, size, state = bytearray(), [0], {"status": 0, "peek": bytearray()}

        async def recv():
            msg = await receive()
            if msg.get("type") == "http.request":
                chunk = msg.get("body") or b""
                size[0] += len(chunk)
                if len(body) < MAX_CAPTURE:
                    body.extend(chunk[:MAX_CAPTURE - len(body)])
            return msg

        async def snd(msg):
            if msg.get("type") == "http.response.start":
                state["status"] = msg.get("status", 0)
            elif msg.get("type") == "http.response.body" and len(state["peek"]) < MAX_RESPONSE_PEEK:
                state["peek"].extend((msg.get("body") or b"")[:MAX_RESPONSE_PEEK - len(state["peek"])])
            await send(msg)

        try:
            await self.app(scope, recv, snd)
        finally:
            try:
                self._report(scope, bytes(body), size[0], state, int((time.time() - started) * 1000))
            except Exception as e:
                self.reporter.last_error = f"report: {e}"[:200]

    def _report(self, scope, body: bytes, size: int, state: dict, ms: int) -> None:
        status, path, method = state["status"], scope.get("path", ""), scope.get("method", "")
        whole = size == len(body)
        digest = hmac.new(self.reporter.key.encode(), body, hashlib.sha256).hexdigest() if whole and body else None
        meta = {"status": status, "ms": ms}
        failed = status >= 400 or status == 0
        if path.rstrip("/") == self.mcp_path:
            try:
                msgs = json.loads(body) if whole else []
            except ValueError:
                msgs = []
            calls = [m for m in (msgs if isinstance(msgs, list) else [msgs])
                     if isinstance(m, dict) and m.get("method") == "tools/call"]
            peek = bytes(state["peek"]).replace(b" ", b"")
            errored = b'"isError":true' in peek or b'"error":{' in peek
            for m in calls:                # other JSON-RPC traffic (initialize, tools/list) is not activity
                tool = str((m.get("params") or {}).get("name") or "unknown")[:120]
                outcome = "blocked" if status in (401, 402, 403, 429) else "failure" if failed or errored else "success"
                self.reporter.report("tool_call", tool, outcome, digest, meta)
            return
        if status in (404, 405):           # no such route: scanners and bots, not activity
            return
        outcome = "blocked" if status in (401, 402, 403, 429) else "failure" if failed else "success"
        self.reporter.report("http", f"{method} {mask_path(path)}", outcome, digest, meta)


def link(app, service: str, version: str = "", db_path: str | None = None, mcp_path: str = "/mcp",
         skip_paths: Iterable[str] = ()):
    """Link a service to the Privi Quantum Ledger: start its reporter (outbox next to the service's own database,
    so it survives restarts) and return the app wrapped with ReportMiddleware."""
    outbox = None
    if db_path and db_path != ":memory:":
        outbox = os.path.join(os.path.dirname(os.path.abspath(db_path)), f"ledger-outbox-{service}.db")
    reporter = LedgerReporter.from_env(service, version, outbox)
    reporter.start()
    return ReportMiddleware(app, reporter, mcp_path, skip_paths)
