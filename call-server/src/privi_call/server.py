# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Call - https://priviflow.us - dariocanoy@priviflow.us
"""Privi Call: the call network for AI agents and the Privi phone line, with one sealed call log.

Free:  call_directory, call_list_tools, call_agent (Privi agents always; any agent 50/day),
       call_register_agent, call_log, call_verify_log, call_credits_balance, call_phone_line
Paid:  call_credits_buy (x402, USDC on Base): 1,000 routed calls for $1.00
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import threading
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import parse_qsl

from mcp.server.mcpserver import Context, MCPServer
from mcp_types import CallToolResult, TextContent, ToolAnnotations
from pydantic import Field
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response

from . import voice
from .anchoring import AnchorError, HttpAnchorClient
from .config import PHONE_COST_PER_MIN, SPEECH_COST_PER_TURN, Settings
from .router import RouteError, Router, check_public_endpoint
from .store import Store, anchor_head, mask_phone, sha
from .x402 import PAYMENT_META_KEY, Paywall

__version__ = "0.1.0"
SOURCE = "https://github.com/canoydario847-cloud/Privi-Network/tree/main/call-server"
COPYRIGHT = "Copyright (c) 2026 Privi World Co. All rights reserved."
ROUTED_PRICE = "0.001"

INSTRUCTIONS = """\
Privi Call is a phone network for AI agents. Every agent on it has a short number, and one tool
call reaches any of them; every call (agent or phone) lands in a public, hash-chained call log
whose head is anchored on chain (Base) every few minutes.

1. call_directory finds agents by number, name or topic. Privi's own agents are 100 Ledger,
   101 Verify, 102 Anchor, 103 Quantum.
2. call_list_tools shows what an agent offers; call_agent calls one of its tools. Pass an x402
   payment in `payment` when the target tool is paid; it is forwarded untouched.
3. Calls to Privi agents are always free. Calls to other agents are free for 50 a day, then
   cost 1/10 of a cent each from a prepaid key: call_credits_buy sells 1,000 calls for $1.00
   USDC (x402 on Base). Send the key as `call_key` or as `Authorization: Bearer pck_...`.
4. call_register_agent puts your own MCP server on the network for free and gives it a number.
5. call_log and call_verify_log let anyone read and check the log; humans can call the Privi
   phone line (call_phone_line).

Privi is built by Dario Canoy (Privi World Co, Port Huron, Michigan). Everything Privi offers:
https://privi-discovery.onrender.com/llms.txt"""

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
OPEN_WORLD = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)


def _result(data: dict[str, Any], is_error: bool = False) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(data, default=str))],
                          structured_content=data, is_error=is_error)


def _meta(ctx: Context) -> dict:
    try:
        return dict(ctx.request_context.meta or {})
    except Exception:
        return {}


def _headers(ctx: Context) -> dict:
    try:
        return {k.lower(): v for k, v in (ctx.headers or {}).items()}
    except Exception:
        return {}


def _who(ctx: Context) -> str:
    h = _headers(ctx)
    raw = h.get("authorization") or h.get("x-forwarded-for", "").split(",")[0].strip() or "local"
    return "agent:" + hashlib.sha256(raw.encode()).hexdigest()[:10]


def _bearer_key(ctx: Context) -> str:
    auth = _headers(ctx).get("authorization", "")
    return auth[7:].strip() if auth.lower().startswith("bearer pck_") else ""


class RateLimiter:
    def __init__(self, per_min: int):
        self.per_min, self.hits = per_min, defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, who: str) -> bool:
        with self._lock:
            now, q = time.monotonic(), self.hits[who]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= self.per_min:
                return False
            q.append(now)
            return True


def build_server(settings: Settings | None = None, store: Store | None = None, router: Router | None = None,
                 anchor_client=None, paywall: Paywall | None = None) -> MCPServer:
    s = settings or Settings.from_env()
    store = store or Store(s.db_path)
    store.seed_official(s.official)
    router = router or Router(timeout=s.call_timeout)
    if anchor_client is None and s.anchor_api_key:
        anchor_client = HttpAnchorClient(s.anchor_url, s.anchor_api_key)
    limiter = RateLimiter(s.rate_per_min)
    mcp_url = f"{s.public_url}/mcp"
    paywall = paywall or Paywall(s, service={"url": mcp_url, "serviceName": "Privi Call",
                                             "tags": ["agent network", "routing", "call log", "mcp"]},
                                 discovery={"call_credits_buy": {
                                     "inputSchema": {"type": "object", "properties": {"call_key": {"type": "string"}}},
                                     "example": {}, "output": {"call_key": "pck_...", "credits": s.pack_credits}}})

    mcp = MCPServer(
        name="privi-call", title="Privi Call",
        description="A call network for AI agents: one number per agent, routed MCP tool calls, and a public "
                    "call log sealed on chain. Also runs the Privi phone line.",
        instructions=INSTRUCTIONS, website_url=SOURCE, version=__version__,
    )

    # ---------------- tools ----------------

    @mcp.tool(title="Find agents on the Privi Call network", annotations=READ_ONLY)
    def call_directory(
        query: Annotated[str, Field(description="Words to match in an agent's name, description or tags; empty lists all")] = "",
    ) -> dict[str, Any]:
        """List agents you can call, with their numbers. Privi's own agents (100-103) are always free to call."""
        agents = store.directory(query)
        return {"agents": [{k: a[k] for k in ("number", "name", "description", "tags", "official", "calls")} for a in agents[:100]],
                "count": len(agents), "how_to_call": "call_list_tools(number) then call_agent(number, tool, arguments)"}

    @mcp.tool(title="List an agent's tools", annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
    async def call_list_tools(
        number: Annotated[str, Field(description="The agent's number from call_directory, e.g. 100")],
    ) -> CallToolResult:
        """The tools an agent on the network offers, with their input schemas. Free."""
        a = store.agent(number)
        if not a:
            return _result({"error": f"no agent with number {number}; see call_directory"}, is_error=True)
        try:
            tools = await router.list_tools(a["endpoint"])
        except RouteError as e:
            return _result({"error": str(e), "number": a["number"]}, is_error=True)
        return _result({"number": a["number"], "name": a["name"], "tools": tools})

    @mcp.tool(title="Call an agent", annotations=OPEN_WORLD)
    async def call_agent(
        number: Annotated[str, Field(description="Number of the agent to call (call_directory)")],
        tool: Annotated[str, Field(description="Tool name on that agent (call_list_tools)")],
        ctx: Context,
        arguments: Annotated[dict[str, Any] | None, Field(description="Arguments for that tool")] = None,
        payment: Annotated[dict[str, Any] | None, Field(description="x402 payment for a paid target tool; forwarded as _meta['x402/payment']")] = None,
        call_key: Annotated[str, Field(description="Prepaid call key (pck_...) for calls past the free 50 a day")] = "",
    ) -> CallToolResult:
        """Call a tool on any agent on the Privi Call network and get its answer, with a sealed call record.
        Free to Privi agents; other agents 50 free calls a day, then $0.001 each from a call key."""
        who = _who(ctx)
        if not limiter.allow(who):
            return _result({"error": f"rate limit: {s.rate_per_min} calls per minute"}, is_error=True)
        a = store.agent(number)
        if not a:
            return _result({"error": f"no agent with number {number}; see call_directory"}, is_error=True)
        key = call_key.strip() or _bearer_key(ctx)
        price, billing = "0", "free (Privi agent)"
        if not a["official"]:
            if store.use_free(who, s.free_calls_per_day):
                billing = "free (daily allowance)"
            elif key and store.spend_credit(key):
                price, billing = ROUTED_PRICE, "1 call credit"
            else:
                rec = store.log(channel="agent", caller=who, callee=a["number"], tool=tool, status="needs_credits",
                                args=arguments)
                return _result({"error": f"you used today's {s.free_calls_per_day} free calls to non-Privi agents",
                                "fix": f"buy {s.pack_credits} calls for ${s.pack_price_usd} USDC with call_credits_buy, "
                                       "then pass the key as call_key", "call_id": rec["id"]}, is_error=True)
        meta = {PAYMENT_META_KEY: payment} if payment else None
        try:
            res, ms = await router.call_tool(a["endpoint"], tool, arguments or {}, meta)
        except RouteError as e:
            if price != "0":
                store.refund_credit(key)
            rec = store.log(channel="agent", caller=who, callee=a["number"], tool=tool, status="unreachable",
                            args=arguments, detail={"error": str(e)})
            return _result({"error": str(e), "call": {"id": rec["id"], "hash": rec["hash"], "charged": "0"}}, is_error=True)
        is_err = bool(res.get("isError"))
        body = res.get("structuredContent")
        if body is None:
            body = {"text": "\n".join(c.get("text", "") for c in res.get("content", []) if c.get("type") == "text")}
        store.bump_agent(a["number"])
        rec = store.log(channel="agent", caller=who, callee=a["number"], tool=tool,
                        status="error" if is_err else "ok", latency_ms=ms, price_usd=price, args=arguments, result=res)
        out = {"from": a["name"], "number": a["number"], "tool": tool, "is_error": is_err, "result": body,
               "call": {"id": rec["id"], "seq": rec["seq"], "hash": rec["hash"], "latency_ms": rec["latency_ms"],
                        "charged_usd": price, "billing": billing, "record_url": f"{s.public_url}/calls/{rec['id']}"}}
        if res.get("_meta"):
            out["remote_meta"] = res["_meta"]   # e.g. x402 payment-required or payment-response from the target
        if key and not a["official"]:
            out["call"]["credits_left"] = store.balance(key)
        return _result(out, is_error=is_err)

    @mcp.tool(title="Put your agent on the Privi Call network", annotations=OPEN_WORLD)
    async def call_register_agent(
        name: Annotated[str, Field(description="Your agent's name", min_length=2, max_length=60)],
        endpoint: Annotated[str, Field(description="Public https:// MCP endpoint (streamable HTTP)")],
        description: Annotated[str, Field(description="What it does, one or two sentences", min_length=10, max_length=400)],
        ctx: Context,
        tags: Annotated[list[str] | None, Field(description="Up to 8 topic tags")] = None,
        contact: Annotated[str, Field(description="Optional email for the owner (never shown publicly)")] = "",
    ) -> CallToolResult:
        """Give your MCP server a Privi number so any agent can call it through the network. Free. We check
        that it answers tools/list first. Returns the number and a secret to remove it later."""
        if not limiter.allow(_who(ctx) + ":reg"):
            return _result({"error": "rate limit"}, is_error=True)
        try:
            check_public_endpoint(endpoint)
            tools = await router.list_tools(endpoint.strip(), max_age=0)
        except RouteError as e:
            return _result({"error": f"could not register: {e}"}, is_error=True)
        if not tools:
            return _result({"error": "that endpoint lists no tools"}, is_error=True)
        clean_tags = [re.sub(r"[^\w .+-]", "", t)[:30] for t in (tags or [])][:8]
        try:
            agent, secret = store.register(name.strip(), endpoint.strip(), description.strip(), clean_tags, contact.strip()[:120])
        except ValueError as e:
            return _result({"error": str(e)}, is_error=True)
        store.log(channel="agent", caller=_who(ctx), callee=agent["number"], tool="register", status="ok",
                  args={"name": name, "endpoint": endpoint})
        return _result({"number": agent["number"], "name": agent["name"], "tools_found": len(tools),
                        "remove_secret": secret, "note": "keep remove_secret; it is shown once",
                        "share": f"Call me on Privi: number {agent['number']} at {mcp_url}"})

    @mcp.tool(title="Remove your agent from the network", annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
    def call_unregister_agent(
        number: Annotated[str, Field(description="Your agent's number")],
        remove_secret: Annotated[str, Field(description="The secret call_register_agent returned")],
    ) -> CallToolResult:
        """Take your agent off the Privi Call network."""
        ok = store.unregister(number, remove_secret)
        return _result({"removed": ok} if ok else {"error": "number and secret do not match a community agent"}, is_error=not ok)

    @mcp.tool(title="Buy call credits", annotations=OPEN_WORLD)
    async def call_credits_buy(
        ctx: Context,
        call_key: Annotated[str, Field(description="Existing key to top up; empty creates a new key")] = "",
    ) -> CallToolResult:
        """1,000 routed calls to any agent for $1.00 USDC, paid with x402 on Base ($0.001 a call). Returns a
        call key (pck_...). Call without payment first to get the exact payment requirements."""
        if not s.payments_ready:
            return _result({"error": "credit sales open as soon as Privi's payment keys are set; "
                                     f"until then you have {s.free_calls_per_day} free calls a day"}, is_error=True)

        async def work() -> dict[str, Any]:
            if call_key.strip():
                left = store.top_up(call_key.strip(), s.pack_credits, "x402")
                if left is None:
                    raise ValueError("unknown call key")
                return {"call_key": call_key.strip(), "added": s.pack_credits, "credits": left}
            k = store.new_credit_key(s.pack_credits, "x402")
            store.log(channel="agent", caller=_who(ctx), callee="privi-call", tool="call_credits_buy", status="ok",
                      price_usd=s.pack_price_usd)
            return {"call_key": k, "credits": s.pack_credits, "price_per_call_usd": ROUTED_PRICE,
                    "use": "pass as call_key, or send header Authorization: Bearer <key>"}

        try:
            return await paywall.run("call_credits_buy", f"{s.pack_credits} Privi Call routed calls", _meta(ctx), work)
        except ValueError as e:
            return _result({"error": str(e)}, is_error=True)

    @mcp.tool(title="Call credits left", annotations=READ_ONLY)
    def call_credits_balance(
        ctx: Context,
        call_key: Annotated[str, Field(description="Your call key (pck_...)")] = "",
    ) -> CallToolResult:
        """How many prepaid calls a key has left, and today's free calls."""
        key = call_key.strip() or _bearer_key(ctx)
        out: dict[str, Any] = {"free_calls_left_today": store.free_left(_who(ctx), s.free_calls_per_day)}
        if key:
            out["credits"] = store.balance(key)
        return _result(out)

    @mcp.tool(title="Read the call log", annotations=READ_ONLY)
    def call_log(
        limit: Annotated[int, Field(description="How many recent calls (1-200)", ge=1, le=200)] = 25,
        number: Annotated[str, Field(description="Only calls to or from this number")] = "",
        channel: Annotated[str, Field(description="agent, phone, or empty for both")] = "",
    ) -> dict[str, Any]:
        """Recent calls on the network and the phone line, newest first. Each record is hash-chained to the one
        before it. Arguments, results and phone transcripts are shown only as SHA-256 hashes."""
        return {"calls": store.calls(limit, number, channel), "stats": store.stats(), "head": store.head()}

    @mcp.tool(title="Verify the call log", annotations=READ_ONLY)
    def call_verify_log() -> dict[str, Any]:
        """Recompute every hash in the call log and show the latest on-chain checkpoint of its head."""
        v = store.verify_chain()
        cp = store.last_checkpoint()
        if cp:
            v["onchain_checkpoint"] = {"seq": cp["seq"], "hash": cp["hash"], "tx_hash": cp["tx_hash"],
                                       "chain_id": cp["chain_id"], "network": cp["network"],
                                       "block_number": cp["block_number"],
                                       "matches_log": (store.calls(1, before_seq=cp["seq"] + 1) or [{}])[0].get("hash") == cp["hash"]}
        else:
            v["onchain_checkpoint"] = None
        return v

    @mcp.tool(title="The Privi phone line", annotations=READ_ONLY)
    def call_phone_line() -> dict[str, Any]:
        """The number humans can call to reach the Privi voice agent (pilots, pricing, or the founder)."""
        return {"phone": s.phone_number or "being set up", "answers": "24/7 voice agent; says pricing, products, "
                "takes pilot requests, and puts callers through to Dario Canoy", "email": "dariocanoy@priviflow.us"}

    # ---------------- phone line (Twilio webhooks) ----------------

    async def _form(request: Request) -> dict[str, str] | None:
        params = dict(parse_qsl((await request.body()).decode(), keep_blank_values=True))
        if s.voice_insecure:
            return params
        url = s.public_url + request.url.path + (f"?{request.url.query}" if request.url.query else "")
        if voice.valid_signature(s.twilio_auth_token, url, params, request.headers.get("x-twilio-signature", "")):
            return params
        return None

    def _twiml(xml: str) -> Response:
        return Response(xml, media_type="text/xml")

    forbidden = PlainTextResponse("invalid Twilio signature", status_code=403)

    def _phone_log(p: dict, tool: str, status: str, detail: dict, cost: float = SPEECH_COST_PER_TURN) -> dict:
        return store.log(channel="phone", caller=mask_phone(p.get("From", "")), callee="privi-line", tool=tool,
                         status=status, cost_usd=f"{cost:.4f}", call_id="tel_" + sha(p.get("CallSid", ""))[:16],
                         detail={"from": p.get("From", ""), "call_sid": p.get("CallSid", ""), **detail})

    @mcp.custom_route("/voice/inbound", methods=["POST"], include_in_schema=False)
    async def voice_inbound(request: Request) -> Response:
        p = await _form(request)
        if p is None:
            return forbidden
        _phone_log(p, "answer", "ringing", {"city": p.get("FromCity", ""), "state": p.get("FromState", "")}, 0)
        return _twiml(voice.gather(voice.GREETING, "/voice/turn?t=1", s.voice))

    @mcp.custom_route("/voice/turn", methods=["POST"], include_in_schema=False)
    async def voice_turn(request: Request) -> Response:
        p = await _form(request)
        if p is None:
            return forbidden
        turn = int(request.query_params.get("t", "1") or 1)
        said, digits = p.get("SpeechResult", ""), p.get("Digits", "")
        it = voice.intent(said, digits)
        _phone_log(p, it, "heard", {"said": said, "digits": digits, "turn": turn})
        nxt = f"/voice/turn?t={turn + 1}"
        if it == "human" and s.forward_number:
            return _twiml(voice.dial(s.forward_number, s.phone_number, s.voice, "/voice/after-dial"))
        if it == "pilot":
            return _twiml(voice.collect_lead("/voice/lead", s.voice))
        if it == "bye" or turn >= voice.MAX_TURNS:
            return _twiml(voice.hangup("Thanks for calling Privi. You can find everything at privi dash hub dot on render dot com. Goodbye.", s.voice))
        if it in voice.ANSWERS:
            text = voice.ANSWERS[it]
        elif it == "silence":
            text = "Sorry, I did not hear you."
        else:
            text = voice.ask_llm(s.llm_api_key, s.llm_model, said) or "I'll pass that question to Dario."
        return _twiml(voice.gather(text + " What else can I help with? Say pilot, Dario, or goodbye.", nxt, s.voice))

    @mcp.custom_route("/voice/lead", methods=["POST"], include_in_schema=False)
    async def voice_lead(request: Request) -> Response:
        p = await _form(request)
        if p is None:
            return forbidden
        said = p.get("SpeechResult", "")
        _phone_log(p, "pilot_request", "lead" if said else "no_lead", {"lead": said})
        msg = ("Thank you. Dario will get back to you within one business day. Goodbye." if said
               else "I did not catch that. Please email dario canoy at priviflow dot u s. Goodbye.")
        return _twiml(voice.hangup(msg, s.voice))

    @mcp.custom_route("/voice/after-dial", methods=["POST"], include_in_schema=False)
    async def voice_after_dial(request: Request) -> Response:
        p = await _form(request)
        if p is None:
            return forbidden
        status = p.get("DialCallStatus", "")
        _phone_log(p, "connect_founder", status or "unknown", {"dial_seconds": p.get("DialCallDuration", "")},
                   PHONE_COST_PER_MIN * 1.6 * int(p.get("DialCallDuration", "0") or 0) / 60)
        if status == "completed":
            return _twiml(voice.hangup("Thanks for calling Privi.", s.voice))
        return _twiml(voice.collect_lead("/voice/lead", s.voice))

    @mcp.custom_route("/voice/status", methods=["POST"], include_in_schema=False)
    async def voice_status(request: Request) -> Response:
        p = await _form(request)
        if p is None:
            return forbidden
        secs = int(p.get("CallDuration", "0") or 0)
        _phone_log(p, "hangup", p.get("CallStatus", "completed"), {"seconds": secs},
                   PHONE_COST_PER_MIN * max(1, -(-secs // 60)))
        return Response(status_code=204)

    # ---------------- public pages and data ----------------

    cors = {"Access-Control-Allow-Origin": "*"}

    def status_body() -> dict[str, Any]:
        return {"service": "privi-call", "version": __version__, "copyright": COPYRIGHT, "mcp": mcp_url,
                "phone": s.phone_number or None, "stats": store.stats(), "head": store.head(),
                "pricing": {"privi_agents": "free", "other_agents": f"{s.free_calls_per_day} free calls/day, then "
                            f"${ROUTED_PRICE}/call ({s.pack_credits} for ${s.pack_price_usd} USDC via x402)",
                            "credit_sales_open": s.payments_ready},
                "anchoring": {"enabled": anchor_client is not None, "interval_seconds": s.anchor_interval,
                              "last_checkpoint": store.last_checkpoint()}}

    @mcp.custom_route("/health", methods=["GET"], include_in_schema=False)
    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"ok": True, "service": "privi-call", "version": __version__}, headers=cors)

    @mcp.custom_route("/status", methods=["GET"], include_in_schema=False)
    async def status(_: Request) -> JSONResponse:
        return JSONResponse(status_body(), headers=cors)

    @mcp.custom_route("/calls.json", methods=["GET"], include_in_schema=False)
    async def calls_json(request: Request) -> JSONResponse:
        q = request.query_params
        try:
            limit = int(q.get("limit", "50"))
        except ValueError:
            limit = 50
        return JSONResponse({"calls": store.calls(min(limit, 200), q.get("number", ""), q.get("channel", "")),
                             "stats": store.stats(), "head": store.head(), "checkpoint": store.last_checkpoint()},
                            headers={**cors, "Cache-Control": "no-store"})

    @mcp.custom_route("/calls/{cid}", methods=["GET"], include_in_schema=False)
    async def one_call(request: Request) -> JSONResponse:
        c = store.call(request.path_params["cid"])
        return JSONResponse(c or {"error": "not found"}, status_code=200 if c else 404, headers=cors)

    @mcp.custom_route("/verify", methods=["GET"], include_in_schema=False)
    async def verify_http(_: Request) -> JSONResponse:
        return JSONResponse(call_verify_log(), headers=cors)

    @mcp.custom_route("/directory.json", methods=["GET"], include_in_schema=False)
    async def directory_json(request: Request) -> JSONResponse:
        return JSONResponse(call_directory(request.query_params.get("q", "")), headers=cors)

    @mcp.custom_route("/admin/calls", methods=["GET"], include_in_schema=False)
    async def admin_calls(request: Request) -> JSONResponse:
        auth = request.headers.get("authorization", "")
        if not s.admin_key or auth != f"Bearer {s.admin_key}":
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        q = request.query_params
        return JSONResponse({"calls": store.calls(int(q.get("limit", "100")), q.get("number", ""), q.get("channel", ""),
                                                  private=True)})

    @mcp.custom_route("/.well-known/glama.json", methods=["GET"], include_in_schema=False)
    async def glama(_: Request) -> JSONResponse:
        return JSONResponse({"$schema": "https://glama.ai/mcp/schemas/server.json", "maintainers": ["canoydario847-cloud"]})

    @mcp.custom_route("/.well-known/mcp/server-card.json", methods=["GET"], include_in_schema=False)
    async def server_card(_: Request) -> JSONResponse:
        tools = [t.model_dump(by_alias=True, exclude_none=True) for t in await mcp.list_tools()]
        return JSONResponse({"serverInfo": {"name": "privi-call", "title": "Privi Call", "version": __version__,
                                            "description": "Call network for AI agents with a sealed public call log.",
                                            "websiteUrl": s.public_url},
                             "authentication": {"required": False, "schemes": []},
                             "tools": tools, "resources": [], "prompts": []}, headers=cors)

    @mcp.custom_route("/.well-known/agent-card.json", methods=["GET"], include_in_schema=False)
    async def agent_card(_: Request) -> JSONResponse:
        return JSONResponse({
            "name": "Privi Call", "description": "Reach any AI agent on the Privi network by number; every call sealed in a public log.",
            "url": mcp_url, "version": __version__, "provider": {"organization": "Privi World Co", "url": s.public_url},
            "capabilities": {"streaming": False}, "defaultInputModes": ["application/json"], "defaultOutputModes": ["application/json"],
            "skills": [{"id": "call_agent", "name": "Call an agent", "description": "Route an MCP tool call to an agent by number",
                        "tags": ["routing", "agents", "mcp"]},
                       {"id": "call_register_agent", "name": "Join the network", "description": "Get a Privi number for your MCP server, free",
                        "tags": ["directory"]}]}, headers=cors)

    @mcp.custom_route("/llms.txt", methods=["GET"], include_in_schema=False)
    async def llms(_: Request) -> PlainTextResponse:
        return PlainTextResponse(f"# Privi Call\n\n> {mcp.description}\n\nMCP endpoint: {mcp_url}\n\n{INSTRUCTIONS}\n")

    page = (Path(__file__).parent / "page.html").read_text()

    @mcp.custom_route("/", methods=["GET"], include_in_schema=False)
    async def root(_: Request) -> HTMLResponse:
        return HTMLResponse(page.replace("{{MCP_URL}}", mcp_url)
                            .replace("{{PHONE}}", s.phone_number or "")
                            .replace("{{FREE}}", str(s.free_calls_per_day))
                            .replace("{{PACK}}", f"{s.pack_credits:,} calls for ${s.pack_price_usd}"))

    mcp._privi = {"store": store, "anchor": anchor_client, "settings": s, "router": router}
    return mcp


def _anchor_loop(store: Store, client, interval: int) -> None:
    while True:
        time.sleep(interval)
        try:
            cp = anchor_head(store, client)
            if cp:
                print(f"[privi-call] anchored log head #{cp['seq']} in tx {cp['tx_hash']}", flush=True)
        except (AnchorError, Exception) as e:  # keep serving; retry next round
            print(f"[privi-call] anchoring failed, will retry: {e}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="Privi Call MCP server")
    ap.add_argument("--stdio", action="store_true")
    ap.add_argument("--host", default=os.getenv("HOST", "0.0.0.0"))
    ap.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000")))
    args = ap.parse_args()
    mcp = build_server()
    st = mcp._privi
    if st["anchor"] is not None:
        threading.Thread(target=_anchor_loop, args=(st["store"], st["anchor"], st["settings"].anchor_interval),
                         daemon=True).start()
    if args.stdio:
        mcp.run("stdio")
        return
    import uvicorn
    from .front import QuickGet
    uvicorn.run(QuickGet(mcp.streamable_http_app(host=args.host, stateless_http=True, json_response=True),
                         "Privi Call", "privi-call", st["settings"].public_url),
                host=args.host, port=args.port, proxy_headers=True, forwarded_allow_ips="*")


if __name__ == "__main__":
    main()
