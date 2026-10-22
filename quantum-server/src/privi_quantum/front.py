# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Quantum - https://priviflow.us - dariocanoy@priviflow.us
"""Answer GET/HEAD on the MCP endpoint at once.

This server is stateless streamable HTTP: it offers no server-to-client SSE stream, so per the MCP spec a GET
on the endpoint gets 405. Without this, a GET would hold the connection open until it timed out, which makes
directory health checks and link scanners report the server as down. Browsers get a short human page instead.
"""

from __future__ import annotations

import json

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{name} MCP endpoint</title><style>body{{font:16px/1.5 system-ui,sans-serif;max-width:640px;margin:48px auto;padding:0 16px;color:#16181d;background:#f7f8fa}}
code,pre{{font:14px ui-monospace,monospace;background:#eef1f6;border-radius:6px}}pre{{padding:12px;overflow-x:auto}}code{{padding:1px 4px}}
@media (prefers-color-scheme:dark){{body{{color:#e8eaee;background:#0f1115}}code,pre{{background:#1d222b}}}}</style></head><body>
<h1>{name}</h1><p>This address is an MCP server endpoint for AI agents (streamable HTTP, POST). Add it to your MCP client:</p>
<pre>{{ "mcpServers": {{ "{slug}": {{ "url": "{url}" }} }} }}</pre>
<p>Everything Privi offers, with live status: <a href="https://privi-hub.onrender.com">Privi Hub</a>.</p></body></html>"""


CORS = [(b"access-control-allow-origin", b"*"),
        (b"access-control-expose-headers", b"Mcp-Session-Id, PAYMENT-REQUIRED, PAYMENT-RESPONSE, X-PAYMENT-RESPONSE")]


class QuickGet:
    def __init__(self, app, name: str, slug: str, public_url: str, path: str = "/mcp"):
        self.app, self.path = app, path
        self.html = PAGE.format(name=name, slug=slug, url=public_url.rstrip("/") + path).encode()
        self.body = json.dumps({"jsonrpc": "2.0", "id": None, "error": {
            "code": -32000, "message": "Method not allowed: this MCP server takes JSON-RPC over POST (streamable HTTP, stateless)"}}).encode()

    async def __call__(self, scope, receive, send):
        on_path = scope["type"] == "http" and scope.get("path", "").rstrip("/") == self.path
        if on_path and scope.get("method") == "OPTIONS":
            # CORS preflight: browser-based MCP clients (web inspectors, demo pages) can call this endpoint.
            # Safe with "*": callers send their own keys in headers; no cookies or ambient credentials are used.
            await send({"type": "http.response.start", "status": 204, "headers": CORS + [
                (b"access-control-allow-methods", b"POST, GET, DELETE, OPTIONS"),
                (b"access-control-allow-headers", b"Content-Type, Accept, Authorization, Mcp-Session-Id, "
                                                   b"Mcp-Protocol-Version, Last-Event-ID, PAYMENT-SIGNATURE, X-PAYMENT"),
                (b"access-control-max-age", b"86400"), (b"content-length", b"0")]})
            await send({"type": "http.response.body", "body": b""})
            return
        if on_path and scope.get("method") not in ("GET", "HEAD"):
            async def send_cors(message):
                if message["type"] == "http.response.start":
                    have = {k.lower() for k, _ in message.get("headers", [])}
                    message = {**message, "headers": list(message.get("headers", [])) +
                               [h for h in CORS if h[0] not in have]}
                await send(message)
            await self.app(scope, receive, send_cors)
            return
        if on_path and scope.get("method") in ("GET", "HEAD"):
            headers = dict(scope.get("headers") or [])
            accept = headers.get(b"accept", b"").decode("latin-1").lower()
            if "text/html" in accept and "text/event-stream" not in accept:
                status, ctype, body = 200, b"text/html; charset=utf-8", self.html
            else:
                status, ctype, body = 405, b"application/json", self.body
            await send({"type": "http.response.start", "status": status,
                        "headers": CORS + [(b"content-type", ctype), (b"allow", b"POST, DELETE, OPTIONS"),
                                    (b"content-length", str(len(body)).encode()), (b"cache-control", b"no-store")]})
            await send({"type": "http.response.body", "body": b"" if scope["method"] == "HEAD" else body})
            return
        await self.app(scope, receive, send)
