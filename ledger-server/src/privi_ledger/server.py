"""Privi Ledger MCP server: tamper-evident audit logs for AI agents.

Free:          ledger_pricing, ledger_check_receipt
Paid (x402):   ledger_audit_stream      (auditors, USDC on Base)
Org API key:   ledger_record_action, ledger_read_stream, ledger_list_streams
Admin (HTTP):  POST /admin/orgs         (create an organization and its API key)
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
from typing import Annotated, Any

from mcp.server.mcpserver import Context, MCPServer
from mcp_types import CallToolResult, TextContent, ToolAnnotations
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse

from .config import Settings
from .store import ACTION_TYPES, OUTCOMES, Ledger, check_id
from .x402 import Facilitator, Paywall

__version__ = "0.1.0"
SOURCE = "https://github.com/canoydario847-cloud/Privi-Network/tree/main/ledger-server"

INSTRUCTIONS = """\
Privi Ledger keeps a tamper-evident record of what AI agents do. Each action is
appended to a stream (usually one per agent) and linked to the previous one by a
SHA-256 fingerprint, so any later edit, deletion or reordering is detectable.

Agents: call ledger_record_action after each meaningful action (tool calls, data
access or changes, payments, messages, decisions). Keep the returned entry_hash
as a receipt. Requires the organization's API key (Authorization: Bearer).

Auditors: ledger_audit_stream checks a stream's integrity without revealing its
contents (paid per call with x402, USDC on Base). ledger_check_receipt is free."""

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)


def _result(data: dict[str, Any], is_error: bool = False) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(data))],
                          structured_content=data, is_error=is_error)


def _bearer(headers) -> str:
    auth = (headers or {}).get("authorization", "")
    return auth[7:].strip() if auth.lower().startswith("bearer ") else ""


def build_server(settings: Settings | None = None, ledger: Ledger | None = None,
                 facilitator: Facilitator | None = None) -> MCPServer:
    settings = settings or Settings.from_env()
    ledger = ledger or Ledger(settings.db_path)
    paywall = Paywall(settings, facilitator)

    mcp = MCPServer(
        name="privi-ledger", title="Privi Ledger",
        description="Tamper-evident audit logs for AI agents; auditors verify integrity, paid per call via x402.",
        instructions=INSTRUCTIONS, website_url=SOURCE, version=__version__,
    )

    def org_from(ctx: Context) -> dict | None:
        headers = ctx.headers
        key = _bearer(headers) if headers is not None else os.getenv("LEDGER_LOCAL_ORG_KEY", "")
        return ledger.org_for_key(key)

    unauthorized = _result({"error": "a valid organization API key is required (Authorization: Bearer <key>)"},
                           is_error=True)

    # ---------------- free ----------------

    @mcp.tool(title="Ledger pricing", annotations=READ_ONLY)
    def ledger_pricing() -> dict[str, Any]:
        """List Privi Ledger tools, what each costs, and how to get an organization key."""
        return {
            "payments_enabled": settings.payments_enabled,
            "currency": "USDC", "network": settings.network["network"], "network_name": settings.network_key,
            "pay_to": settings.pay_to or None,
            "tools": {
                "ledger_pricing": "free",
                "ledger_check_receipt": "free",
                "ledger_audit_stream": f"${settings.prices_usd['ledger_audit_stream']} per call (x402)",
                "ledger_record_action": "organization API key",
                "ledger_read_stream": "organization API key",
                "ledger_list_streams": "organization API key",
            },
            "action_types": list(ACTION_TYPES), "outcomes": list(OUTCOMES),
            "get_a_key": SOURCE,
        }

    @mcp.tool(title="Check a receipt", annotations=READ_ONLY)
    def ledger_check_receipt(
        entry_hash: Annotated[str, Field(description="64-character hex entry_hash returned when the action was recorded")],
    ) -> CallToolResult:
        """Confirm that an action receipt exists in the ledger and when it was recorded. Reveals no action contents. Free."""
        try:
            hit = ledger.find_entry(entry_hash)
        except ValueError as e:
            return _result({"error": str(e)}, is_error=True)
        return _result({"found": True, **hit} if hit else {"found": False})

    # ---------------- paid ----------------

    @mcp.tool(title="Audit a stream", annotations=READ_ONLY)
    async def ledger_audit_stream(
        org_id: Annotated[str, Field(description="Organization ID, e.g. org_1a2b3c4d5e6f7a8b")],
        stream_id: Annotated[str, Field(description="Stream ID, usually the agent's name")],
        ctx: Context,
    ) -> CallToolResult:
        """Check whether an agent's action log is intact: entry count, time span, action and failure
        counts, head hash, and where tampering broke the chain if it did. Does not reveal the actions
        themselves. Paid per call via x402."""

        async def work() -> dict[str, Any]:
            try:
                oid, sid = check_id(org_id, "org_id"), check_id(stream_id, "stream_id")
            except ValueError as e:
                return {"found": False, "error": str(e)}
            a = ledger.audit(oid, sid)
            return {"found": True, **a} if a else {"found": False, "org_id": oid, "stream_id": sid}

        return await paywall.run("ledger_audit_stream", "Integrity audit of an AI agent's action log",
                                 dict(ctx.request_context.meta or {}), work)

    # ---------------- organization ----------------

    @mcp.tool(title="Record an agent action",
              annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False))
    def ledger_record_action(
        stream_id: Annotated[str, Field(description="Stream to append to, usually the agent's name, e.g. 'billing-agent'")],
        actor: Annotated[str, Field(description="Who acted: agent name, model, or user on whose behalf")],
        action_type: Annotated[str, Field(description=f"One of: {', '.join(ACTION_TYPES)}")],
        summary: Annotated[str, Field(description="One-line description of what was done")],
        ctx: Context,
        resource: Annotated[str, Field(description="What was acted on: URL, file, record ID, account")] = "",
        outcome: Annotated[str, Field(description=f"One of: {', '.join(OUTCOMES)}")] = "success",
        details: Annotated[dict[str, Any] | None, Field(description="Optional structured details (JSON object, under 16 KB)")] = None,
    ) -> CallToolResult:
        """Append an action to the organization's tamper-evident log. Returns the entry with its
        entry_hash receipt. Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        try:
            e = ledger.record(org["org_id"], stream_id, actor, action_type, summary, resource, outcome, details)
        except ValueError as err:
            return _result({"error": str(err)}, is_error=True)
        return _result({"recorded": True, "entry": e})

    @mcp.tool(title="Read a stream", annotations=READ_ONLY)
    def ledger_read_stream(
        stream_id: Annotated[str, Field(description="Stream ID")],
        ctx: Context,
        after_seq: Annotated[int, Field(description="Return entries after this sequence number", ge=0)] = 0,
        limit: Annotated[int, Field(description="Max entries to return", ge=1, le=500)] = 100,
    ) -> CallToolResult:
        """Read your organization's entries in a stream, oldest first, with an integrity check of the
        whole stream. Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        try:
            page = ledger.entries(org["org_id"], stream_id, after_seq, limit)
            check = ledger.check_chain(ledger.entries(org["org_id"], stream_id))
        except ValueError as err:
            return _result({"error": str(err)}, is_error=True)
        for e in page:
            e["details"] = json.loads(e["details"])
        return _result({
            "stream_id": stream_id, "entries": page,
            "next_after_seq": page[-1]["seq"] if len(page) == limit else None,
            "integrity": {"intact": check.valid, "broken_at_seq": check.broken_at_seq,
                          "reason": check.reason, "entry_count": check.entry_count},
        })

    @mcp.tool(title="List streams", annotations=READ_ONLY)
    def ledger_list_streams(ctx: Context) -> CallToolResult:
        """List your organization's streams with entry counts. Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        return _result({"org_id": org["org_id"], "organization": org["name"], "streams": ledger.streams(org["org_id"])})

    # ---------------- http ----------------

    @mcp.custom_route("/admin/orgs", methods=["POST"], include_in_schema=False)
    async def create_org(request: Request) -> JSONResponse:
        token = _bearer(request.headers)
        if not settings.admin_key or not token or not hmac.compare_digest(token, settings.admin_key):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        try:
            body = await request.json()
            org = ledger.create_org(str(body.get("name", "")))
        except (ValueError, AttributeError) as e:
            return JSONResponse({"error": str(e) or "send JSON like {\"name\": \"Acme Inc\"}"}, status_code=400)
        return JSONResponse({**org, "note": "Store api_key now; it cannot be shown again."}, status_code=201)

    @mcp.custom_route("/health", methods=["GET"], include_in_schema=False)
    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"ok": True, "service": "privi-ledger", "version": __version__})

    @mcp.custom_route("/", methods=["GET"], include_in_schema=False)
    async def index(_: Request) -> JSONResponse:
        return JSONResponse({"service": "Privi Ledger MCP", "mcp_endpoint": "/mcp",
                             "payments": "x402 (USDC on Base)" if settings.payments_enabled else "disabled",
                             "source": SOURCE})

    return mcp


def main() -> None:
    p = argparse.ArgumentParser(description="Privi Ledger MCP server")
    p.add_argument("--stdio", action="store_true", help="run over stdio instead of HTTP")
    p.add_argument("--host", default=os.getenv("HOST", "0.0.0.0"))
    p.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000")))
    args = p.parse_args()
    mcp = build_server()
    if args.stdio:
        mcp.run("stdio")
        return
    import uvicorn
    uvicorn.run(mcp.streamable_http_app(host=args.host, stateless_http=True, json_response=True),
                host=args.host, port=args.port)


if __name__ == "__main__":
    main()
