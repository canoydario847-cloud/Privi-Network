# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Call - https://priviflow.us - dariocanoy@priviflow.us
"""Route MCP tool calls to agents on the Privi Call network.

Speed comes from keeping warm connections: one shared HTTP client with a keep-alive pool, so
a routed call skips DNS, TCP and TLS setup after the first one; sessions and tool lists are
cached per agent. Only public HTTPS endpoints can join the network (no private addresses).
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import socket
import time
from urllib.parse import urlsplit

import httpx2 as httpx

PROTOCOL = "2025-06-18"
CLIENT_INFO = {"name": "privi-call", "version": "0.1.0"}


class RouteError(RuntimeError):
    pass


def check_public_endpoint(url: str) -> str:
    """Reject anything that is not https:// on a public internet address."""
    parts = urlsplit(url.strip())
    if parts.scheme != "https" or not parts.hostname:
        raise RouteError("agent endpoint must be an https:// URL")
    if parts.username or parts.password:
        raise RouteError("agent endpoint must not contain credentials")
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise RouteError(f"cannot resolve {parts.hostname}") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise RouteError("agent endpoint must be on the public internet")
    return url.strip()


def _parse(resp: httpx.Response) -> dict:
    text = resp.text
    if "text/event-stream" in resp.headers.get("content-type", "") or text.lstrip().startswith(("event:", "data:")):
        datas = [l[5:].strip() for l in text.splitlines() if l.startswith("data:")]
        for d in reversed(datas):
            try:
                msg = json.loads(d)
            except ValueError:
                continue
            if "result" in msg or "error" in msg:
                return msg
        raise RouteError("agent sent no JSON-RPC response")
    try:
        return resp.json()
    except ValueError as e:
        raise RouteError(f"agent sent HTTP {resp.status_code} without JSON") from e


class Router:
    def __init__(self, timeout: float = 30.0, transport: httpx.AsyncBaseTransport | None = None,
                 check_endpoints: bool = True):
        self.timeout = timeout
        self.check_endpoints = check_endpoints
        self._client = httpx.AsyncClient(
            timeout=timeout, transport=transport, follow_redirects=False,
            limits=httpx.Limits(max_connections=200, max_keepalive_connections=50, keepalive_expiry=120))
        self._sessions: dict[str, str | None] = {}
        self._tools: dict[str, tuple[float, list]] = {}
        self._ids = 0

    async def aclose(self) -> None:
        await self._client.aclose()

    def _next_id(self) -> int:
        self._ids += 1
        return self._ids

    async def _post(self, endpoint: str, body: dict, session: str | None, extra: dict | None = None) -> httpx.Response:
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                   "MCP-Protocol-Version": PROTOCOL, "User-Agent": "privi-call/0.1 (+https://privi-call.onrender.com)"}
        if session:
            headers["Mcp-Session-Id"] = session
        headers.update(extra or {})
        try:
            return await self._client.post(endpoint, json=body, headers=headers)
        except httpx.TimeoutException as e:
            raise RouteError(f"agent did not answer within {self.timeout:.0f}s") from e
        except httpx.HTTPError as e:
            raise RouteError(f"could not reach agent: {e.__class__.__name__}") from e

    async def _session(self, endpoint: str, fresh: bool = False) -> str | None:
        if not fresh and endpoint in self._sessions:
            return self._sessions[endpoint]
        init = {"jsonrpc": "2.0", "id": self._next_id(), "method": "initialize",
                "params": {"protocolVersion": PROTOCOL, "capabilities": {}, "clientInfo": CLIENT_INFO}}
        r = await self._post(endpoint, init, None)
        msg = _parse(r)
        if "error" in msg:
            raise RouteError(f"agent refused initialize: {msg['error'].get('message', msg['error'])}")
        sid = r.headers.get("mcp-session-id")
        await self._post(endpoint, {"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)
        self._sessions[endpoint] = sid
        return sid

    async def rpc(self, endpoint: str, method: str, params: dict, extra_headers: dict | None = None) -> dict:
        if self.check_endpoints:
            await asyncio.to_thread(check_public_endpoint, endpoint)
        sid = await self._session(endpoint)
        body = {"jsonrpc": "2.0", "id": self._next_id(), "method": method, "params": params}
        r = await self._post(endpoint, body, sid, extra_headers)
        if r.status_code in (400, 404) and sid is not None:  # session expired on the agent's side
            sid = await self._session(endpoint, fresh=True)
            r = await self._post(endpoint, body, sid, extra_headers)
        msg = _parse(r)
        if "error" in msg:
            err = msg["error"]
            raise RouteError(f"agent error: {err.get('message', err) if isinstance(err, dict) else err}")
        return msg.get("result") or {}

    async def list_tools(self, endpoint: str, max_age: float = 600) -> list[dict]:
        hit = self._tools.get(endpoint)
        if hit and time.monotonic() - hit[0] < max_age:
            return hit[1]
        res = await self.rpc(endpoint, "tools/list", {})
        tools = [{"name": t.get("name"), "title": t.get("title"), "description": (t.get("description") or "")[:600],
                  "inputSchema": t.get("inputSchema", {})} for t in res.get("tools", [])]
        self._tools[endpoint] = (time.monotonic(), tools)
        return tools

    async def call_tool(self, endpoint: str, tool: str, arguments: dict, meta: dict | None = None,
                        extra_headers: dict | None = None) -> tuple[dict, float]:
        params: dict = {"name": tool, "arguments": arguments or {}}
        if meta:
            params["_meta"] = meta
        t0 = time.perf_counter()
        res = await self.rpc(endpoint, "tools/call", params, extra_headers)
        return res, (time.perf_counter() - t0) * 1000
