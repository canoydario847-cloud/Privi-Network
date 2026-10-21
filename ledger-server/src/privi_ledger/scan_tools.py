"""MCP tools and HTTP routes for Privi Scan (the public MCP trust registry)."""

from __future__ import annotations

from typing import Annotated, Any, Callable

import anyio
from mcp.server.mcpserver import Context, MCPServer
from mcp_types import ToolAnnotations
from pydantic import Field
from starlette.requests import Request
from starlette.responses import Response

from .live import jresp
from .scanner import LIVE_PROBES_PER_MIN, MAX_WATCH, PAGE, SCAN_ORG_ID, SCAN_STREAM, Scanner, ScanError, badge

READ = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
OPEN = ToolAnnotations(readOnlyHint=True, openWorldHint=True)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)


def register(mcp: MCPServer, scan: Scanner, *, org_from: Callable, result: Callable, unauthorized) -> None:
    base = scan.public_url

    def err(e: Exception):
        return result({"error": str(e)}, is_error=True)

    @mcp.tool(title="Check an MCP server before connecting", annotations=OPEN)
    async def mcp_server_check(
        url: Annotated[str, Field(description="The server's streamable-HTTP MCP endpoint, e.g. https://example.com/mcp")],
        expected_tools_hash: Annotated[str | None, Field(description="The tools_hash you approved earlier; Privi tells you if "
                                                                     "the tools changed since then (rug-pull check)")] = None,
    ) -> Any:
        """Free safety check for any remote MCP server, before an agent connects to it or after it was approved. Privi
        reads the server's tool list (it never calls a tool) and returns a verdict: ok, caution, danger (tool poisoning:
        hidden instructions, concealment from the user, requests for keys or private files, tool shadowing, invisible
        characters), changed (tools differ from expected_tools_hash), unverified (tools behind auth) or unreachable. Also
        returns the tools_hash to pin, a grade A-F and a link to the server's public history. Every first observation and
        change is recorded in Privi's on-chain-anchored transparency log. No key needed."""
        try:
            return await anyio.to_thread.run_sync(lambda: scan.check(url, expected_tools_hash))
        except ScanError as e:
            return err(e)

    @mcp.tool(title="Search the MCP trust registry", annotations=READ)
    def scan_search(
        query: Annotated[str, Field(description="Words to match in name, description or URL; empty lists everything")] = "",
        grade: Annotated[str, Field(description="Only this grade: A, B, C, D or F")] = "",
        sort: Annotated[str, Field(description="name, score, risk, changed or new")] = "score",
        limit: Annotated[int, Field(ge=1, le=100)] = 20,
        offset: Annotated[int, Field(ge=0)] = 0,
    ) -> dict[str, Any]:
        """Search Privi Scan, the public directory of remote MCP servers from the official MCP Registry, each with a
        safety grade, verdict, tool count and change history. Use it to find a trustworthy server for a job. Free."""
        return scan.search(query, grade, "", limit, offset, False, sort)

    @mcp.tool(title="Privi Scan: one server in full", annotations=READ)
    def scan_server(
        server_id: Annotated[str, Field(description="mcp_... id from scan_search or mcp_server_check, or the endpoint URL")],
        include_history: bool = True,
    ) -> Any:
        """Full report for one MCP server: every tool definition with its hash, all findings with evidence, the change
        history (what was added, removed or modified, and when) and the transparency-log proof. Free."""
        try:
            sid = scan.resolve(server_id)
            d = scan.public(scan.get(sid))
            if include_history:
                d["history"] = scan.history(sid, 50)
            return d
        except ScanError as e:
            return err(e)

    @mcp.tool(title="Privi Scan: recent tool changes", annotations=READ)
    def scan_changes(limit: Annotated[int, Field(ge=1, le=100)] = 25) -> list[dict]:
        """The latest MCP servers whose tool definitions changed after they were first observed (possible rug pulls),
        newest first. Subscribe to the Live channel 'scan' for these as they happen. Free."""
        return scan.changes(limit)

    @mcp.tool(title="Privi Scan: totals", annotations=READ)
    def scan_stats() -> dict[str, Any]:
        """How many MCP servers Privi Scan tracks, by status and grade, tools indexed, changes recorded and how to verify
        the evidence. Free."""
        return {**scan.stats(), "directory": f"{base}/scan"}

    @mcp.tool(title="Watch an MCP server (pin its tools)", annotations=WRITE)
    def scan_watch(
        ctx: Context,
        server: Annotated[str, Field(description="mcp_... id or endpoint URL")],
        repin: Annotated[bool, Field(description="Pin the current tools_hash as approved (default true)")] = True,
    ) -> Any:
        """Pin the server's current tools as approved and get a real-time event on your private Live 'org' channel the
        moment they change, a risk appears or the server goes down. Free plan: 3 servers; Pro: 500. Needs the org key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        try:
            return scan.watch(org["org_id"], server, repin)
        except ScanError as e:
            return err(e)

    @mcp.tool(title="Stop watching an MCP server", annotations=WRITE)
    def scan_unwatch(ctx: Context, server: Annotated[str, Field(description="mcp_... id or endpoint URL")]) -> Any:
        """Remove a server from your watchlist. Needs the org key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        try:
            return scan.unwatch(org["org_id"], server)
        except ScanError as e:
            return err(e)

    @mcp.tool(title="Your watched MCP servers", annotations=READ)
    def scan_watchlist(ctx: Context) -> Any:
        """Your watched servers with their pinned tools_hash and whether each has drifted since you pinned it. Needs the
        org key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        return scan.watchlist(org["org_id"])

    @mcp.tool(title="Claim your MCP server's listing", annotations=WRITE)
    def scan_claim_start(ctx: Context, server: Annotated[str, Field(description="mcp_... id or endpoint URL")]) -> Any:
        """Start proving you operate an MCP server listed in Privi Scan. Returns a token to publish at
        https://<your host>/.well-known/privi-scan.txt. Verified owners get an owner-verified badge, unlimited rescans,
        change alerts and control over the listing. Needs the org key (create_org is free)."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        try:
            return scan.claim_start(org["org_id"], server)
        except ScanError as e:
            return err(e)

    @mcp.tool(title="Finish claiming your MCP server", annotations=WRITE)
    async def scan_claim_verify(ctx: Context, server: Annotated[str, Field(description="mcp_... id or endpoint URL")]) -> Any:
        """Check the token at /.well-known/privi-scan.txt and mark your organization as the verified owner."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        try:
            return await anyio.to_thread.run_sync(lambda: scan.claim_verify(org["org_id"], server))
        except ScanError as e:
            return err(e)

    @mcp.tool(title="Show or hide your server's listing", annotations=WRITE)
    def scan_owner_listing(ctx: Context, server: Annotated[str, Field(description="mcp_... id or endpoint URL")],
                           listed: bool) -> Any:
        """Verified owners only: hide the server from the directory (opt-out) or show it again. History already in the
        transparency log cannot be removed."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        try:
            return scan.owner_listing(org["org_id"], server, listed)
        except ScanError as e:
            return err(e)

    @mcp.tool(title="Rescan an MCP server now", annotations=OPEN)
    async def scan_rescan(ctx: Context, server: Annotated[str, Field(description="mcp_... id or endpoint URL")]) -> Any:
        """Probe the server immediately instead of waiting for the next crawl (every ~6 hours). For the verified owner
        or Pro organizations."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        try:
            return await anyio.to_thread.run_sync(lambda: scan.rescan(org["org_id"], server))
        except ScanError as e:
            return err(e)


def http_routes(scan: Scanner) -> list[tuple[str, list[str], Callable]]:
    async def page(_: Request) -> Response:
        return Response(PAGE.read_text(encoding="utf-8"), media_type="text/html; charset=utf-8",
                        headers={"Cache-Control": "public, max-age=300"})

    async def api_servers(request: Request) -> Response:
        q = request.query_params
        try:
            lim, off = int(q.get("limit", "50")), int(q.get("offset", "0"))
        except ValueError:
            return jresp({"error": "limit and offset must be numbers"}, 400, cors=True)
        return jresp(scan.search(q.get("q", ""), q.get("grade", ""), q.get("verdict", ""), lim, off,
                                 q.get("all") == "1", q.get("sort", "score")), cors=True)

    async def api_server(request: Request) -> Response:
        sid = request.path_params["server_id"]
        try:
            d = scan.public(scan.get(sid))
            d["history"] = scan.history(sid, 50, with_tools=request.query_params.get("tools") == "1")
            return jresp(d, cors=True)
        except ScanError as e:
            return jresp({"error": str(e)}, 404, cors=True)

    async def api_check(request: Request) -> Response:
        url = request.query_params.get("url", "")
        try:
            return jresp(await anyio.to_thread.run_sync(lambda: scan.check(url, request.query_params.get("expected"))), cors=True)
        except ScanError as e:
            return jresp({"error": str(e)}, 400, cors=True)

    async def api_changes(request: Request) -> Response:
        return jresp(scan.changes(int(request.query_params.get("limit", "50") or 50)), cors=True)

    async def api_stats(_: Request) -> Response:
        return jresp(scan.stats(), cors=True)

    async def svg(request: Request) -> Response:
        sid = request.path_params["server_id"].removesuffix(".svg")
        row = scan._row(sid)
        return Response(badge(None if not row or row.get("hidden") else row), media_type="image/svg+xml",
                        headers={"Cache-Control": "public, max-age=900", "Access-Control-Allow-Origin": "*"})

    return [("/scan", ["GET"], page), ("/scan/s/{server_id}", ["GET"], page),
            ("/scan/api/servers", ["GET"], api_servers), ("/scan/api/servers/{server_id}", ["GET"], api_server),
            ("/scan/api/check", ["GET"], api_check), ("/scan/api/changes", ["GET"], api_changes),
            ("/scan/api/stats", ["GET"], api_stats), ("/scan/badge/{server_id}", ["GET"], svg)]
