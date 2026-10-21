"""MCP tools for Privi Live: approvals, kill switch, trust feed, gateway and rooms."""

from __future__ import annotations

import json
import time
from typing import Annotated, Any, Callable

import anyio
from mcp.server.mcpserver import Context, MCPServer
from mcp_types import CallToolResult, ToolAnnotations
from pydantic import Field

from .gateway import FREE_MONTHLY as GW_FREE, GatewayError, Gateways
from .live import FREE_DELAY_S, LiveError, LiveService, make_filter
from .mandate import MandateError
from .rooms import FREE_MONTHLY as ROOM_FREE, RoomError, Rooms
from .store import check_id

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
DESTRUCTIVE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False)


def register(mcp: MCPServer, live: LiveService, gateways: Gateways, rooms: Rooms, *, org_from: Callable,
             result: Callable, unauthorized: CallToolResult, over_limit: Callable) -> None:
    base = live.public_url
    ws_base = base.replace("https://", "wss://").replace("http://", "ws://")

    # ---------------- overview ----------------

    @mcp.tool(title="Privi Live: how to connect", annotations=READ_ONLY)
    def live_info() -> dict[str, Any]:
        """Real-time Privi: WebSocket and server-sent-event streams (trust changes, your own audit tail, approvals), a
        kill switch, human approvals, a metered MCP gateway and paid agent-to-agent rooms. Returns the endpoints,
        channels, frames and what each plan gets. Free; no key needed."""
        return {
            "streams": {
                "websocket": f"{ws_base}/live/ws",
                "sse": f"{base}/live/events",
                "poll": f"{base}/live/trust/recent",
                "dashboard": f"{base}/live",
                "websocket_protocol": [
                    '{"type":"auth","key":"<org api key>"}  (optional; unlocks the org channel and real-time trust)',
                    '{"type":"subscribe","channels":["trust","org"],"replay":20,"filter":{"address":"0x..","types":["passport."]}}',
                    '{"type":"kill","stream_id":"<agent>|*","reason":"..."}  /  {"type":"resume","stream_id":"..."}',
                    '{"type":"ping"}',
                    'server frames: {"type":"event","event":"<name>","id":N,"channel":"..","at":"..","data":{..}}, plus '
                    '"heartbeat" every 15s when idle'],
                "api_keys": "never put keys in URLs: use the Authorization: Bearer header (SSE/HTTP) or the first WebSocket frame",
            },
            "channels": {
                "trust": "public: passport.issued / revoked / score_changed / state_changed, kya.bound / unbound, "
                         "mandate.activated / revoked, log.anchored",
                "org": "private: entry.recorded (live tail of your audit log), approval.*, agent.killed / resumed, room.*",
                "mandate:<id>": "public: that mandate's activation and revocation"},
            "plans": {"free": f"trust feed delayed {int(FREE_DELAY_S)}s; {GW_FREE} gateway calls and {ROOM_FREE} room messages per month; 2 gateways; 5 streams",
                      "pro": "trust feed in real time; unlimited gateway calls and room messages; 50 gateways; 100 streams "
                             "(ledger_upgrade_pro)"},
            "gateway": {"http": f"{base}/gw/<id>/mcp", "websocket": f"{ws_base}/gw/<id>/ws", "create": "gateway_create"},
            "rooms": {"websocket": f"{ws_base}/rooms/<id>/ws", "open": "room_open"},
            "approvals": "approval_policy_set + mandate_spend (automatic), or approval_request / approval_wait for any action",
            "kill_switch": "live_kill stops mandate spending, gateway calls and room messages for one agent or all; audit "
                           "logging is never blocked",
        }

    # ---------------- kill switch ----------------

    @mcp.tool(title="Kill switch: stop an agent", annotations=DESTRUCTIVE)
    def live_kill(
        ctx: Context,
        stream_id: Annotated[str, Field(description="The agent (stream) to stop, or '*' for every agent in your organization")] = "*",
        reason: Annotated[str, Field(description="Why (shown in your log and on your live channel)")] = "",
    ) -> CallToolResult:
        """Stop an agent at once: mandate_spend, your gateways and your room messages are refused until live_resume.
        Takes effect on the next call, and is pushed to your live channel immediately. Audit logging keeps working.
        Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        try:
            return result(live.kill(org["org_id"], stream_id.strip() or "*", reason, "organization (mcp)"))
        except ValueError as e:
            return result({"error": str(e)}, True)

    @mcp.tool(title="Kill switch: resume an agent", annotations=DESTRUCTIVE)
    def live_resume(
        ctx: Context,
        stream_id: Annotated[str, Field(description="The agent to resume, or '*'")] = "*",
    ) -> CallToolResult:
        """Lift a kill switch set with live_kill. Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        try:
            return result(live.resume(org["org_id"], stream_id.strip() or "*", "organization (mcp)"))
        except ValueError as e:
            return result({"error": str(e)}, True)

    @mcp.tool(title="Live status", annotations=READ_ONLY)
    def live_status(ctx: Context) -> CallToolResult:
        """Your kill switches, live-approval thresholds, pending approvals, gateways, rooms and usage this month. Requires the
        organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        oid = org["org_id"]
        return result({"org_id": oid, "plan": live.plan_of(oid), "killed": live.killed_list(oid), "policies": live.policies(oid),
                       "pending_approvals": live.approvals_for(oid, "pending"), "gateways": gateways.list_for(oid),
                       "rooms": rooms.list_for(oid),
                       "usage_this_month": {"gateway_calls": live.usage(oid, "gateway"), "room_messages": live.usage(oid, "room"),
                                            "free_gateway_calls": GW_FREE, "free_room_messages": ROOM_FREE}})

    # ---------------- human approvals ----------------

    @mcp.tool(title="Approvals: set a live-approval threshold", annotations=WRITE)
    def approval_policy_set(
        ctx: Context,
        stream_id: Annotated[str, Field(description="The agent (stream), or '*' for all of them")],
        approve_over_usdc: Annotated[str | None, Field(description="Payments above this need a live human approval; omit to remove the rule")] = None,
    ) -> CallToolResult:
        """Make mandate_spend pause for a human on large payments: any payment over the threshold creates an approval request
        that the mandate's principal must sign with their wallet before the agent can spend. Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        try:
            return result(live.policy_set(org["org_id"], stream_id.strip(), approve_over_usdc))
        except ValueError as e:
            return result({"error": str(e)}, True)

    @mcp.tool(title="Approvals: ask a human", annotations=WRITE)
    def approval_request(
        ctx: Context,
        stream_id: Annotated[str, Field(description="The agent asking")],
        action: Annotated[str, Field(description="Plain-English action the human is approving, e.g. 'Wire 4,800 USDC to Acme for invoice 1042'")],
        mandate_id: Annotated[str | None, Field(description="mdt_... : the mandate's principal decides")] = None,
        approver_wallet: Annotated[str | None, Field(description="0x wallet of the human who decides (if no mandate_id)")] = None,
        amount_usdc: Annotated[str | None, Field(description="Amount, if money is involved")] = None,
        payee: Annotated[str, Field(description="Payee address or domain, if money is involved")] = "",
        reference: Annotated[str, Field(description="Invoice or order reference")] = "",
        reason: Annotated[str, Field(description="Why the agent wants to do this")] = "",
        ttl_s: Annotated[int, Field(description="Seconds the request stays open (60-86400)", ge=60, le=86400)] = 900,
    ) -> CallToolResult:
        """Ask a human to approve (or deny) an action. Returns approve_url for them: they read the request and sign with their
        wallet (free, no transaction). Your agent then calls approval_wait, or watches your live channel for approval.approved.
        Only the named wallet can decide; your API key can only cancel. Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        try:
            a = live.approval_request(org, stream_id, action, amount=amount_usdc, payee=payee, reference=reference,
                                      reason=reason, approver_wallet=approver_wallet, mandate_id=mandate_id, ttl_s=ttl_s)
            return result({**a, "next": f"Send the human {a['approve_url']}, then call approval_wait with this approval_id."})
        except (LiveError, MandateError, ValueError) as e:
            return result({"error": str(e)}, True)

    @mcp.tool(title="Approvals: check one", annotations=READ_ONLY)
    def approval_status(approval_id: Annotated[str, Field(description="apr_... ID")]) -> CallToolResult:
        """Status of an approval request: pending, approved, denied, expired or cancelled, with the human's wallet signature
        once they decide. Free."""
        try:
            return result(live.approval_public(approval_id))
        except LiveError as e:
            return result({"error": str(e)}, True)

    @mcp.tool(title="Approvals: wait for the human", annotations=READ_ONLY)
    async def approval_wait(
        approval_id: Annotated[str, Field(description="apr_... ID")],
        timeout_s: Annotated[int, Field(description="How long to wait (1-55 seconds); call again to keep waiting", ge=1, le=55)] = 30,
    ) -> CallToolResult:
        """Block until the human decides (or timeout_s passes). Returns the current status; if still pending, call again.
        Free."""
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                a = live.approval_public(approval_id)
            except LiveError as e:
                return result({"error": str(e)}, True)
            if a["status"] != "pending" or time.monotonic() >= deadline:
                return result({**a, "waited": a["status"] == "pending" and "timed out; call again to keep waiting" or "decided"})
            await anyio.sleep(0.5)

    @mcp.tool(title="Approvals: cancel", annotations=DESTRUCTIVE)
    def approval_cancel(ctx: Context, approval_id: Annotated[str, Field(description="apr_... ID")]) -> CallToolResult:
        """Withdraw an approval request (or revoke an approval not yet used). Your key cannot approve, only cancel. Requires the
        organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        try:
            return result(live.approval_cancel(org["org_id"], approval_id.strip()))
        except LiveError as e:
            return result({"error": str(e)}, True)

    @mcp.tool(title="Approvals: list yours", annotations=READ_ONLY)
    def approval_list(ctx: Context, status: Annotated[str | None, Field(description="pending, approved, denied, expired or cancelled")] = None) -> CallToolResult:
        """Your organization's approval requests, newest first. Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        return result({"approvals": live.approvals_for(org["org_id"], status)})

    # ---------------- trust feed ----------------

    @mcp.tool(title="Trust feed: recent events", annotations=READ_ONLY)
    def trust_events(
        ctx: Context,
        address: Annotated[str | None, Field(description="Only events about this 0x wallet")] = None,
        passport_id: Annotated[str | None, Field(description="Only events about this passport")] = None,
        limit: Annotated[int, Field(description="1-200", ge=1, le=200)] = 50,
    ) -> CallToolResult:
        """The latest trust-change events: passports issued, revoked or re-scored, wallets bound or unbound, mandates activated
        or revoked, transparency-log heads anchored. Without a Pro key the feed is delayed (see live_info); use the WebSocket or
        SSE stream for real time. Free."""
        org = org_from(ctx)
        delay = live.public_delay(org)
        filt = make_filter({"address": address, "passport_id": passport_id})
        evs = [e for e in live.bus.recent("trust", 200, delay) if filt(e)][-limit:]
        return result({"delay_seconds": int(delay), "events": evs, "stream": f"{ws_base}/live/ws", "sse": f"{base}/live/events"})

    # ---------------- gateway ----------------

    @mcp.tool(title="Gateway: protect and meter an MCP server", annotations=WRITE)
    async def gateway_create(
        ctx: Context,
        name: Annotated[str, Field(description="A name for this gateway, e.g. 'acme-search-mcp'")],
        upstream_url: Annotated[str, Field(description="The MCP server's public https URL (streamable HTTP), e.g. https://api.acme.com/mcp")],
        min_score: Annotated[int, Field(description="0 = open to everyone. >0 = callers must prove a KYA wallet whose Passport scores at least this (0-1000)", ge=0, le=1000)] = 0,
        rate_per_min: Annotated[int, Field(description="Requests per minute per caller (1-1200)", ge=1, le=1200)] = 60,
    ) -> CallToolResult:
        """Put your MCP server behind Privi. You get an HTTP URL and a WebSocket URL that forward to it unchanged (x402
        payments keep working) while Privi rate-limits callers, optionally requires a Privi Passport, meters every tool call
        and writes each call to your tamper-evident log. The kill switch stops the gateway instantly. Upstream must be public
        HTTPS. Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        try:
            g = await gateways.create(org, name, upstream_url, min_score, rate_per_min)
            return result({**g, "next": "Point your agents at http_url (or ws_url) instead of the upstream URL; view usage with gateway_stats."})
        except (GatewayError, ValueError) as e:
            return result({"error": str(e)}, True)

    @mcp.tool(title="Gateway: info", annotations=READ_ONLY)
    def gateway_info(gw_id: Annotated[str, Field(description="gw_... ID")]) -> CallToolResult:
        """Public description of a gateway: where it forwards, whether callers need a Passport, its rate limit and its call
        counts. Free."""
        try:
            return result(gateways.public(gw_id))
        except GatewayError as e:
            return result({"error": str(e)}, True)

    @mcp.tool(title="Gateway: your gateways", annotations=READ_ONLY)
    def gateway_list(ctx: Context) -> CallToolResult:
        """Your organization's gateways. Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        return result({"gateways": gateways.list_for(org["org_id"])})

    @mcp.tool(title="Gateway: usage", annotations=READ_ONLY)
    def gateway_stats(ctx: Context, gw_id: Annotated[str, Field(description="gw_... ID")]) -> CallToolResult:
        """Calls, errors, denials and x402 payment prompts per tool and per day for one of your gateways, plus your monthly quota.
        Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        try:
            return result(gateways.stats(org["org_id"], gw_id.strip()))
        except GatewayError as e:
            return result({"error": str(e)}, True)

    @mcp.tool(title="Gateway: delete", annotations=DESTRUCTIVE)
    def gateway_delete(ctx: Context, gw_id: Annotated[str, Field(description="gw_... ID")]) -> CallToolResult:
        """Turn a gateway off. Its URLs stop working at once; history stays in your log. Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        try:
            return result(gateways.delete(org["org_id"], gw_id.strip()))
        except GatewayError as e:
            return result({"error": str(e)}, True)

    # ---------------- rooms ----------------

    @mcp.tool(title="Rooms: open a live room", annotations=WRITE)
    def room_open(
        ctx: Context,
        title: Annotated[str, Field(description="What the room is for, e.g. 'Negotiate delivery of lot 4471'")],
        counterparty_org_id: Annotated[str | None, Field(description="org_... that may join; omit to get a one-time join_code instead")] = None,
        price_per_message_usdc: Annotated[str | None, Field(description="Charge the guest this much per message (needs payee)")] = None,
        payee: Annotated[str | None, Field(description="Who is paid for messages: 0x address or domain")] = None,
        max_messages: Annotated[int, Field(description="Message cap (2-10000)", ge=2, le=10000)] = 500,
        hours: Annotated[int, Field(description="Hours the room stays open (1-168)", ge=1, le=168)] = 24,
    ) -> CallToolResult:
        """Open a live, hash-chained conversation room for two organizations' agents. Both connect over WebSocket
        (ws_url), authenticate with their API keys and talk in real time; closing the room seals the transcript on the Privi
        chain. Optionally charge per message, paid under the guest's human-signed Mandate. Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        try:
            return result(rooms.open(org, title, counterparty_org_id, price_per_message_usdc, payee, max_messages, hours))
        except (RoomError, MandateError, ValueError) as e:
            return result({"error": str(e)}, True)

    @mcp.tool(title="Rooms: info", annotations=READ_ONLY)
    def room_info(room_id: Annotated[str, Field(description="rm_... ID")]) -> CallToolResult:
        """Public facts about a room: parties, price, message count, head hash and its seal once closed. No message text. Free."""
        try:
            return result(rooms.public(room_id))
        except RoomError as e:
            return result({"error": str(e)}, True)

    @mcp.tool(title="Rooms: list yours", annotations=READ_ONLY)
    def room_list(ctx: Context) -> CallToolResult:
        """Rooms your organization owns or joined. Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        return result({"rooms": rooms.list_for(org["org_id"])})

    @mcp.tool(title="Rooms: transcript", annotations=READ_ONLY)
    def room_transcript(ctx: Context, room_id: Annotated[str, Field(description="rm_... ID")]) -> CallToolResult:
        """Every message in a room you are part of, with the chain check. Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        try:
            return result(rooms.transcript(room_id.strip(), org))
        except RoomError as e:
            return result({"error": str(e)}, True)

    @mcp.tool(title="Rooms: close and seal", annotations=DESTRUCTIVE)
    async def room_close(ctx: Context, room_id: Annotated[str, Field(description="rm_... ID")]) -> CallToolResult:
        """Close a room and seal its transcript: the hash is signed (Ed25519 + ML-DSA-87), anchored on the Privi chain and written
        to both organizations' logs. Either party can close. Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        try:
            return result(await rooms.close(room_id.strip(), org))
        except RoomError as e:
            return result({"error": str(e)}, True)

    @mcp.tool(title="Rooms: verify a sealed transcript", annotations=READ_ONLY)
    def room_verify(
        room_id: Annotated[str, Field(description="rm_... ID")],
        messages: Annotated[list[dict[str, Any]] | None, Field(description="The transcript's 'messages' array exactly as room_transcript returned it")] = None,
    ) -> CallToolResult:
        """Check a closed room's seal (signature, on-chain anchor) and, if you pass the transcript, that it is complete and
        unaltered. Free; no key needed."""
        try:
            return result(rooms.verify(room_id.strip(), messages))
        except RoomError as e:
            return result({"error": str(e)}, True)
