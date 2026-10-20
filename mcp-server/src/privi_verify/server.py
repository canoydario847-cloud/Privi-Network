"""Privi Verify MCP server.

Free tools:   privi_pricing, privi_lookup_fingerprint
Paid tools:   privi_verify_lot, privi_chain_of_custody   (x402, USDC on Base)
Write tool:   privi_record_event                          (manufacturer API key)
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
from .store import EVENT_TYPES, LotStore, seed_demo
from .x402 import Facilitator, Paywall

__version__ = "0.1.0"

INSTRUCTIONS = """\
Privi Verify checks where a manufactured lot came from and whether its records
were changed after the fact. Each lot's events (received, produced, inspected,
shipped, ...) are linked by SHA-256 fingerprints, so any edit to history is detectable.

Start with privi_pricing. privi_lookup_fingerprint is free. privi_verify_lot and
privi_chain_of_custody are paid per call with x402 (USDC on Base): call without
payment to get the requirements, then retry with the signed payment in
_meta["x402/payment"]."""

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)


def _text_result(data: dict[str, Any], is_error: bool = False) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(data))],
        structured_content=data,
        is_error=is_error,
    )


def _meta(ctx: Context) -> dict:
    try:
        return dict(ctx.request_context.meta or {})
    except Exception:
        return {}


def build_server(
    settings: Settings | None = None,
    store: LotStore | None = None,
    facilitator: Facilitator | None = None,
) -> MCPServer:
    settings = settings or Settings.from_env()
    store = store or LotStore(settings.db_path)
    if os.getenv("PRIVI_SEED_DEMO") == "1":
        seed_demo(store)
    paywall = Paywall(settings, facilitator)

    mcp = MCPServer(
        name="privi-verify",
        title="Privi Verify",
        description="Verify manufacturing lot provenance and chain of custody, paid per call with x402.",
        instructions=INSTRUCTIONS,
        website_url="https://github.com/canoydario847-cloud/Privi-Network/tree/main/mcp-server",
        version=__version__,
    )

    # ---------------- free ----------------

    @mcp.tool(title="Privi pricing", annotations=READ_ONLY)
    def privi_pricing() -> dict[str, Any]:
        """List Privi Verify tools, what each costs, and how payment works."""
        net = settings.network
        return {
            "payments_enabled": settings.payments_enabled,
            "currency": "USDC",
            "network": net["network"],
            "network_name": settings.network_key,
            "pay_to": settings.pay_to or None,
            "protocol": "x402 v2 over MCP (_meta['x402/payment'])",
            "tools": {
                "privi_pricing": "free",
                "privi_lookup_fingerprint": "free",
                "privi_verify_lot": f"${settings.prices_usd['privi_verify_lot']} per call",
                "privi_chain_of_custody": f"${settings.prices_usd['privi_chain_of_custody']} per call",
                "privi_record_event": "manufacturers only (API key)",
            },
        }

    @mcp.tool(title="Look up a record fingerprint", annotations=READ_ONLY)
    def privi_lookup_fingerprint(
        fingerprint: Annotated[str, Field(description="64-character hex SHA-256 record fingerprint")],
    ) -> CallToolResult:
        """Check whether a record fingerprint (from a label, certificate or document) exists in Privi. Free."""
        try:
            hit = store.find_fingerprint(fingerprint)
        except ValueError as e:
            return _text_result({"error": str(e)}, is_error=True)
        if not hit:
            return _text_result({"found": False})
        return _text_result({"found": True, **hit})

    # ---------------- paid ----------------

    @mcp.tool(title="Verify a lot", annotations=READ_ONLY)
    async def privi_verify_lot(
        lot_code: Annotated[str, Field(description="Lot or batch code to verify")],
        ctx: Context,
    ) -> CallToolResult:
        """Verify a lot: product, first and latest custody events, recall status, and whether
        its record history is intact. Paid per call via x402."""

        async def work() -> dict[str, Any]:
            try:
                s = store.summary(lot_code)
            except ValueError as e:
                return {"found": False, "error": str(e)}
            return {"found": True, **s} if s else {"found": False, "lot_code": lot_code}

        return await paywall.run(
            "privi_verify_lot", "Verify a manufacturing lot's provenance and record integrity", _meta(ctx), work
        )

    @mcp.tool(title="Chain of custody", annotations=READ_ONLY)
    async def privi_chain_of_custody(
        lot_code: Annotated[str, Field(description="Lot or batch code")],
        ctx: Context,
    ) -> CallToolResult:
        """Full ordered event history for a lot with each event's fingerprint, plus an
        integrity check of the whole chain. Paid per call via x402."""

        async def work() -> dict[str, Any]:
            try:
                evs = store.events(lot_code)
            except ValueError as e:
                return {"found": False, "error": str(e)}
            if not evs:
                return {"found": False, "lot_code": lot_code}
            check = store.check_chain(evs)
            return {
                "found": True,
                "lot_code": evs[0]["lot_code"],
                "integrity": {"valid": check.valid, "broken_at_seq": check.broken_at_seq, "reason": check.reason},
                "events": evs,
            }

        return await paywall.run(
            "privi_chain_of_custody", "Full chain of custody for a manufacturing lot", _meta(ctx), work
        )

    # ---------------- manufacturer write ----------------

    @mcp.tool(title="Record a lot event", annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    def privi_record_event(
        lot_code: Annotated[str, Field(description="Lot or batch code")],
        event_type: Annotated[str, Field(description=f"One of: {', '.join(EVENT_TYPES)}")],
        location: Annotated[str, Field(description="Where it happened, e.g. 'Plant 2, Port Huron MI'")],
        actor: Annotated[str, Field(description="Company or person responsible")],
        ctx: Context,
        product: Annotated[str, Field(description="Product name or part number")] = "",
        quantity: Annotated[str, Field(description="Quantity with units, e.g. '500 kg'")] = "",
        notes: str = "",
    ) -> CallToolResult:
        """Append an event to a lot's history (manufacturers only). Requires
        'Authorization: Bearer <key>' with a key from PRIVI_WRITE_KEYS. Over stdio,
        writes are allowed only when PRIVI_ALLOW_LOCAL_WRITES=1."""
        headers = ctx.headers
        if headers is None:
            allowed = os.getenv("PRIVI_ALLOW_LOCAL_WRITES") == "1"
        else:
            auth = headers.get("authorization", "")
            token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
            allowed = bool(token) and any(hmac.compare_digest(token, k) for k in settings.write_keys)
        if not allowed:
            return _text_result({"error": "not authorized to record events"}, is_error=True)
        try:
            ev = store.record_event(lot_code, event_type, location, actor, product, quantity, notes)
        except ValueError as e:
            return _text_result({"error": str(e)}, is_error=True)
        return _text_result({"recorded": True, "event": ev})

    # ---------------- http extras ----------------

    @mcp.custom_route("/health", methods=["GET"], include_in_schema=False)
    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"ok": True, "service": "privi-verify", "version": __version__})

    @mcp.custom_route("/", methods=["GET"], include_in_schema=False)
    async def index(_: Request) -> JSONResponse:
        return JSONResponse({
            "service": "Privi Verify MCP",
            "mcp_endpoint": "/mcp",
            "payments": "x402 (USDC on Base)" if settings.payments_enabled else "disabled",
            "source": "https://github.com/canoydario847-cloud/Privi-Network/tree/main/mcp-server",
        })

    return mcp


def main() -> None:
    parser = argparse.ArgumentParser(description="Privi Verify MCP server")
    parser.add_argument("--stdio", action="store_true", help="run over stdio instead of HTTP")
    parser.add_argument("--host", default=os.getenv("HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000")))
    args = parser.parse_args()

    mcp = build_server()
    if args.stdio:
        mcp.run("stdio")
        return

    import uvicorn

    app = mcp.streamable_http_app(host=args.host, stateless_http=True, json_response=True)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
