# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Call - https://priviflow.us - dariocanoy@priviflow.us
"""Privi Call Gateway: plain HTTPS access to the Privi Call network for every kind of caller.

MCP is one way in. This adds the others, on the same server and the same sealed call log:

- REST + OpenAPI (/v1/..., /openapi.json) for any agent framework that can make an HTTP request
  (OpenAI, Claude, Gemini, LangChain, CrewAI, plain code).
- Tool kits (/kits/<platform>.json) and one webhook (/v1/hook) for AI voice and phone agents
  (Vapi, Retell, ElevenLabs, OpenAI Realtime, Twilio-based bots).
- A console page (/console) for human call-center agents.

Nothing is free. Each request pays one of two ways:
- per call, no sign-up: x402 (USDC on Base) or PRIVI, sent in the PAYMENT-SIGNATURE / X-PAYMENT header;
- prepaid key: `Authorization: Bearer pck_...`, one credit per request (POST /v1/keys sells the packs).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Awaitable, Callable

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response

from .router import RouteError, check_public_endpoint
from .x402 import NO_CHARGE_KEY, PAYMENT_META_KEY, RESPONSE_META_KEY

CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Authorization, Content-Type, PAYMENT-SIGNATURE, X-PAYMENT, X-PRIVI-PAYMENT",
    "Access-Control-Expose-Headers": "PAYMENT-REQUIRED, PAYMENT-RESPONSE, X-PAYMENT-RESPONSE",
    "Cache-Control": "no-store",
}
PLATFORMS = ("openai", "anthropic", "gemini", "vapi", "retell", "elevenlabs")
MAX_BODY = 256 * 1024

# The three functions every kit exposes. Names are the same on every platform.
FUNCTIONS: list[dict[str, Any]] = [
    {"name": "privi_find_agents",
     "description": "Find services on the Privi network (verification, audit ledger, on-chain anchoring, "
                    "post-quantum tools, and community agents). Returns each one's number.",
     "parameters": {"type": "object", "properties": {
         "query": {"type": "string", "description": "Words to match, e.g. 'verify'. Empty lists everything."}}}},
    {"name": "privi_list_tools",
     "description": "List the tools one Privi agent offers, with the inputs each tool takes.",
     "parameters": {"type": "object", "required": ["number"], "properties": {
         "number": {"type": "string", "description": "Agent number from privi_find_agents, e.g. '100'."}}}},
    {"name": "privi_call",
     "description": "Call one tool on a Privi agent and get its answer with a sealed, on-chain-anchored call record.",
     "parameters": {"type": "object", "required": ["number", "tool"], "properties": {
         "number": {"type": "string", "description": "Agent number, e.g. '100'."},
         "tool": {"type": "string", "description": "Tool name from privi_list_tools."},
         "arguments": {"type": "object", "description": "Inputs for that tool.", "additionalProperties": True}}}},
]


def _b64_json(raw: str) -> Any:
    raw = raw.strip()
    try:
        return json.loads(base64.b64decode(raw + "=" * (-len(raw) % 4)))
    except Exception:
        try:
            return json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
        except Exception:
            return json.loads(raw)   # some clients send the JSON as is


def _enc(data: Any) -> str:
    return base64.b64encode(json.dumps(data, separators=(",", ":"), default=str).encode()).decode()


def register_gateway(mcp, s, store, router, paywall, limiter, version: str) -> None:
    base = s.public_url.rstrip("/")
    key_price = float(s.pack_price_usd) / max(1, s.pack_credits)
    s.per_call_prices["agent_access_signup"] = "1.00"  # one-time USDC activation; not a recurring charge

    def per_call_price() -> str:
        return os.getenv("CALL_PRICE_PER_CALL", "0.01")

    def who(request: Request) -> str:
        raw = (request.headers.get("authorization") or request.headers.get("x-forwarded-for", "").split(",")[0].strip()
               or (request.client.host if request.client else "local"))
        return "agent:" + hashlib.sha256(raw.encode()).hexdigest()[:10]

    def bearer(request: Request) -> str:
        auth = request.headers.get("authorization", "")
        return auth[7:].strip() if auth.lower().startswith("bearer pck_") else ""

    def out(data: Any, status: int = 200, headers: dict | None = None) -> JSONResponse:
        return JSONResponse(data, status_code=status, headers={**CORS, **(headers or {})})

    async def body_json(request: Request) -> dict:
        raw = await request.body()
        if len(raw) > MAX_BODY:
            raise ValueError("request body too large")
        if not raw.strip():
            return {}
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("send a JSON object")
        return data

    def payment_meta(request: Request, body: dict | None = None) -> dict:
        meta: dict[str, Any] = {}
        try:
            h = request.headers.get("payment-signature") or request.headers.get("x-payment")
            if h:
                meta[PAYMENT_META_KEY] = _b64_json(h)
            elif isinstance((body or {}).get("payment"), dict):
                meta[PAYMENT_META_KEY] = body["payment"]
            p = request.headers.get("x-privi-payment")
            if p:
                meta["privi/payment"] = _b64_json(p)
            elif isinstance((body or {}).get("privi_payment"), dict):
                meta["privi/payment"] = body["privi_payment"]
        except Exception:
            raise ValueError("payment header is not base64 JSON")
        return meta

    def how_to_pay() -> dict:
        return {"per_call": f"${per_call_price()} USDC on Base via x402 (or PRIVI): repeat the request with the "
                            "signed payment in the PAYMENT-SIGNATURE header",
                "prepaid_key": f"POST {base}/v1/keys buys {s.pack_credits} requests for ${s.pack_price_usd} USDC; "
                               "then send Authorization: Bearer pck_...",
                "docs": f"{base}/openapi.json"}

    async def charge(request: Request, name: str, description: str, meta: dict,
                     work: Callable[[], Awaitable[dict[str, Any]]], use_key: bool = True) -> Response:
        """Run `work` once it is paid for: one credit from a prepaid key, or one x402/PRIVI payment."""
        if not limiter.allow(who(request)):
            return out({"error": f"rate limit: {s.rate_per_min} requests per minute"}, 429)
        key = bearer(request) if use_key else ""
        if key:
            if not store.spend_credit(key):
                known = store.balance(key) is not None
                return out({"error": "this key has no credits left" if known else "unknown key",
                            "how_to_pay": how_to_pay()}, 402 if known else 401)
            try:
                data = await work()
            except Exception:
                store.refund_credit(key)
                raise
            failed = bool(data.pop(NO_CHARGE_KEY, False))
            if failed:
                store.refund_credit(key)
            data["billing"] = {"paid_with": "prepaid key", "charged_credits": 0 if failed else 1,
                               "credits_left": store.balance(key)}
            return out(data, 502 if failed and data.get("unreachable") else 400 if failed else 200)

        s.per_call_prices.setdefault(name, per_call_price())
        res = await paywall.run(name, description, meta, work)
        data = res.structured_content if isinstance(res.structured_content, dict) else {}
        if res.is_error and "accepts" in data:
            data["how_to_pay"] = how_to_pay()
            return out(data, 402, {"PAYMENT-REQUIRED": _enc(data)})
        rmeta = dict(getattr(res, "meta", None) or {})
        headers = {}
        if rmeta.get(RESPONSE_META_KEY):
            headers = {"PAYMENT-RESPONSE": _enc(rmeta[RESPONSE_META_KEY]),
                       "X-PAYMENT-RESPONSE": _enc(rmeta[RESPONSE_META_KEY])}
            data["billing"] = {"paid_with": "x402", "charged_usd": s.per_call_prices.get(name)}
        elif rmeta.get("privi/receipt"):
            data["billing"] = {"paid_with": "PRIVI", "receipt": rmeta["privi/receipt"]}
        return out(data, (502 if data.get("unreachable") else 400) if res.is_error else 200, headers)

    # ---------------- the three things a caller can do ----------------

    def do_find(query: str) -> dict[str, Any]:
        agents = store.directory(query or "")
        return {"agents": [{k: a[k] for k in ("number", "name", "description", "tags", "official")} for a in agents[:100]],
                "count": len(agents)}

    async def do_tools(number: str) -> dict[str, Any]:
        a = store.agent(str(number))
        if not a:
            return {"error": f"no agent with number {number}; see GET {base}/v1/agents", NO_CHARGE_KEY: True}
        try:
            tools = await router.list_tools(a["endpoint"])
        except RouteError as e:
            return {"error": str(e), "number": a["number"], "unreachable": True, NO_CHARGE_KEY: True}
        return {"number": a["number"], "name": a["name"], "tools": tools}

    async def do_call(caller: str, number: str, tool: str, arguments: dict | None, forward_payment: dict | None,
                      via: str) -> dict[str, Any]:
        a = store.agent(str(number))
        if not a:
            return {"error": f"no agent with number {number}; see GET {base}/v1/agents", NO_CHARGE_KEY: True}
        if not tool:
            return {"error": "tool is required; see the agent's tools", NO_CHARGE_KEY: True}
        meta = {PAYMENT_META_KEY: forward_payment} if forward_payment else None
        try:
            res, ms = await router.call_tool(a["endpoint"], tool, arguments or {}, meta)
        except RouteError as e:
            rec = store.log(channel="agent", caller=caller, callee=a["number"], tool=tool, status="unreachable",
                            args=arguments, detail={"error": str(e), "via": via})
            return {"error": str(e), "unreachable": True, "call": {"id": rec["id"], "hash": rec["hash"]},
                    NO_CHARGE_KEY: True}
        is_err = bool(res.get("isError"))
        result = res.get("structuredContent")
        if result is None:
            result = {"text": "\n".join(c.get("text", "") for c in res.get("content", []) if c.get("type") == "text")}
        store.bump_agent(a["number"])
        rec = store.log(channel="agent", caller=caller, callee=a["number"], tool=tool,
                        status="error" if is_err else "ok", latency_ms=ms, args=arguments, result=res,
                        detail={"via": via})
        data = {"from": a["name"], "number": a["number"], "tool": tool, "is_error": is_err, "result": result,
                "call": {"id": rec["id"], "seq": rec["seq"], "hash": rec["hash"], "latency_ms": rec["latency_ms"],
                         "record_url": f"{base}/calls/{rec['id']}"}}
        if res.get("_meta"):
            data["remote_meta"] = res["_meta"]   # e.g. the target tool's own x402 price
        return data

    async def guarded(request: Request, handler: Callable[[], Awaitable[Response]]) -> Response:
        if request.method == "OPTIONS":
            return Response(status_code=204, headers=CORS)
        try:
            return await handler()
        except (ValueError, json.JSONDecodeError) as e:
            return out({"error": str(e) or "bad request"}, 400)

    # ---------------- REST ----------------

    @mcp.custom_route("/v1/agents", methods=["GET", "OPTIONS"], include_in_schema=False)
    async def v1_agents(request: Request) -> Response:
        async def h() -> Response:
            q = request.query_params.get("q", "")

            async def work() -> dict[str, Any]:
                return do_find(q)
            return await charge(request, "rest_find_agents", "Privi Call: find agents", payment_meta(request), work)
        return await guarded(request, h)

    @mcp.custom_route("/v1/agents/{number}/tools", methods=["GET", "OPTIONS"], include_in_schema=False)
    async def v1_tools(request: Request) -> Response:
        async def h() -> Response:
            return await charge(request, "rest_list_tools", "Privi Call: list an agent's tools", payment_meta(request),
                                lambda: do_tools(request.path_params["number"]))
        return await guarded(request, h)

    async def _call(request: Request, number: str, tool: str, arguments: Any, body: dict) -> Response:
        if arguments is not None and not isinstance(arguments, dict):
            raise ValueError("arguments must be a JSON object")
        fwd = body.get("target_payment") if isinstance(body.get("target_payment"), dict) else None
        return await charge(request, "rest_call", f"Privi Call: call agent {number}", payment_meta(request, body),
                            lambda: do_call(who(request), number, tool, arguments, fwd, "rest"))

    @mcp.custom_route("/v1/call", methods=["POST", "OPTIONS"], include_in_schema=False)
    async def v1_call(request: Request) -> Response:
        async def h() -> Response:
            b = await body_json(request)
            return await _call(request, str(b.get("number", "")), str(b.get("tool", "")), b.get("arguments"), b)
        return await guarded(request, h)

    @mcp.custom_route("/v1/call/{number}/{tool}", methods=["POST", "OPTIONS"], include_in_schema=False)
    async def v1_call_flat(request: Request) -> Response:
        """The request body is the tool's arguments, for platforms that can only send flat fields."""
        async def h() -> Response:
            b = await body_json(request)
            return await _call(request, request.path_params["number"], request.path_params["tool"], b, {})
        return await guarded(request, h)

    @mcp.custom_route("/v1/keys", methods=["POST", "OPTIONS"], include_in_schema=False)
    async def v1_keys(request: Request) -> Response:
        async def h() -> Response:
            b = await body_json(request)
            top_up = str(b.get("key", "")).strip() or bearer(request)
            if not s.payments_ready:
                return out({"error": "key sales open as soon as Privi's payment keys are set"}, 503)

            async def work() -> dict[str, Any]:
                if top_up:
                    left = store.top_up(top_up, s.pack_credits, "x402-rest")
                    if left is None:
                        return {"error": "unknown key", NO_CHARGE_KEY: True}
                    return {"key": top_up, "added": s.pack_credits, "credits": left}
                k = store.new_credit_key(s.pack_credits, "x402-rest")
                store.log(channel="agent", caller=who(request), callee="privi-call", tool="call_credits_buy",
                          status="ok", price_usd=s.pack_price_usd, detail={"via": "rest"})
                return {"key": k, "credits": s.pack_credits, "price_per_request_usd": f"{key_price:.4f}",
                        "use": "send header Authorization: Bearer <key> on every request; keep it secret"}
            return await charge(request, "call_credits_buy", f"{s.pack_credits} Privi Call requests",
                                payment_meta(request, b), work, use_key=False)
        return await guarded(request, h)

    @mcp.custom_route("/v1/balance", methods=["GET", "OPTIONS"], include_in_schema=False)
    async def v1_balance(request: Request) -> Response:
        async def h() -> Response:
            key = bearer(request)
            bal = store.balance(key) if key else None
            if bal is None:
                return out({"error": "send Authorization: Bearer pck_...", "how_to_pay": how_to_pay()}, 401)
            return out({"credits": bal})
        return await guarded(request, h)

    # ---------------- Agent Access: $1 signup, AI-agent-only REST door ----------------

    @mcp.custom_route("/v1/agent-access", methods=["GET", "OPTIONS"], include_in_schema=False)
    async def agent_access_offer(request: Request) -> Response:
        if request.method == "OPTIONS":
            return Response(status_code=204, headers=CORS)
        return out({
            "name": "Privi Agent Access",
            "eligible": "AI agents exposing a reachable public HTTPS MCP tools/list endpoint",
            "price": {"amount": "1.00", "currency": "USDC", "network": "Base", "frequency": "once"},
            "included_requests": s.pack_credits,
            "access": "One registered AI agent and a reusable secret key; top up call credits when exhausted",
            "extra_costs": "Third-party agents' paid tools may charge separately.",
            "signup": f"{base}/v1/agent-access/signup",
            "status": f"{base}/v1/agent-access/status",
            "agent_only_call": f"{base}/v1/agent-access/call",
            "payment": "x402 v2; signed PAYMENT-SIGNATURE header",
            "verification_note": "A working MCP endpoint is required; no claim of cryptographic AI-personhood proof."
        })

    def signup_required(message: str) -> Response:
        pending = paywall.payment_required("agent_access_signup", "One Privi AI agent registration", message)
        data = dict(pending.structured_content or {})
        return out(data, 402, {"PAYMENT-REQUIRED": _enc(data)})

    @mcp.custom_route("/v1/agent-access/signup", methods=["POST", "OPTIONS"], include_in_schema=False)
    async def agent_access_signup(request: Request) -> Response:
        async def h() -> Response:
            if not limiter.allow(who(request) + ":agent-signup"):
                return out({"error": "signup rate limit exceeded"}, 429)
            body = await body_json(request)
            name = str(body.get("name", "")).strip()
            endpoint = str(body.get("endpoint", "")).strip()
            description = str(body.get("description", "")).strip()
            contact = str(body.get("contact", "")).strip()
            raw_tags = body.get("tags", [])
            if not 2 <= len(name) <= 60 or not 10 <= len(description) <= 400:
                return out({"error": "name must be 2-60 characters and description 10-400 characters"}, 400)
            if not isinstance(raw_tags, list) or len(raw_tags) > 8 or any(not isinstance(x, str) for x in raw_tags):
                return out({"error": "tags must be a list of up to 8 strings"}, 400)
            if len(contact) > 120 or len(endpoint) > 2048:
                return out({"error": "contact or endpoint is too long"}, 400)
            try:
                check_public_endpoint(endpoint)  # reject local hosts and SSRF addresses
            except RouteError as exc:
                return out({"error": str(exc)}, 400)
            if store.agent_by_endpoint(endpoint):
                return out({"error": "this endpoint is already on the Privi network"}, 409)
            # Require a *working* MCP agent before asking anyone to pay.
            try:
                found_tools = await router.list_tools(endpoint, max_age=0)
            except RouteError as exc:
                return out({"error": f"AI agent endpoint failed MCP discovery: {exc}"}, 400)
            if not found_tools:
                return out({"error": "an AI agent must expose at least one MCP tool"}, 400)
            if not s.payments_ready:
                return out({"error": "secure USDC signup is unavailable until payment settlement is configured"}, 503)

            meta = payment_meta(request, body)
            payment = meta.get(PAYMENT_META_KEY)
            if payment is None:
                return signup_required("Sign the $1 USDC payment and retry this registration.")
            req = paywall.requirements("agent_access_signup")
            bad = paywall._matches(payment, req)
            if bad:
                return signup_required("Invalid payment: " + bad)
            verified = await paywall.facilitator.verify(payment, req)
            if not verified.get("isValid"):
                return signup_required("Payment could not be verified: " +
                                       str(verified.get("invalidReason") or verified.get("error") or "invalid"))
            # IMPORTANT: Unlike paywall.run(), we settle BEFORE issuing access credentials.
            settled = await paywall.facilitator.settle(payment, req)
            if not settled.get("success"):
                return out({"error": "USDC settlement did not succeed; no account or key issued"}, 502)
            tx = str(settled.get("transaction") or settled.get("txHash") or "").strip()
            if not tx:
                return out({"error": "settlement returned no transaction reference; contact support with receipt"}, 502)
            fingerprint = hashlib.sha256(json.dumps(payment, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            clean_tags = [x.strip()[:30] for x in raw_tags]
            try:
                agent, key = store.enroll_paid_agent(
                    name, endpoint, description, clean_tags, contact, fingerprint, tx,
                    credits=s.pack_credits)
            except ValueError as exc:
                return out({"error": str(exc), "support": "dariocanoy@priviflow.us"}, 409)
            except Exception:
                # Payment might have succeeded; do not lie or issue a second bill.
                return out({"error": "settled payment could not be provisioned; contact support with receipt"}, 503)
            store.log(channel="agent", caller="paid-registration", callee=agent["number"],
                      tool="agent_access_signup", status="ok", price_usd="1.00",
                      args={"name": name, "endpoint": endpoint},
                      detail={"payment_tx_sha256": hashlib.sha256(tx.encode()).hexdigest()})
            return out({
                "status": "active", "agent_number": agent["number"], "name": agent["name"],
                "api_key": key, "credits": s.pack_credits, "paid_usdc": "1.00",
                "key_note": "Shown once. Store as a secret; never put it in a public repository.",
                "call_url": f"{base}/v1/agent-access/call",
                "balance_url": f"{base}/v1/agent-access/status",
                "authorization": "Authorization: Bearer <api_key>",
                "top_up_url": f"{base}/v1/keys",
                "billing": "One-time signup. Included requests are finite; paid target-tool fees are separate."
            }, 201, {"PAYMENT-RESPONSE": _enc(settled)})
        return await guarded(request, h)

    @mcp.custom_route("/v1/agent-access/status", methods=["GET", "OPTIONS"], include_in_schema=False)
    async def agent_access_status(request: Request) -> Response:
        if request.method == "OPTIONS":
            return Response(status_code=204, headers=CORS)
        key = bearer(request)
        member = store.paid_agent_for_key(key) if key else None
        if not member:
            return out({"error": "registered AI-agent key required; sign up for $1 at /v1/agent-access/signup"}, 401)
        return out(member)

    @mcp.custom_route("/v1/agent-access/call", methods=["POST", "OPTIONS"], include_in_schema=False)
    async def agent_access_call(request: Request) -> Response:
        async def h() -> Response:
            key = bearer(request)
            member = store.paid_agent_for_key(key) if key else None
            if not member:
                return out({"error": "this route is exclusively for registered AI agents"}, 401)
            b = await body_json(request)
            args = b.get("arguments", {})
            if not isinstance(args, dict):
                return out({"error": "arguments must be a JSON object"}, 400)
            number, tool = str(b.get("number", "")).strip(), str(b.get("tool", "")).strip()
            if not number or not tool:
                return out({"error": "number and tool are required"}, 400)
            fwd = b.get("target_payment") if isinstance(b.get("target_payment"), dict) else None
            return await charge(request, "rest_call", "Privi registered-agent routed call", {},
                                lambda: do_call("registered:" + member["number"], number, tool,
                                                args, fwd, "agent-access"))
        return await guarded(request, h)

    # ---------------- one webhook for voice / phone agent platforms ----------------

    async def run_function(caller: str, name: str, args: dict, via: str) -> dict[str, Any]:
        if name == "privi_find_agents":
            return do_find(str(args.get("query", "")))
        if name == "privi_list_tools":
            return await do_tools(str(args.get("number", "")))
        if name == "privi_call":
            a = args.get("arguments")
            if isinstance(a, str):
                try:
                    a = json.loads(a) if a.strip() else {}
                except ValueError:
                    return {"error": "arguments must be a JSON object", NO_CHARGE_KEY: True}
            return await do_call(caller, str(args.get("number", "")), str(args.get("tool", "")),
                                 a if isinstance(a, dict) else {}, None, via)
        return {"error": f"unknown function {name}; use privi_find_agents, privi_list_tools or privi_call",
                NO_CHARGE_KEY: True}

    @mcp.custom_route("/v1/hook", methods=["POST", "OPTIONS"], include_in_schema=False)
    async def v1_hook(request: Request) -> Response:
        """Accepts the tool-call shapes voice platforms send. Needs a prepaid key (they cannot sign x402)."""
        async def h() -> Response:
            b = await body_json(request)
            if not bearer(request):
                return out({"error": "voice webhooks need a prepaid key: Authorization: Bearer pck_...",
                            "how_to_pay": how_to_pay()}, 401)
            caller = who(request)
            msg = b.get("message") if isinstance(b.get("message"), dict) else None
            calls = (msg or {}).get("toolCallList") or (msg or {}).get("toolCalls")
            if isinstance(calls, list):            # Vapi: several tool calls, answered as {results:[...]}
                results = []
                for c in calls[:5]:
                    fn = c.get("function") or {}
                    args = fn.get("arguments") or {}
                    if isinstance(args, str):
                        args = json.loads(args or "{}")
                    r = await charge(request, "rest_call", "Privi Call",
                                     {}, lambda fn=fn, args=args: run_function(caller, str(fn.get("name", "")), args, "vapi"))
                    results.append({"toolCallId": c.get("id"), "result": r.body.decode()})
                return out({"results": results})
            if isinstance(b.get("args"), dict) and b.get("name"):     # Retell custom function
                name, args, via = str(b["name"]), b["args"], "retell"
            else:                                                     # flat: ElevenLabs, OpenAI Realtime relays, anything
                name = str(b.get("function") or b.get("name") or request.query_params.get("function") or "privi_call")
                args, via = {k: v for k, v in b.items() if k not in ("function", "name")}, "voice"
            return await charge(request, "rest_call", "Privi Call", {}, lambda: run_function(caller, name, args, via))
        return await guarded(request, h)

    # ---------------- discovery: OpenAPI and ready-made tool kits ----------------

    def openapi() -> dict[str, Any]:
        pay402 = {"description": "Payment required. The body and the PAYMENT-REQUIRED header carry the x402 terms."}
        err = {"description": "Error", "content": {"application/json": {"schema": {"type": "object"}}}}
        ok = {"description": "OK", "content": {"application/json": {"schema": {"type": "object"}}}}
        sec = [{"prepaidKey": []}, {"x402": []}]
        return {
            "openapi": "3.1.0",
            "info": {"title": "Privi Call Gateway", "version": version,
                     "description": "Reach every service on the Privi network over plain HTTPS. Every request is paid: "
                                    f"${per_call_price()} USDC per request with x402 (no sign-up), or one credit from a "
                                    f"prepaid key ({s.pack_credits} requests for ${s.pack_price_usd} USDC). Every call is "
                                    "written to a public, hash-chained call log anchored on Base.",
                     "contact": {"name": "Privi World Co", "email": "dariocanoy@priviflow.us", "url": base}},
            "servers": [{"url": base}],
            "components": {"securitySchemes": {
                "prepaidKey": {"type": "http", "scheme": "bearer", "description": "pck_... key from POST /v1/keys"},
                "x402": {"type": "apiKey", "in": "header", "name": "PAYMENT-SIGNATURE",
                         "description": "Base64 x402 v2 payment payload (USDC on Base). X-PAYMENT is accepted too."}}},
            "paths": {
                "/v1/agents": {"get": {"operationId": "privi_find_agents", "summary": FUNCTIONS[0]["description"],
                                       "security": sec, "parameters": [{"name": "q", "in": "query", "schema": {"type": "string"}}],
                                       "responses": {"200": ok, "402": pay402}}},
                "/v1/agents/{number}/tools": {"get": {"operationId": "privi_list_tools", "summary": FUNCTIONS[1]["description"],
                                                      "security": sec, "parameters": [{"name": "number", "in": "path", "required": True,
                                                                                       "schema": {"type": "string"}}],
                                                      "responses": {"200": ok, "402": pay402, "400": err}}},
                "/v1/call": {"post": {"operationId": "privi_call", "summary": FUNCTIONS[2]["description"], "security": sec,
                                      "requestBody": {"required": True, "content": {"application/json": {
                                          "schema": FUNCTIONS[2]["parameters"]}}},
                                      "responses": {"200": ok, "402": pay402, "400": err, "502": err}}},
                "/v1/call/{number}/{tool}": {"post": {"operationId": "privi_call_flat", "security": sec,
                                                      "summary": "Same as privi_call; the JSON body is the tool's arguments.",
                                                      "parameters": [{"name": n, "in": "path", "required": True, "schema": {"type": "string"}}
                                                                     for n in ("number", "tool")],
                                                      "requestBody": {"content": {"application/json": {"schema": {"type": "object"}}}},
                                                      "responses": {"200": ok, "402": pay402, "400": err, "502": err}}},
                "/v1/keys": {"post": {"operationId": "privi_buy_key", "security": [{"x402": []}],
                                      "summary": f"Buy a prepaid key ({s.pack_credits} requests) or top one up, paid with x402.",
                                      "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {
                                          "key": {"type": "string", "description": "Existing key to top up"}}}}}},
                                      "responses": {"200": ok, "402": pay402}}},
                "/v1/balance": {"get": {"operationId": "privi_key_balance", "summary": "Credits left on a prepaid key.",
                                        "security": [{"prepaidKey": []}], "responses": {"200": ok, "401": err}}},
            },
        }

    def kit(platform: str) -> dict[str, Any]:
        hook, auth = f"{base}/v1/hook", {"Authorization": "Bearer YOUR_PRIVI_KEY"}
        common = {"platform": platform, "provider": "Privi World Co", "webhook": hook, "headers": auth,
                  "get_a_key": f"POST {base}/v1/keys (x402, {s.pack_credits} requests for ${s.pack_price_usd} USDC)",
                  "openapi": f"{base}/openapi.json",
                  "system_prompt_addition": "You can use Privi services. Call privi_find_agents to see what exists, "
                                            "privi_list_tools for an agent's tools, then privi_call. Tell the caller the "
                                            "call record id when a result matters."}
        if platform == "openai":
            return {**common,
                    "tools_responses_and_realtime": [{"type": "function", **f} for f in FUNCTIONS],
                    "tools_chat_completions": [{"type": "function", "function": f} for f in FUNCTIONS],
                    "run": "When the model calls a function, POST {\"function\": name, ...arguments} to the webhook."}
        if platform == "anthropic":
            return {**common, "tools": [{"name": f["name"], "description": f["description"],
                                         "input_schema": f["parameters"]} for f in FUNCTIONS],
                    "mcp": {"type": "url", "url": f"{base}/mcp", "name": "privi-call"},
                    "run": "POST {\"function\": name, ...input} to the webhook, or connect the MCP server directly."}
        if platform == "gemini":
            return {**common, "tools": [{"functionDeclarations": [
                {"name": f["name"], "description": f["description"], "parameters": f["parameters"]} for f in FUNCTIONS]}],
                "run": "POST {\"function\": name, ...args} to the webhook."}
        if platform == "vapi":
            return {**common, "tools": [{"type": "function", "function": f,
                                         "server": {"url": hook, "headers": auth}} for f in FUNCTIONS]}
        if platform == "retell":
            return {**common, "custom_functions": [{"name": f["name"], "description": f["description"], "url": hook,
                                                    "method": "POST", "headers": auth, "parameters": f["parameters"],
                                                    "speak_during_execution": True} for f in FUNCTIONS]}
        return {**common, "webhook_tools": [{"name": f["name"], "description": f["description"], "method": "POST",
                                             "url": f"{hook}?function={f['name']}", "headers": auth,
                                             "body_schema": f["parameters"]} for f in FUNCTIONS]}

    @mcp.custom_route("/openapi.json", methods=["GET"], include_in_schema=False)
    async def openapi_json(_: Request) -> JSONResponse:
        return JSONResponse(openapi(), headers={"Access-Control-Allow-Origin": "*"})

    @mcp.custom_route("/kits", methods=["GET"], include_in_schema=False)
    async def kits_index(_: Request) -> JSONResponse:
        return JSONResponse({"kits": {p: f"{base}/kits/{p}.json" for p in PLATFORMS}, "openapi": f"{base}/openapi.json",
                             "mcp": f"{base}/mcp", "console_for_people": f"{base}/console", "pricing": how_to_pay()},
                            headers={"Access-Control-Allow-Origin": "*"})

    @mcp.custom_route("/kits/{name}", methods=["GET"], include_in_schema=False)
    async def kit_json(request: Request) -> JSONResponse:
        p = request.path_params["name"].removesuffix(".json").lower()
        if p not in PLATFORMS:
            return JSONResponse({"error": "unknown platform", "kits": list(PLATFORMS)}, status_code=404)
        return JSONResponse(kit(p), headers={"Access-Control-Allow-Origin": "*"})

    console = (Path(__file__).parent / "console.html").read_text()

    @mcp.custom_route("/console", methods=["GET"], include_in_schema=False)
    async def console_page(_: Request) -> HTMLResponse:
        return HTMLResponse(console.replace("{{PACK}}", f"{s.pack_credits:,} requests for ${s.pack_price_usd} USDC"))
