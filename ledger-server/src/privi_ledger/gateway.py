"""Privi Gateway: a metered, audited front door for any MCP server.

An organization registers an upstream MCP server (streamable HTTP). Privi gives it
    POST /gw/<id>/mcp    (HTTP, SSE responses pass through)
    WS   /gw/<id>/ws     (the same JSON-RPC over one persistent WebSocket)
and in between it:
  * checks the kill switch and the optional caller gate (a KYA wallet proving it holds a Passport score),
  * rate-limits each caller,
  * meters every tools/call (free plan: GW_FREE_MONTHLY per month, Pro: unlimited),
  * writes each tool call to the owner's tamper-evident log, as long as the owner's log plan allows,
  * forwards the request unchanged, including x402 payment headers and MCP _meta, so the
    upstream's own paywall keeps working end to end.

Privi never stores the caller's credentials or the upstream's responses. The upstream must be public
HTTPS: private, loopback and link-local addresses are refused.
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import os
import secrets
import socket
import sqlite3
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from urllib.parse import urlsplit

import anyio
import httpx2
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.websockets import WebSocket, WebSocketDisconnect

from .kya import checksum, norm_address, personal_hash, recover_address
from .live import LiveService, MAX_FRAME, _iso, _now, jresp
from .store import check_id

FREE_MONTHLY = int(os.getenv("GW_FREE_MONTHLY", "1000"))
MAX_GATEWAYS = {"free": 2, "pro": 50, "enterprise": 500}
MAX_BODY = 1_000_000
MAX_BUFFER = 4_000_000
AUTH_WINDOW_S = 300
FORWARD_HEADERS = {"content-type", "accept", "authorization", "mcp-session-id", "mcp-protocol-version",
                   "payment-signature", "x-payment", "user-agent"}
RETURN_HEADERS = {"content-type", "mcp-session-id", "www-authenticate", "payment-required", "payment-response",
                  "x-payment-response", "retry-after"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS gateways (
    gw_id        TEXT PRIMARY KEY,
    org_id       TEXT NOT NULL,
    name         TEXT NOT NULL,
    upstream     TEXT NOT NULL,
    stream_id    TEXT NOT NULL,
    min_score    INTEGER NOT NULL DEFAULT 0,
    rate_per_min INTEGER NOT NULL DEFAULT 60,
    created_at   TEXT NOT NULL,
    disabled_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_gateways_org ON gateways (org_id);
CREATE TABLE IF NOT EXISTS gw_usage (
    gw_id TEXT NOT NULL, day TEXT NOT NULL, tool TEXT NOT NULL,
    calls INTEGER NOT NULL DEFAULT 0, errors INTEGER NOT NULL DEFAULT 0, denied INTEGER NOT NULL DEFAULT 0,
    payments INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (gw_id, day, tool)
);
"""


class GatewayError(Exception):
    pass


def rpc_error(rid, code: int, message: str, data: dict | None = None) -> dict:
    e = {"code": code, "message": message}
    if data:
        e["data"] = data
    return {"jsonrpc": "2.0", "id": rid, "error": e}


def tool_names(msg) -> list[str]:
    msgs = msg if isinstance(msg, list) else [msg]
    return [m["params"]["name"][:80] for m in msgs if isinstance(m, dict) and m.get("method") == "tools/call"
            and isinstance(m.get("params"), dict) and isinstance(m["params"].get("name"), str)]


def first_id(msg):
    m = msg[0] if isinstance(msg, list) and msg else msg
    return m.get("id") if isinstance(m, dict) else None


def classify(status: int, body: bytes | None, ctype: str) -> str:
    """ok | error | payment_required, from the upstream's answer (only when we hold the whole JSON body)."""
    if status == 402:
        return "payment_required"
    if status >= 400:
        return "error"
    if not body or "json" not in ctype:
        return "ok"
    try:
        data = json.loads(body)
    except ValueError:
        return "ok"
    for m in (data if isinstance(data, list) else [data]):
        if not isinstance(m, dict):
            continue
        if "error" in m:
            return "error"
        r = m.get("result")
        if isinstance(r, dict) and r.get("isError"):
            sc = r.get("structuredContent")
            if isinstance(sc, dict) and ("accepts" in sc or "x402Version" in sc):
                return "payment_required"
            return "error"
    return "ok"


class Gateways:
    def __init__(self, live: LiveService, client: httpx2.AsyncClient | None = None, allow_private: bool = False):
        self.live, self.ledger, self.plans = live, live.ledger, live.plans
        self.db, self.lock = live.db, live.lock
        self.allow_private = allow_private or os.getenv("GW_ALLOW_PRIVATE") == "1"
        self.allow_http = self.allow_private
        self._client = client
        self._rates: dict[tuple[str, str], deque] = defaultdict(deque)
        self._seen_sigs: dict[str, float] = {}
        self._salt = os.getenv("GW_IP_SALT", "") or secrets.token_hex(8)
        with self.lock:
            self.db.executescript(SCHEMA)
            self.db.commit()

    @property
    def client(self) -> httpx2.AsyncClient:
        if self._client is None:
            self._client = httpx2.AsyncClient(
                timeout=httpx2.Timeout(connect=10.0, read=60.0, write=30.0, pool=10.0), follow_redirects=False,
                limits=httpx2.Limits(max_connections=200, max_keepalive_connections=40))
        return self._client

    # ---------------- management ----------------

    async def check_upstream(self, url: str) -> str:
        u = urlsplit((url or "").strip())
        if u.scheme != "https" and not (self.allow_http and u.scheme == "http"):
            raise GatewayError("upstream_url must be a public https:// URL")
        host = (u.hostname or "").lower()
        if not host or host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
            raise GatewayError("upstream host is not public")
        own = urlsplit(self.live.public_url).hostname
        if host == own and not self.allow_private:
            raise GatewayError("a gateway cannot point at this server itself")
        if u.username or u.password:
            raise GatewayError("do not put credentials in the upstream URL")
        if not self.allow_private:
            try:
                infos = await anyio.to_thread.run_sync(socket.getaddrinfo, host, u.port or 443, 0, socket.SOCK_STREAM)
            except OSError:
                raise GatewayError(f"cannot resolve {host}")
            for fam, _, _, _, sa in infos:
                if not ipaddress.ip_address(sa[0]).is_global:
                    raise GatewayError("upstream resolves to a non-public address")
        return url.strip()

    async def create(self, org: dict, name: str, upstream_url: str, min_score: int = 0, rate_per_min: int = 60) -> dict:
        name = " ".join((name or "").split())[:60]
        if not name:
            raise GatewayError("name is required")
        if not 0 <= min_score <= 1000:
            raise GatewayError("min_score must be 0-1000 (0 = open to everyone)")
        if not 1 <= rate_per_min <= 1200:
            raise GatewayError("rate_per_min must be 1-1200")
        plan = self.live.plan_of(org["org_id"])
        with self.lock:
            n = self.db.execute("SELECT COUNT(*) FROM gateways WHERE org_id=? AND disabled_at IS NULL",
                                (org["org_id"],)).fetchone()[0]
        if n >= MAX_GATEWAYS[plan]:
            raise GatewayError(f"the {plan} plan allows {MAX_GATEWAYS[plan]} gateways; call ledger_upgrade_pro for more")
        upstream = await self.check_upstream(upstream_url)
        gw_id = "gw_" + secrets.token_hex(6)
        stream = check_id(f"gw-{gw_id}", "stream_id")
        with self.lock:
            self.db.execute("INSERT INTO gateways (gw_id, org_id, name, upstream, stream_id, min_score, rate_per_min, created_at) "
                            "VALUES (?,?,?,?,?,?,?,?)", (gw_id, org["org_id"], name, upstream, stream, min_score,
                                                         rate_per_min, _iso(_now())))
            self.db.commit()
        self.live._log(org["org_id"], stream, "other", f"Gateway {gw_id} created for {urlsplit(upstream).hostname}", gw_id)
        return self.public(gw_id)

    def get(self, gw_id: str) -> dict | None:
        with self.lock:
            r = self.db.execute("SELECT * FROM gateways WHERE gw_id=? AND disabled_at IS NULL", ((gw_id or "").strip(),)).fetchone()
        return dict(r) if r else None

    def public(self, gw_id: str) -> dict:
        g = self.get(gw_id)
        if not g:
            raise GatewayError("no such gateway")
        base = self.live.public_url
        host = urlsplit(g["upstream"]).hostname
        ws = base.replace("https://", "wss://").replace("http://", "ws://")
        with self.lock:
            tot = self.db.execute("SELECT COALESCE(SUM(calls),0) c, COALESCE(SUM(errors),0) e, COALESCE(SUM(denied),0) d, "
                                  "COALESCE(SUM(payments),0) p FROM gw_usage WHERE gw_id=?", (gw_id,)).fetchone()
        return {"gw_id": g["gw_id"], "name": g["name"], "org_id": g["org_id"], "upstream_host": host,
                "http_url": f"{base}/gw/{gw_id}/mcp", "ws_url": f"{ws}/gw/{gw_id}/ws",
                "caller_gate": ({"required": True, "min_score": g["min_score"], "how": "KYA wallet proof: headers X-Privi-Wallet, "
                                 "X-Privi-Timestamp, X-Privi-Signature (personal_sign of 'Privi Gateway <id>\\nTimestamp: <ts>')"}
                                if g["min_score"] else {"required": False}),
                "rate_limit_per_minute_per_caller": g["rate_per_min"], "created_at": g["created_at"],
                "stats": {"tool_calls": tot["c"], "errors": tot["e"], "denied": tot["d"], "payment_required": tot["p"]},
                "audited_by": "Privi Ledger: every tool call is written to the owner's tamper-evident log"}

    def list_for(self, org_id: str) -> list[dict]:
        with self.lock:
            ids = [r["gw_id"] for r in self.db.execute(
                "SELECT gw_id FROM gateways WHERE org_id=? AND disabled_at IS NULL ORDER BY created_at DESC", (org_id,)).fetchall()]
        return [self.public(i) for i in ids]

    def delete(self, org_id: str, gw_id: str) -> dict:
        with self.lock:
            n = self.db.execute("UPDATE gateways SET disabled_at=? WHERE gw_id=? AND org_id=? AND disabled_at IS NULL",
                                (_iso(_now()), gw_id, org_id)).rowcount
            self.db.commit()
        if not n:
            raise GatewayError("no such gateway for this organization")
        return {"gw_id": gw_id, "disabled": True}

    def stats(self, org_id: str, gw_id: str) -> dict:
        g = self.get(gw_id)
        if not g or g["org_id"] != org_id:
            raise GatewayError("no such gateway for this organization")
        with self.lock:
            by_tool = self.db.execute("SELECT tool, SUM(calls) c, SUM(errors) e, SUM(denied) d, SUM(payments) p FROM gw_usage "
                                      "WHERE gw_id=? GROUP BY tool ORDER BY c DESC LIMIT 100", (gw_id,)).fetchall()
            daily = self.db.execute("SELECT day, SUM(calls) c FROM gw_usage WHERE gw_id=? GROUP BY day ORDER BY day DESC LIMIT 30",
                                    (gw_id,)).fetchall()
        ok, q = self.live.quota(org_id, "gateway", FREE_MONTHLY)
        return {**self.public(gw_id), "by_tool": [{"tool": r["tool"], "calls": r["c"], "errors": r["e"], "denied": r["d"],
                                                   "payment_required": r["p"]} for r in by_tool],
                "daily": {r["day"]: r["c"] for r in daily}, "quota": q, "log_stream": g["stream_id"]}

    def _count(self, gw_id: str, tools: list[str], kind: str) -> None:
        day = _now().date().isoformat()
        col = {"ok": "calls", "error": "errors", "denied": "denied", "payment_required": "payments"}[kind]
        with self.lock:
            for t in tools or ["(protocol)"]:
                self.db.execute(f"INSERT INTO gw_usage (gw_id, day, tool, {col}) VALUES (?,?,?,1) "
                                f"ON CONFLICT(gw_id, day, tool) DO UPDATE SET {col} = {col} + 1", (gw_id, day, t))
            if kind in ("error", "payment_required"):   # a call that reached upstream still counts as a call
                for t in tools or ["(protocol)"]:
                    self.db.execute("UPDATE gw_usage SET calls = calls + 1 WHERE gw_id=? AND day=? AND tool=?", (gw_id, day, t))
            self.db.commit()

    # ---------------- caller identity and limits ----------------

    def _ip_hash(self, ip: str) -> str:
        return hashlib.sha256((self._salt + ip).encode()).hexdigest()[:12]

    def _rate_ok(self, gw: dict, caller: str) -> bool:
        q, now = self._rates[(gw["gw_id"], caller)], time.monotonic()
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= gw["rate_per_min"]:
            return False
        q.append(now)
        if len(self._rates) > 20000:
            for k in [k for k, v in self._rates.items() if not v or now - v[-1] > 60][:5000]:
                self._rates.pop(k, None)
        return True

    def prove(self, gw: dict, h: dict, ip: str) -> tuple[str, str | None]:
        """Who is calling? Returns (caller label, problem). A wallet is believed only with a fresh personal_sign
        by that wallet over this gateway's id and a recent timestamp; each signature works once."""
        wallet = (h.get("x-privi-wallet") or "").strip()
        label = f"ip:{self._ip_hash(ip)}"
        if not wallet:
            return label, None
        try:
            addr = norm_address(wallet)
            ts = int(h.get("x-privi-timestamp", "0"))
            sig = (h.get("x-privi-signature") or "").strip()
            if abs(time.time() - ts) > AUTH_WINDOW_S:
                raise ValueError("timestamp is more than 5 minutes off")
            if sig in self._seen_sigs:
                raise ValueError("signature was already used")
            signer = recover_address(personal_hash(f"Privi Gateway {gw['gw_id']}\nTimestamp: {ts}"),
                                     bytes.fromhex(sig.removeprefix("0x")))
            if signer != addr:
                raise ValueError("signature is not from that wallet")
            now = time.time()
            self._seen_sigs = {k: v for k, v in self._seen_sigs.items() if now - v < AUTH_WINDOW_S * 2}
            self._seen_sigs[sig] = now
            return f"wallet:{checksum(addr)}", None
        except (ValueError, TypeError) as e:
            return label, f"wallet proof failed: {e}"

    def gate(self, gw: dict, caller: str) -> str | None:
        """Passport gate: the proven wallet's live KYA verdict must allow the gateway's minimum score."""
        if not gw["min_score"]:
            return None
        if not caller.startswith("wallet:"):
            return ("this gateway only serves agents with a Privi Passport: send X-Privi-Wallet, X-Privi-Timestamp "
                    "and X-Privi-Signature (personal_sign of 'Privi Gateway <id>\\nTimestamp: <ts>'); bind the wallet "
                    "with kya_bind_wallet first")
        v = self.live.kya.check(caller[7:], gw["min_score"], None, True)
        return None if v["allow"] else "KYA denied: " + "; ".join(v["reasons"] or ["not allowed"])

    # ---------------- the proxy ----------------

    async def forward(self, gw: dict, body: bytes, in_headers, ip: str, *, method: str = "POST",
                      buffer: bool = False, session_id: str | None = None, caller: str | None = None):
        """Returns (status, headers, content, finish) where content is bytes or an async iterator of bytes.
        finish(result_kind, nbytes) must be called once the response has been delivered."""
        t0 = time.monotonic()
        h = {k.lower(): v for k, v in in_headers.items()}
        try:
            msg = json.loads(body) if body else None
        except ValueError:
            return 400, {}, json.dumps(rpc_error(None, -32700, "invalid JSON")).encode(), None
        tools, rid = tool_names(msg), first_id(msg)
        org_id = gw["org_id"]

        def deny(status: int, code: int, text: str, extra: dict | None = None, kind: str = "denied"):
            self._count(gw["gw_id"], tools, kind)
            if tools:
                self._log_call(gw, tools, "gateway", "blocked", text, 0)
            return status, {"content-type": "application/json", "x-privi-gateway": gw["gw_id"]}, \
                json.dumps(rpc_error(rid, code, text, extra)).encode(), None

        k = self.live.is_killed(org_id, gw["stream_id"])
        if k:
            return deny(503, -32002, "Kill switch is on for this gateway" + (f": {k['reason']}" if k["reason"] else ""))
        why = None
        if caller is None:                        # HTTP: every request carries its own proof; WebSocket: proven once per connection
            caller, why = self.prove(gw, h, ip)
        why = why or self.gate(gw, caller)
        if why:
            return deny(401, -32001, why)
        if not self._rate_ok(gw, caller):
            return deny(429, -32003, f"rate limit: {gw['rate_per_min']} requests per minute per caller")
        if tools:
            ok, q = self.live.quota(org_id, "gateway", FREE_MONTHLY)
            if not ok:
                return deny(429, -32004, "this gateway's monthly free quota is used up; the owner can upgrade with ledger_upgrade_pro", q)
        try:
            await self.check_upstream(gw["upstream"])      # re-check DNS on every call (rebinding)
        except GatewayError as e:
            return deny(502, -32005, f"upstream refused: {e}")
        fh = {k: v for k, v in h.items() if k in FORWARD_HEADERS}
        fh["accept-encoding"] = "identity"
        if session_id:
            fh["mcp-session-id"] = session_id
        fh["user-agent"] = "privi-gateway/1 (+https://privi-ledger.onrender.com)"
        if method == "POST" and "content-type" not in fh:
            fh["content-type"] = "application/json"
        fh.setdefault("accept", "application/json, text/event-stream")
        try:
            req = self.client.build_request(method, gw["upstream"], content=body or None, headers=fh)
            resp = await self.client.send(req, stream=True)
        except (httpx2.HTTPError, OSError) as e:
            return deny(502, -32006, f"upstream unreachable: {type(e).__name__}", kind="error")
        ctype = resp.headers.get("content-type", "")
        out_h = {k: v for k, v in resp.headers.items() if k.lower() in RETURN_HEADERS}
        out_h["x-privi-gateway"] = gw["gw_id"]

        def finish(kind: str, nbytes: int = 0) -> None:
            lat = int((time.monotonic() - t0) * 1000)
            if tools:
                self.live.bump(org_id, "gateway", len(tools))
            self._count(gw["gw_id"], tools, kind)
            if tools:
                self._log_call(gw, tools, caller, "success" if kind == "ok" else "failure",
                               f"{kind} in {lat}ms ({resp.status_code})", lat, {"caller": caller, "status": resp.status_code,
                                                                              "result": kind, "bytes": nbytes})

        if buffer or "text/event-stream" not in ctype:
            data = bytearray()
            try:
                async for chunk in resp.aiter_raw():
                    data += chunk
                    if len(data) > MAX_BUFFER:
                        await resp.aclose()
                        return deny(502, -32007, "upstream response too large", kind="error")
            finally:
                await resp.aclose()
            kind = classify(resp.status_code, bytes(data), ctype)
            finish(kind, len(data))
            return resp.status_code, out_h, bytes(data), None

        async def stream():
            n = 0
            try:
                async for chunk in resp.aiter_raw():
                    n += len(chunk)
                    yield chunk
            finally:
                await resp.aclose()
                finish("ok" if resp.status_code < 400 else "error", n)
        return resp.status_code, out_h, stream(), None

    def _log_call(self, gw: dict, tools: list[str], caller: str, outcome: str, text: str, lat: int,
                  details: dict | None = None) -> None:
        """One audit entry per request (not per tool in a batch), unless the owner's log quota is used up."""
        try:
            ok, _ = self.plans.can_write(gw["org_id"], 1)
            if not ok:
                return
            self.ledger.record(gw["org_id"], gw["stream_id"], caller[:120], "tool_call",
                               f"{', '.join(tools)[:200]} via gateway: {text}", gw["gw_id"], outcome,
                               {"tools": tools, "latency_ms": lat, **(details or {})})
        except ValueError:
            pass

    # ---------------- HTTP / WebSocket handlers ----------------

    @staticmethod
    def _ip(request) -> str:
        fwd = request.headers.get("x-forwarded-for", "")
        return (fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "?")) or "?"

    async def http_proxy(self, request: Request) -> Response:
        gw = self.get(request.path_params["gw_id"])
        if not gw:
            return jresp(rpc_error(None, -32004, "no such gateway"), 404)
        if request.method == "GET":
            return Response("This gateway speaks POST (streamable HTTP) and WebSocket.", status_code=405,
                            headers={"Allow": "POST, DELETE"})
        cl = request.headers.get("content-length")
        if cl and cl.isdigit() and int(cl) > MAX_BODY:
            return jresp(rpc_error(None, -32600, "request too large"), 413)
        body = await request.body()
        if len(body) > MAX_BODY:
            return jresp(rpc_error(None, -32600, "request too large"), 413)
        status, headers, content, _ = await self.forward(gw, body, request.headers, self._ip(request), method=request.method)
        if isinstance(content, (bytes, bytearray)):
            return Response(bytes(content), status_code=status, headers=headers)
        return StreamingResponse(content, status_code=status, headers=headers)

    async def http_info(self, request: Request) -> Response:
        try:
            return jresp(self.public(request.path_params["gw_id"]), cors=True)
        except GatewayError as e:
            return jresp({"error": str(e)}, 404)

    async def ws_proxy(self, ws: WebSocket) -> None:
        gw = self.get(ws.path_params["gw_id"])
        if not gw:
            await ws.close(code=4404)
            return
        await ws.accept()
        hdrs = {k.lower(): v for k, v in ws.headers.items()}
        ip = ws.headers.get("x-forwarded-for", "").split(",")[0].strip() or (ws.client.host if ws.client else "?")
        state = {"session": None, "caller": f"ip:{self._ip_hash(ip)}"}
        send_lock, sem = anyio.Lock(), anyio.Semaphore(8)
        notice = None
        if hdrs.get("x-privi-wallet"):                       # proof sent with the WebSocket handshake: check it once
            who, why = self.prove(gw, hdrs, ip)
            why = why or self.gate(gw, who)
            if why:
                notice = {"type": "privi.auth", "ok": False, "error": why, "caller": state["caller"]}
            else:
                state["caller"] = who
            for k in ("x-privi-wallet", "x-privi-timestamp", "x-privi-signature"):
                hdrs.pop(k, None)

        async def send(obj) -> None:
            async with send_lock:
                await ws.send_text(json.dumps(obj, separators=(",", ":")))

        async def one(text: str) -> None:
            async with sem:
                try:
                    status, headers, content, _ = await self.forward(gw, text.encode(), hdrs, ip, buffer=True,
                                                                     session_id=state["session"], caller=state["caller"])
                    if headers.get("mcp-session-id"):
                        state["session"] = headers["mcp-session-id"]
                    ctype = headers.get("content-type", "")
                    raw = bytes(content) if isinstance(content, (bytes, bytearray)) else b""
                    if status == 202 or not raw:
                        return
                    if "text/event-stream" in ctype:
                        for ev in raw.decode("utf-8", "replace").replace("\r\n", "\n").split("\n\n"):
                            data = "\n".join(l[5:].lstrip() for l in ev.split("\n") if l.startswith("data:"))
                            if data:
                                await send(json.loads(data))
                    else:
                        await send(json.loads(raw))
                except (ValueError, WebSocketDisconnect, RuntimeError):
                    pass

        if notice:
            await send(notice)
        try:
            async with anyio.create_task_group() as tg:
                try:
                    while True:
                        text = await ws.receive_text()
                        if len(text) > MAX_FRAME * 8:
                            await send(rpc_error(None, -32600, "frame too large"))
                            continue
                        try:
                            m = json.loads(text)
                        except ValueError:
                            await send(rpc_error(None, -32700, "invalid JSON"))
                            continue
                        if isinstance(m, dict) and m.get("type") == "privi.auth":     # optional in-band credentials
                            for k_in, k_out in (("wallet", "x-privi-wallet"), ("timestamp", "x-privi-timestamp"),
                                                ("signature", "x-privi-signature"), ("authorization", "authorization")):
                                if m.get(k_in) is not None:
                                    hdrs[k_out] = str(m[k_in])
                            caller, why = self.prove(gw, hdrs, ip)
                            why = why or self.gate(gw, caller)
                            if not why:
                                state["caller"] = caller
                            await send({"type": "privi.auth", "ok": why is None, "caller": caller if not why else state["caller"],
                                        **({"error": why} if why else {})})
                            continue
                        tg.start_soon(one, text)
                except (WebSocketDisconnect, RuntimeError):
                    pass
                finally:
                    tg.cancel_scope.cancel()
        except (WebSocketDisconnect, RuntimeError):
            pass

    def http_routes(self):
        return [("/gw/{gw_id}/mcp", ["POST", "GET", "DELETE"], self.http_proxy),
                ("/gw/{gw_id}", ["GET"], self.http_info)]

    def ws_routes(self):
        return [("/gw/{gw_id}/ws", self.ws_proxy)]
