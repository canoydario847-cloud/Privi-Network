"""MCP tools and HTTP API for Privi Guard."""

from __future__ import annotations

import base64
import hmac
import json
from typing import Annotated, Any, Callable, Literal

import anyio
from mcp.server.mcpserver import Context, MCPServer
from mcp_types import ToolAnnotations
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .guard import PACKS, Guard, GuardError, NeedPayment
from .guard_engine import MAX_CHARS, UNIT_CHARS, units_for
from .x402 import X402_VERSION

READ = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
CHECK = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)
BUY = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)
DESC = "Privi Guard: prompt-injection and data-leak check with a signed receipt"
MAX_BATCH_ITEMS = 50


def _cors(data: Any, status: int = 200, headers: dict | None = None) -> JSONResponse:
    h = {"Access-Control-Allow-Origin": "*", "Cache-Control": "no-store",
         "Access-Control-Expose-Headers": "PAYMENT-REQUIRED, PAYMENT-RESPONSE"}
    h.update(headers or {})
    return JSONResponse(data, status_code=status, headers=h)


def register(mcp: MCPServer, guard: Guard, paywall, *, org_from: Callable, result: Callable, unauthorized,
             payments_enabled: bool) -> None:

    def err(e):
        return result({"error": str(e)}, is_error=True)

    @mcp.tool(title="Guard: check text before acting on it or sending it", annotations=CHECK)
    async def guard_check(
        ctx: Context,
        text: Annotated[str, Field(description="The content to check: a web page, email, document or tool result the agent "
                                               "is about to act on (inbound), or what the agent is about to send (outbound)")],
        direction: Annotated[Literal["inbound", "outbound"], Field(description="inbound = untrusted content coming in "
                             "(prompt injection, hidden instructions); outbound = content going out (API keys, card numbers, "
                             "data smuggled in URLs)")] = "inbound",
        source: Annotated[str | None, Field(description="Optional label for the receipt, e.g. the page URL or tool name")] = None,
    ) -> Any:
        """Check content for prompt injection (inbound) or leaked secrets and personal data (outbound) before an
        agent acts on it or sends it. Returns allow / warn / block, the findings, a redacted copy for outbound
        secrets, and an Ed25519-signed receipt anchored on-chain, which proves the check happened. Privi does
        not store the text. Free for 1,000 checks a month with an organization key; otherwise 1 cent per check
        in USDC via x402."""
        if len(text) > MAX_CHARS:
            return err(f"text is over {MAX_CHARS} characters; split it")
        org = org_from(ctx)
        units = units_for(text)
        try:
            paid_by = guard.bill(org["org_id"] if org else None, units)
            return result(guard.check(text, direction, source, org["org_id"] if org else None, paid_by))
        except NeedPayment as e:
            if units > 1:
                return err(f"{e}. Texts over {UNIT_CHARS} characters need an organization key with credits.")

            async def work() -> dict[str, Any]:
                return guard.check(text, direction, source, org["org_id"] if org else None,
                                   "x402" if payments_enabled else "open")
            return await paywall.run("guard_check", DESC, dict(ctx.request_context.meta or {}), work)
        except (GuardError, ValueError) as e:
            return err(e)

    @mcp.tool(title="Guard: check many texts at once", annotations=CHECK)
    def guard_check_many(
        ctx: Context,
        items: Annotated[list[dict[str, Any]], Field(description=f"Up to {MAX_BATCH_ITEMS} items "
                         '{"text": "...", "direction": "inbound"|"outbound", "source": "optional label"}')],
    ) -> Any:
        """Check up to 50 texts in one call (for example every tool result in a step). Each item is billed as its
        own check against your free allowance or credits and gets its own receipt. Needs an organization key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        if not isinstance(items, list) or not 1 <= len(items) <= MAX_BATCH_ITEMS:
            return err(f"send 1-{MAX_BATCH_ITEMS} items")
        clean = []
        for i, it in enumerate(items):
            t = it.get("text") if isinstance(it, dict) else None
            d = (it.get("direction") or "inbound") if isinstance(it, dict) else None
            if not isinstance(t, str) or len(t) > MAX_CHARS or d not in ("inbound", "outbound"):
                return err(f"item {i}: needs text (up to {MAX_CHARS} characters) and direction inbound|outbound")
            clean.append((t, d, it.get("source")))
        try:
            paid_by = guard.bill(org["org_id"], sum(units_for(t) for t, _, _ in clean))
        except NeedPayment as e:
            return err(e)
        out = [guard.check(t, d, s if isinstance(s, str) else None, org["org_id"], paid_by) for t, d, s in clean]
        return result({"results": out, "blocked": sum(r["verdict"] == "block" for r in out),
                       "warned": sum(r["verdict"] == "warn" for r in out), "balance": guard.balance(org["org_id"])})

    @mcp.tool(title="Guard: verify a receipt", annotations=READ)
    def guard_receipt(check_id: Annotated[str, Field(description="gc_... id from a guard_check receipt")]) -> Any:
        """Verify a Privi Guard receipt: the signed body, signature validity and its Merkle proof into the anchored
        transparency log. Free; anyone holding the id can verify it."""
        try:
            return result(guard.receipt(check_id))
        except GuardError as e:
            return err(e)

    @mcp.tool(title="Guard: balance", annotations=READ)
    def guard_balance(ctx: Context) -> Any:
        """Your free checks left this month and your prepaid credits. Needs the organization key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        return result(guard.balance(org["org_id"]))

    @mcp.tool(title="Guard: buy check credits", annotations=BUY)
    async def guard_buy_credits(
        ctx: Context,
        pack: Annotated[Literal["1k", "10k", "100k"], Field(description="1k = 1,000 checks for 7 USDC; 10k = 10,000 for "
                                                                         "50 USDC; 100k = 100,000 for 300 USDC")],
    ) -> Any:
        """Buy prepaid Privi Guard checks in USDC on Base via x402. Credits never expire and are used after the free
        monthly allowance. Needs the organization key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        if pack not in PACKS:
            return err(f"pack must be one of {', '.join(PACKS)}")

        async def work() -> dict[str, Any]:
            return guard.add_credits(org["org_id"], pack)
        return await paywall.run(f"guard_credits_{pack}", f"Privi Guard: {PACKS[pack][0]:,} checks",
                                 dict(ctx.request_context.meta or {}), work)

    @mcp.tool(title="Guard: pricing and how it works", annotations=READ)
    def guard_pricing() -> dict[str, Any]:
        """What Privi Guard checks, what it costs, and how receipts work. Free."""
        return {**guard.pricing(), "tools": ["guard_check", "guard_check_many", "guard_receipt", "guard_balance",
                                            "guard_buy_credits"],
                "http": {"check": f"POST {guard.public_url}/guard/v1/check", "batch": f"POST {guard.public_url}/guard/v1/check_many",
                         "receipt": f"GET {guard.public_url}/guard/v1/receipts/<check_id>"}}


def http_routes(guard: Guard, paywall, ledger, settings) -> list[tuple[str, list[str], Callable]]:
    public = guard.public_url

    def org_of(request: Request) -> dict | None:
        auth = request.headers.get("authorization", "")
        return ledger.org_for_key(auth[7:].strip()) if auth.lower().startswith("bearer ") else None

    def payment_required(error: str) -> JSONResponse:
        body = {"x402Version": X402_VERSION, "error": error,
                "resource": {"url": f"{public}/guard/v1/check", "description": DESC, "mimeType": "application/json"},
                "accepts": [paywall.requirements("guard_check")]}
        enc = base64.b64encode(json.dumps(body, separators=(",", ":")).encode()).decode()
        return _cors(body, 402, {"PAYMENT-REQUIRED": enc})

    async def read_json(request: Request, limit: int) -> dict:
        raw = await request.body()
        if len(raw) > limit:
            raise GuardError("request body too large")
        try:
            data = json.loads(raw or b"{}")
        except ValueError:
            raise GuardError("send a JSON body")
        if not isinstance(data, dict):
            raise GuardError("send a JSON object")
        return data

    async def check(request: Request) -> JSONResponse:
        try:
            data = await read_json(request, MAX_CHARS * 4 + 10_000)
            text, direction, source = data.get("text"), data.get("direction", "inbound"), data.get("source")
            if not isinstance(text, str) or direction not in ("inbound", "outbound"):
                raise GuardError('send {"text": "...", "direction": "inbound"|"outbound"}')
            if len(text) > MAX_CHARS:
                raise GuardError(f"text is over {MAX_CHARS} characters; split it")
        except GuardError as e:
            return _cors({"error": str(e)}, 400)
        org = org_of(request)
        oid = org["org_id"] if org else None
        units = units_for(text)
        try:
            paid_by = guard.bill(oid, units)
            out = await anyio.to_thread.run_sync(lambda: guard.check(text, direction, source if isinstance(source, str) else None, oid, paid_by))
            return _cors(out)
        except NeedPayment as e:
            if units > 1:
                return _cors({"error": f"{e}. Texts over {UNIT_CHARS} characters need an organization key with credits."}, 402)
            if not settings.payments_enabled:
                return _cors(await anyio.to_thread.run_sync(lambda: guard.check(text, direction, None, oid, "open")))
            header = request.headers.get("payment-signature") or request.headers.get("x-payment")
            if not header:
                return payment_required(str(e))
            try:
                payload = json.loads(base64.b64decode(header))
            except (ValueError, TypeError):
                return payment_required("PAYMENT-SIGNATURE must be base64-encoded JSON")
            req = paywall.requirements("guard_check")
            if isinstance(payload, dict):
                payload.setdefault("resource", {"url": f"{public}/guard/v1/check", "description": DESC, "mimeType": "application/json"})
            bad = paywall._matches(payload, req)
            if bad:
                return payment_required(f"Invalid payment: {bad}")
            v = await paywall.facilitator.verify(payload, req)
            if not v.get("isValid"):
                return payment_required(f"Invalid payment: {v.get('invalidReason') or v.get('error') or 'verification failed'}")
            out = await anyio.to_thread.run_sync(lambda: guard.check(text, direction, source if isinstance(source, str) else None, oid, "x402"))
            s = await paywall.facilitator.settle(payload, req)
            if not s.get("success"):
                return payment_required(f"Settlement failed: {s.get('errorReason') or s.get('error') or 'unknown'}")
            enc = base64.b64encode(json.dumps(s, separators=(",", ":")).encode()).decode()
            return _cors(out, 200, {"PAYMENT-RESPONSE": enc})
        except (GuardError, ValueError) as e:
            return _cors({"error": str(e)}, 400)

    async def check_many(request: Request) -> JSONResponse:
        org = org_of(request)
        if not org:
            return _cors({"error": "Authorization: Bearer <organization key> required (free key: ledger_signup)"}, 401)
        try:
            data = await read_json(request, 8_000_000)
            items = data.get("items")
            if not isinstance(items, list) or not 1 <= len(items) <= MAX_BATCH_ITEMS:
                raise GuardError(f"send {{\"items\": [...]}} with 1-{MAX_BATCH_ITEMS} items")
            clean = []
            for i, it in enumerate(items):
                t = it.get("text") if isinstance(it, dict) else None
                d = (it.get("direction") or "inbound") if isinstance(it, dict) else None
                if not isinstance(t, str) or len(t) > MAX_CHARS or d not in ("inbound", "outbound"):
                    raise GuardError(f"item {i}: needs text (up to {MAX_CHARS} characters) and direction inbound|outbound")
                clean.append((t, d, it.get("source") if isinstance(it.get("source"), str) else None))
            paid_by = guard.bill(org["org_id"], sum(units_for(t) for t, _, _ in clean))
        except GuardError as e:
            return _cors({"error": str(e)}, 400)
        except NeedPayment as e:
            return _cors({"error": str(e), "buy": "guard_buy_credits (MCP) with your organization key"}, 402)
        out = await anyio.to_thread.run_sync(lambda: [guard.check(t, d, s, org["org_id"], paid_by) for t, d, s in clean])
        return _cors({"results": out, "blocked": sum(r["verdict"] == "block" for r in out),
                      "warned": sum(r["verdict"] == "warn" for r in out), "balance": guard.balance(org["org_id"])})

    async def receipt(request: Request) -> JSONResponse:
        try:
            return _cors(guard.receipt(request.path_params["check_id"]))
        except GuardError as e:
            return _cors({"error": str(e)}, 404)

    async def pricing(_: Request) -> JSONResponse:
        return _cors(guard.pricing())

    async def stats(_: Request) -> JSONResponse:
        return _cors(guard.stats())

    async def revenue(request: Request) -> JSONResponse:
        tok = request.headers.get("authorization", "")[7:].strip()
        if not settings.admin_key or not tok or not hmac.compare_digest(tok, settings.admin_key):
            return _cors({"error": "unauthorized"}, 401)
        return _cors({**guard.revenue(), **guard.stats()})

    async def options(_: Request) -> Response:
        return Response(status_code=204, headers={"Access-Control-Allow-Origin": "*", "Access-Control-Max-Age": "86400",
                                                  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                                                  "Access-Control-Allow-Headers": "Authorization, Content-Type, PAYMENT-SIGNATURE, X-PAYMENT"})

    return [("/guard/v1/check", ["POST"], check), ("/guard/v1/check", ["OPTIONS"], options),
            ("/guard/v1/check_many", ["POST"], check_many), ("/guard/v1/check_many", ["OPTIONS"], options),
            ("/guard/v1/receipts/{check_id}", ["GET"], receipt), ("/guard/v1/pricing", ["GET"], pricing),
            ("/guard/v1/stats", ["GET"], stats), ("/guard/v1/revenue", ["GET"], revenue)]
