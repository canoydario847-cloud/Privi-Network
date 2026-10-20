"""Privi Ledger MCP server: tamper-evident audit logs for AI agents.

Free:          ledger_pricing, ledger_check_receipt
Paid (x402):   ledger_audit_stream      (auditors, USDC on Base)
Org API key:   ledger_record_action, ledger_read_stream, ledger_list_streams
Admin (HTTP):  POST /admin/orgs         (create an organization and its API key)
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import time
import threading
from typing import Annotated, Any

import anyio
from mcp.server.mcpserver import Context, MCPServer
from mcp_types import BlobResourceContents, CallToolResult, EmbeddedResource, TextContent, ToolAnnotations
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .config import Settings
from .store import ACTION_TYPES, OUTCOMES, Ledger, check_id
from .anchoring import AnchorClient, AnchorError, Checkpoints, HttpAnchorClient, describe, start_loop
from .reports import ReportStore, build_body, report_hash, to_markdown
from .pdf import render_pdf
from .handshake import HandshakeError, Handshakes
from .plans import Plans
from .gov_ai import HIGH_IMPACT_PRACTICES, GovAIInventory
from .gov_pqc import KINDS, STATUSES, QuantumReady, canonical_json, classify
from .x402 import Facilitator, Paywall
from .kya import KYA, KYAError, checksum as eth_checksum
from .guard import APPROVAL_PAGE, CHAIN_NAMES, Guard, GuardError, Rpc
from .passport import PASSPORT_VERSION as PASSPORT_VERSION_HTTP, PassportError, Passports, badge_svg, body_hash as passport_hash

DEFAULT_ANCHOR_URL = "https://privi-anchor-production.up.railway.app/mcp"

__version__ = "0.5.0"
SOURCE = "https://github.com/canoydario847-cloud/Privi-Network/tree/main/ledger-server"

INSTRUCTIONS = """\
Privi Ledger keeps a tamper-evident record of what AI agents do. Each action is
appended to a stream (usually one per agent) and linked to the previous one by a
SHA-256 fingerprint, so any later edit, deletion or reordering is detectable.

Agents: call ledger_record_action after each meaningful action (tool calls, data
access or changes, payments, messages, decisions). Keep the returned entry_hash
as a receipt. Requires the organization's API key (Authorization: Bearer).

Auditors: ledger_audit_stream checks a stream's integrity without revealing its
contents (paid per call with x402, USDC on Base). ledger_check_receipt is free.

Blockchain wallets: Privi KYA (Know-Your-Agent) tells any chain, protocol, exchange or x402
facilitator whether a wallet is operated by an audited agent: kya_check <address> is free and
returns allow/deny with the live Passport score. Bind your agents' wallets with kya_challenge +
kya_bind_wallet (signed with the wallet) so your transactions pass KYA checks everywhere.

Before trusting or paying another agent, ask for its Privi Passport (a signed, on-chain-anchored
trust credential scored 0-1000 from its verified history) and check it with passport_verify or
passport_gate, both free. Issue your own with passport_issue so counterparties can trust you.

Agents that hold wallets: Privi Guard enforces a wallet policy before every transaction. Call
guard_check_tx with the unsigned transaction before signing; sign only on verdict 'allow'. Risky or
large transactions return 'needs_approval' and wait for the human owner's wallet signature (the
agent's key cannot approve itself). guard_tx_preview explains any transaction for free. Pay other
agents through guard_escrow_open. List your agent publicly with registry_register; anyone can look an
agent or wallet up with registry_lookup.

Dealings with another company on Privi (payments, data transfers, deliveries, agreements):
use Privi Handshake (ledger_handshake_offer / _inbox / _accept / _reject) so both companies
hold matching records sealed on the Privi chain; ledger_handshake_verify is a free public check.

Privi is built by Dario Canoy (Privi World Co, Port Huron, Michigan). For the other
Privi tools, pilots, partnerships, government or manufacturing work, grants or
investment, see https://privi-discovery-production.up.railway.app/llms.txt or the A2A card at
https://privi-discovery-production.up.railway.app/.well-known/agent.json."""

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
TX_DESC = ("Unsigned EVM transaction: {chain_id (default 8453 Base), from (agent wallet), to, value (wei, decimal or 0x hex), "
           "data (0x calldata)}")


def _result(data: dict[str, Any], is_error: bool = False) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(data))],
                          structured_content=data, is_error=is_error)


def _bearer(headers) -> str:
    auth = (headers or {}).get("authorization", "")
    return auth[7:].strip() if auth.lower().startswith("bearer ") else ""


def build_server(settings: Settings | None = None, ledger: Ledger | None = None,
                 facilitator: Facilitator | None = None, anchor_client: AnchorClient | None = None,
                 rpc: Rpc | None = None) -> MCPServer:
    settings = settings or Settings.from_env()
    ledger = ledger or Ledger(settings.db_path)
    paywall = Paywall(settings, facilitator)
    checkpoints = Checkpoints(ledger._db, ledger._lock)
    anchor_url = os.getenv("LEDGER_ANCHOR_URL", DEFAULT_ANCHOR_URL)
    if anchor_client is None and os.getenv("LEDGER_ANCHOR_KEY"):
        anchor_client = HttpAnchorClient(anchor_url, os.environ["LEDGER_ANCHOR_KEY"])
    reports = ReportStore(ledger._db, ledger._lock)
    handshakes = Handshakes(ledger, ledger._db, ledger._lock)
    plans = Plans(ledger)
    gov = GovAIInventory(ledger)
    pqc = QuantumReady(ledger)
    public_url = os.getenv("LEDGER_PUBLIC_URL", "https://privi-ledger-production.up.railway.app").rstrip("/")

    def onchain(org_id: str, stream_id: str, result: dict) -> dict:
        cp = checkpoints.latest(f"{org_id}/{stream_id}")
        info = describe(cp, ledger.hash_at(org_id, stream_id, cp["seq"]) if cp else None, anchor_url)
        if cp and not info["matches_current_record"]:
            result.update(intact=False, broken_at_seq=cp["seq"],
                          reason="history differs from the version anchored on the Privi chain")
        return info

    mcp = MCPServer(
        name="privi-ledger", title="Privi Ledger",
        description="Tamper-evident audit logs for AI agents; auditors verify integrity, paid per call via x402.",
        instructions=INSTRUCTIONS, website_url=SOURCE, version=__version__,
    )

    passports = Passports(ledger, ledger._db, ledger._lock, reports, handshakes, onchain, public_url,
                          os.getenv("LEDGER_PASSPORT_SIGNING_KEY", ""))

    kya = KYA(ledger._db, ledger._lock, passports, public_url)

    rpc_urls = None
    if os.getenv("GUARD_RPC_URLS"):
        rpc_urls = {int(k): v for k, v in json.loads(os.environ["GUARD_RPC_URLS"]).items()}
    guard = Guard(ledger, ledger._db, ledger._lock, kya, passports, public_url,
                  rpc if rpc is not None else (None if os.getenv("GUARD_SIMULATION") == "off" else Rpc(rpc_urls)),
                  os.getenv("GUARD_ARBITER_KEY", ""), os.getenv("GUARD_ESCROW_CONTRACT", ""))

    def org_from(ctx: Context) -> dict | None:
        headers = ctx.headers
        key = _bearer(headers) if headers is not None else os.getenv("LEDGER_LOCAL_ORG_KEY", "")
        return ledger.org_for_key(key)

    unauthorized = _result({"error": "a valid organization API key is required (Authorization: Bearer <key>)"},
                           is_error=True)

    def over_limit(org_id: str, n: int = 1) -> CallToolResult | None:
        ok, st = plans.can_write(org_id, n)
        if ok:
            return None
        return _result({"error": f"free plan limit reached ({st['monthly_limit']} entries this month)",
                        "plan": st, "upgrade": f"call ledger_upgrade_pro (${settings.prices_usd['ledger_upgrade_pro']} "
                        f"USDC per 30 days via x402) for unlimited entries"}, is_error=True)

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
                "ledger_signup": "free (free plan: monthly entry limit)",
                "ledger_upgrade_pro": f"${settings.prices_usd['ledger_upgrade_pro']} per 30 days (x402), unlimited entries",
                "passport_issue": f"organization API key; free on Pro/enterprise, ${settings.prices_usd['passport_issue']} per passport (x402) on the free plan",
                "passport_verify": "free", "passport_gate": "free", "passport_list": "organization API key",
                "passport_revoke": "organization API key",
                "kya_check": "free", "kya_challenge": "organization API key", "kya_bind_wallet": "organization API key",
                "kya_wallets": "organization API key", "kya_unbind_wallet": "organization API key",
                "guard_tx_preview": "free", "guard_check_tx": "organization API key",
                "guard_policy_set": "organization API key", "guard_policies": "organization API key",
                "guard_approvals": "organization API key", "guard_approve": "free (owner wallet signature)",
                "guard_escrow_open": "organization API key", "guard_escrow_act": "organization API key",
                "guard_escrows": "organization API key", "guard_escrow_status": "free",
                "registry_register": "organization API key", "registry_lookup": "free",
                "registry_verify": "free", "registry_remove": "organization API key",
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
            if not a:
                return {"found": False, "org_id": oid, "stream_id": sid}
            a["onchain_checkpoint"] = onchain(oid, sid, a)
            return {"found": True, **a}

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
        if blocked := over_limit(org["org_id"]):
            return blocked
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
        integrity = {"intact": check.valid, "broken_at_seq": check.broken_at_seq,
                     "reason": check.reason, "entry_count": check.entry_count}
        integrity["onchain_checkpoint"] = onchain(org["org_id"], stream_id, integrity)
        return _result({
            "stream_id": stream_id, "entries": page,
            "next_after_seq": page[-1]["seq"] if len(page) == limit else None,
            "integrity": integrity,
        })

    @mcp.tool(title="List streams", annotations=READ_ONLY)
    def ledger_list_streams(ctx: Context) -> CallToolResult:
        """List your organization's streams with entry counts. Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        return _result({"org_id": org["org_id"], "organization": org["name"], "streams": ledger.streams(org["org_id"])})

    # ---------------- compliance reports ----------------

    @mcp.tool(title="Compliance report", annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                                                     idempotentHint=False, openWorldHint=True))
    async def ledger_compliance_report(
        ctx: Context,
        since: Annotated[str | None, Field(description="Start of period, ISO 8601 UTC (e.g. 2026-10-01T00:00:00Z). Omit for all history")] = None,
        until: Annotated[str | None, Field(description="End of period, ISO 8601 UTC. Omit for now")] = None,
        streams: Annotated[list[str] | None, Field(description="Only these streams; omit for all")] = None,
    ) -> CallToolResult:
        """Audit-ready report of your AI agents' activity for a period (SOC 2 evidence, security
        questionnaires, AI-regulation record keeping): actions by type, failures, human approvals,
        log integrity, on-chain status, and findings. The report's hash is anchored on the Privi
        blockchain so it cannot be edited later without detection. Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        body = build_body(ledger, org, onchain, since, until, streams)
        h = report_hash(body)
        att: dict[str, Any] = {"report_hash": h, "algorithm": "sha256 over canonical JSON (sorted keys, no spaces)"}
        if anchor_client:
            try:
                r = await anyio.to_thread.run_sync(anchor_client.anchor, [h], f"compliance report {org['org_id']}")
                rc = next(x for x in r["receipts"] if x["hash"] == h)
                att.update(anchored=True, tx_hash=r["tx_hash"], proof=rc["proof"], merkle_root=r["merkle_root"],
                           block_number=r.get("block_number"), block_time=r.get("block_time"),
                           chain_id=r.get("chain_id"), status=r.get("status"), anchor_server=anchor_url)
            except (AnchorError, StopIteration, KeyError) as e:
                att.update(anchored=False, reason=f"anchoring failed: {e}")
        else:
            att.update(anchored=False, reason="anchoring is not configured on this server")
        rid = reports.save(org["org_id"], body, att)
        return _result({"report_id": rid, "report": body, "attestation": att, "markdown": to_markdown(body, att)})

    @mcp.tool(title="Compliance report PDF", annotations=READ_ONLY)
    def ledger_report_pdf(
        report_id: Annotated[str, Field(description="report_id returned by ledger_compliance_report")],
        ctx: Context,
    ) -> CallToolResult:
        """A finished PDF of a sealed compliance report, for auditors and customers. Returned as base64
        (pdf_base64) and as an embedded PDF resource; also downloadable at /reports/<report_id>.pdf with the
        organization key. Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        rec = reports.get(report_id, org["org_id"])
        if not rec:
            return _result({"error": "no such report for this organization"}, is_error=True)
        pdf = render_pdf(rec["body"], rec["attestation"], report_id)
        b64 = base64.b64encode(pdf).decode()
        data = {"report_id": report_id, "filename": f"{report_id}.pdf", "bytes": len(pdf), "pdf_base64": b64,
                "download": f"/reports/{report_id}.pdf"}
        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps({k: v for k, v in data.items() if k != "pdf_base64"})),
                     EmbeddedResource(type="resource", resource=BlobResourceContents(
                         uri=f"privi-ledger://reports/{report_id}.pdf", mimeType="application/pdf", blob=b64))],
            structured_content=data)

    @mcp.tool(title="Verify a report", annotations=READ_ONLY)
    async def ledger_verify_report(
        report: Annotated[dict[str, Any], Field(description="The 'report' object exactly as received from ledger_compliance_report")],
    ) -> CallToolResult:
        """Check that a compliance report is unaltered: recomputes its hash, confirms Privi Ledger issued it,
        and checks the anchor on the Privi blockchain. Free; no key needed."""
        h = report_hash(report)
        rec = reports.by_hash(h)
        if not rec:
            return _result({"valid": False, "report_hash": h,
                            "reason": "no report with this exact content was issued; it may have been edited"})
        att = rec["attestation"]
        out = {"report_hash": h, "report_id": rec["report_id"], "issued_at": rec["created_at"],
               "organization": report.get("organization"), "anchored": bool(att.get("anchored"))}
        if att.get("anchored") and anchor_client and hasattr(anchor_client, "verify"):
            try:
                v = await anyio.to_thread.run_sync(anchor_client.verify, h, att["tx_hash"], att["proof"])
                out.update(onchain_verified=bool(v.get("verified")), block_number=v.get("block_number"),
                           block_time_utc=v.get("block_time_utc"), tx_hash=att["tx_hash"])
            except AnchorError as e:
                out.update(onchain_verified=None, onchain_error=str(e))
        out["valid"] = out.get("onchain_verified", True) is not False
        return _result(out)

    # ---------------- self-serve plans ----------------

    @mcp.tool(title="Sign up", annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                                           idempotentHint=False, openWorldHint=False))
    def ledger_signup(
        organization_name: Annotated[str, Field(description="Your company or project name")],
    ) -> CallToolResult:
        """Create a Privi Ledger organization on the free plan and get its API key (shown once; store it).
        Free plan: up to the monthly entry limit, all tools included. Upgrade any time with
        ledger_upgrade_pro. No key needed to sign up."""
        try:
            org = plans.signup(organization_name)
        except ValueError as e:
            return _result({"error": str(e)}, is_error=True)
        return _result({**org, "plan": plans.status(org["org_id"]),
                        "next": "Send 'Authorization: Bearer <api_key>' and call ledger_record_action after each agent action.",
                        "note": "Store api_key now; it cannot be shown again."})

    @mcp.tool(title="Plan and usage", annotations=READ_ONLY)
    def ledger_plan(ctx: Context) -> CallToolResult:
        """Your plan, entries used this month, the limit, and when a Pro plan renews. Requires your organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        return _result({"org_id": org["org_id"], "organization": org["name"], **plans.status(org["org_id"]),
                        "pro_price_usd_per_30_days": settings.prices_usd["ledger_upgrade_pro"]})

    @mcp.tool(title="Upgrade to Pro", annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                                                   idempotentHint=False, openWorldHint=True))
    async def ledger_upgrade_pro(ctx: Context) -> CallToolResult:
        """Buy 30 days of Privi Ledger Pro (unlimited entries) for your organization, paid in USDC on Base
        via x402. Each call adds 30 days. Requires your organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized

        async def work() -> dict[str, Any]:
            st = plans.extend_pro(org["org_id"])
            ledger.record(org["org_id"], "privi-billing", "Privi Ledger", "payment",
                          f"Pro plan purchased: 30 days, ${settings.prices_usd['ledger_upgrade_pro']} USDC",
                          "ledger_upgrade_pro", "success", {"paid_until": st["paid_until"]})
            return {"upgraded": True, "org_id": org["org_id"], **st}

        return await paywall.run("ledger_upgrade_pro", "Privi Ledger Pro, 30 days",
                                 dict(ctx.request_context.meta or {}), work)

    # ---------------- Privi Gov AI Inventory (OMB M-25-21) ----------------

    @mcp.tool(title="Save an AI use case", annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                                                      idempotentHint=True, openWorldHint=False))
    def gov_ai_usecase_save(
        use_case: Annotated[dict[str, Any], Field(description=(
            "AI use case record in OMB M-25-21 reporting fields. Required: use_case_id, name, stage "
            "(pre_deployment|pilot|deployed|retired), high_impact, purpose, outputs, sourcing (in_house|vendor|both), "
            "involves_pii, custom_code. Optional: bureau, contact_email, topic_area, ai_classification, "
            "withhold_from_public, expected_benefits, start_date, vendor_name, ato_system_name, data_description, "
            "open_data_link, pia_link, demographic_features, code_link, monitoring_streams (Ledger stream IDs), "
            "waivers [{practice, justification}], practices {name: {done, evidence, date}} with names: "
            + ", ".join(HIGH_IMPACT_PRACTICES)))],
        actor: Annotated[str, Field(description="Who is making the change (person or agent)")],
        ctx: Context,
        merge: Annotated[bool, Field(description="Merge into the existing record (true) or replace it (false)")] = True,
    ) -> CallToolResult:
        """Add or update an entry in your agency's AI use case inventory (OMB M-25-21). Every change creates a
        new version and is written to your tamper-evident 'ai-inventory' log. Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        if blocked := over_limit(org["org_id"]):
            return blocked
        try:
            return _result(gov.upsert(org["org_id"], actor, use_case, merge))
        except ValueError as e:
            return _result({"error": str(e)}, is_error=True)

    @mcp.tool(title="AI use case inventory", annotations=READ_ONLY)
    def gov_ai_inventory(
        ctx: Context,
        use_case_id: Annotated[str | None, Field(description="One use case; omit for all")] = None,
    ) -> CallToolResult:
        """Your agency's AI use case inventory: the current version of each record. Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        return _result({"org_id": org["org_id"], "use_cases": gov.latest(org["org_id"], use_case_id)})

    @mcp.tool(title="Check inventory readiness", annotations=READ_ONLY)
    def gov_ai_inventory_check(ctx: Context) -> CallToolResult:
        """Flags what an OMB M-25-21 review would flag before you submit: missing required fields, PII without a
        Privacy Impact Assessment, and high-impact AI in pilot or deployment missing any minimum risk practice
        (testing, impact assessment, independent review, monitoring, operator training, fail-safe, appeals, public
        feedback) or without a recently active activity log as monitoring evidence. Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        return _result(gov.check(org["org_id"]))

    @mcp.tool(title="Export public inventory", annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                                                          idempotentHint=False, openWorldHint=True))
    async def gov_ai_inventory_export(
        ctx: Context,
        include_withheld: Annotated[bool, Field(description="Include use cases marked withhold_from_public (internal copy)")] = False,
    ) -> CallToolResult:
        """Machine-readable CSV of your publicly releasable AI use cases (for publishing at agency.gov/ai), with its
        SHA-256 sealed on the Privi blockchain so the published file can be proven unaltered. Requires the
        organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        text, rows = gov.export_csv(org["org_id"], include_withheld)
        h = hashlib.sha256(text.encode("utf-8")).hexdigest()
        att: dict[str, Any] = {"export_hash": h, "rows": rows, "include_withheld": include_withheld}
        if anchor_client:
            try:
                r = await anyio.to_thread.run_sync(anchor_client.anchor, [h], f"AI inventory export {org['org_id']}")
                rc = next(x for x in r["receipts"] if x["hash"] == h)
                att.update(anchored=True, tx_hash=r["tx_hash"], proof=rc["proof"], block_number=r.get("block_number"),
                           chain_id=r.get("chain_id"))
            except (AnchorError, StopIteration, KeyError) as e:
                att.update(anchored=False, reason=f"anchoring failed: {e}")
        else:
            att.update(anchored=False, reason="anchoring is not configured on this server")
        gov.save_export(org["org_id"], h, rows, att)
        ledger.record(org["org_id"], "ai-inventory", "Privi Ledger", "data_access",
                      f"Exported AI use case inventory ({rows} use case(s){', including withheld' if include_withheld else ''})",
                      "ai-inventory-export", "success", {"export_hash": h, "anchored": att.get("anchored")})
        return _result({"csv": text, "attestation": att,
                        "note": "Column names follow the M-25-21 reporting fields; confirm against OMB's current template."})

    @mcp.tool(title="Verify a published inventory", annotations=READ_ONLY)
    def gov_ai_verify_export(
        csv_text: Annotated[str, Field(description="The exact CSV file contents as published")],
    ) -> CallToolResult:
        """Check that a published AI inventory file is exactly what the agency exported from Privi Ledger, and
        return its on-chain seal. Free; no key needed."""
        h = hashlib.sha256(csv_text.encode("utf-8")).hexdigest()
        rec = gov.find_export(h)
        if not rec:
            return _result({"valid": False, "export_hash": h, "reason": "no export with this exact content; it may have been edited"})
        return _result({"valid": True, "export_hash": h, **rec})

    # ---------------- Privi Quantum-Ready (post-quantum migration, OMB M-26-15) ----------------

    @mcp.tool(title="Classify an algorithm", annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    def gov_pqc_classify(
        algorithms: Annotated[list[str], Field(description="Algorithm or cipher-suite names, e.g. 'RSA-2048', 'ECDHE-RSA-AES256-GCM', 'X25519MLKEM768'")],
    ) -> CallToolResult:
        """Classify cryptographic algorithms as quantum-vulnerable (RSA, ECDH, ECDSA, EdDSA, DH, DSA, MQV),
        post-quantum (ML-KEM, ML-DSA, SLH-DSA), hybrid, symmetric/hash, or unknown. Free."""
        return _result({"results": [classify(a) for a in algorithms[:200]]})

    @mcp.tool(title="Save a system's crypto inventory", annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                                                                   idempotentHint=True, openWorldHint=False))
    def gov_pqc_system_save(
        system: Annotated[dict[str, Any], Field(description=(
            "System record: system_id, name, bureau, owner, high_value_asset, high_impact, sensitive_until_year, "
            "fedramp_cloud, notes, assets [{asset_id, kind (" + "|".join(KINDS) + "), algorithm, key_size, protocol, "
            "location, product, vendor, status (" + "|".join(STATUSES) + "), target_date (YYYY-MM-DD), replacement, evidence}]. "
            "Replaces the system's previous inventory."))],
        actor: Annotated[str, Field(description="Who made the change (person, scanner or agent)")],
        ctx: Context,
    ) -> CallToolResult:
        """Record the cryptographic inventory (CBOM) of one system for post-quantum migration. Every change creates
        a new version and is written to the agency's tamper-evident 'pqc-inventory' log. Scanners and agents can
        submit results directly. Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        if blocked := over_limit(org["org_id"]):
            return blocked
        try:
            return _result(pqc.save(org["org_id"], actor, system))
        except ValueError as e:
            return _result({"error": str(e)}, is_error=True)

    @mcp.tool(title="Crypto inventory", annotations=READ_ONLY)
    def gov_pqc_inventory(
        ctx: Context,
        system_id: Annotated[str | None, Field(description="One system; omit for all")] = None,
    ) -> CallToolResult:
        """Current cryptographic inventory of your systems. Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        return _result({"org_id": org["org_id"], "systems": pqc.latest(org["org_id"], system_id)})

    @mcp.tool(title="Post-quantum migration plan", annotations=READ_ONLY)
    def gov_pqc_plan(ctx: Context) -> CallToolResult:
        """Prioritized post-quantum migration plan: every quantum-vulnerable asset ranked (High Value Assets,
        high-impact systems and long-lived sensitive data first; key establishment before signatures), with its
        deadline (key establishment Dec 31 2030, signatures Dec 31 2031), recommended NIST replacement, progress
        metrics, and findings (missed deadlines, TLS below 1.3, no target dates, unrecognized algorithms).
        Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        return _result(pqc.plan(org["org_id"]))

    @mcp.tool(title="Export sealed CBOM and plan", annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                                                              idempotentHint=False, openWorldHint=True))
    async def gov_pqc_export(ctx: Context) -> CallToolResult:
        """Export the full cryptographic inventory (CBOM) and migration plan as one JSON document for OMB, the
        CIO or auditors, with its SHA-256 sealed on the Privi blockchain. Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        doc = {"document_type": "privi/pqc-cbom-and-migration-plan", "version": 1,
               "organization": {"org_id": org["org_id"], "name": org["name"]},
               "systems": [s["record"] for s in pqc.latest(org["org_id"])], "plan": pqc.plan(org["org_id"])}
        h = hashlib.sha256(canonical_json(doc).encode("utf-8")).hexdigest()
        att: dict[str, Any] = {"export_hash": h, "algorithm": "sha256 over canonical JSON (sorted keys, no spaces)"}
        if anchor_client:
            try:
                r = await anyio.to_thread.run_sync(anchor_client.anchor, [h], f"PQC CBOM export {org['org_id']}")
                rc = next(x for x in r["receipts"] if x["hash"] == h)
                att.update(anchored=True, tx_hash=r["tx_hash"], proof=rc["proof"], block_number=r.get("block_number"),
                           chain_id=r.get("chain_id"))
            except (AnchorError, StopIteration, KeyError) as e:
                att.update(anchored=False, reason=f"anchoring failed: {e}")
        else:
            att.update(anchored=False, reason="anchoring is not configured on this server")
        pqc.save_export(org["org_id"], h, att)
        ledger.record(org["org_id"], "pqc-inventory", "Privi Ledger", "data_access",
                      f"Exported CBOM and PQC migration plan ({len(doc['systems'])} system(s))", "pqc-export", "success",
                      {"export_hash": h, "anchored": att.get("anchored")})
        return _result({"document": doc, "attestation": att})

    @mcp.tool(title="Verify a CBOM export", annotations=READ_ONLY)
    def gov_pqc_verify_export(
        document: Annotated[dict[str, Any], Field(description="The 'document' object exactly as exported")],
    ) -> CallToolResult:
        """Check that a CBOM and migration-plan document is exactly what was exported from Privi Ledger and return
        its on-chain seal. Free; no key needed."""
        h = hashlib.sha256(canonical_json(document).encode("utf-8")).hexdigest()
        rec = pqc.find_export(h)
        if not rec:
            return _result({"valid": False, "export_hash": h, "reason": "no export with this exact content; it may have been edited"})
        return _result({"valid": True, "export_hash": h, **rec})

    # ---------------- Privi Handshake (cross-organization) ----------------

    WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)

    @mcp.tool(title="Offer a handshake", annotations=WRITE)
    def ledger_handshake_offer(
        counterparty_org_id: Annotated[str, Field(description="org_id of the other company (must be on Privi Ledger)")],
        stream_id: Annotated[str, Field(description="Your stream to record it in, usually your agent's name")],
        actor: Annotated[str, Field(description="Who is acting on your side")],
        action_type: Annotated[str, Field(description=f"One of: {', '.join(ACTION_TYPES)}")],
        summary: Annotated[str, Field(description="What is being agreed or done between the two companies")],
        ctx: Context,
        resource: Annotated[str, Field(description="Invoice, order, dataset, contract or other reference")] = "",
        details: Annotated[dict[str, Any] | None, Field(description="Terms as structured data (amounts, quantities, dates)")] = None,
        expires_hours: Annotated[float, Field(description="Hours the other company has to respond", gt=0, le=720)] = 72,
    ) -> CallToolResult:
        """Start a Privi Handshake: a two-sided record of a dealing with another company's agent
        (payment, data transfer, delivery, agreement). Recorded in your log now; when the other company
        accepts, both logs hold matching entries and the pair is sealed on the Privi chain. Requires your
        organization API key; the other company must also use Privi Ledger."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        if blocked := over_limit(org["org_id"]):
            return blocked
        try:
            return _result(handshakes.offer(org["org_id"], counterparty_org_id.strip(), stream_id, actor, action_type,
                                            summary, resource, details, expires_hours))
        except (HandshakeError, ValueError) as e:
            return _result({"error": str(e)}, is_error=True)

    @mcp.tool(title="Handshake inbox", annotations=READ_ONLY)
    def ledger_handshake_inbox(ctx: Context) -> CallToolResult:
        """Handshakes sent to and from your organization, newest first, with their terms and status.
        Requires your organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        items = handshakes.inbox(org["org_id"])
        return _result({"org_id": org["org_id"], "pending_for_you": sum(
            1 for h in items if h["direction"] == "incoming" and h["status"] == "offered"), "handshakes": items})

    @mcp.tool(title="Accept a handshake", annotations=WRITE)
    async def ledger_handshake_accept(
        handshake_id: Annotated[str, Field(description="hs_... ID from the offer")],
        stream_id: Annotated[str, Field(description="Your stream to record it in")],
        actor: Annotated[str, Field(description="Who is accepting on your side")],
        ctx: Context,
    ) -> CallToolResult:
        """Accept a handshake addressed to your organization: records the same terms in your log, confirms
        it in the other company's log, and seals the matched pair on the Privi chain. Requires your
        organization API key. Read the terms first with ledger_handshake_inbox."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        if blocked := over_limit(org["org_id"]):
            return blocked
        try:
            r = await anyio.to_thread.run_sync(
                lambda: handshakes.accept(handshake_id.strip(), org["org_id"], stream_id, actor, anchor_client))
            return _result(r)
        except (HandshakeError, ValueError) as e:
            return _result({"error": str(e)}, is_error=True)

    @mcp.tool(title="Reject a handshake", annotations=WRITE)
    def ledger_handshake_reject(
        handshake_id: Annotated[str, Field(description="hs_... ID from the offer")],
        ctx: Context,
        reason: Annotated[str, Field(description="Why it is rejected (shared with the other company)")] = "",
    ) -> CallToolResult:
        """Reject a handshake addressed to your organization; the other company's log records the rejection.
        Requires your organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        try:
            return _result(handshakes.reject(handshake_id.strip(), org["org_id"], reason))
        except (HandshakeError, ValueError) as e:
            return _result({"error": str(e)}, is_error=True)

    @mcp.tool(title="Verify a handshake", annotations=READ_ONLY)
    def ledger_handshake_verify(
        handshake_id: Annotated[str, Field(description="hs_... handshake ID")],
    ) -> CallToolResult:
        """Public check of a handshake: both companies, status, whether both matching log entries still exist,
        and the on-chain seal. Never reveals the terms. Free; useful for disputes and audits."""
        s = handshakes.public_status(handshake_id.strip())
        return _result(s) if s else _result({"error": "no such handshake"}, is_error=True)

    # ---------------- Privi Passport: trust credentials for AI agents ----------------

    async def _anchor_hash(h: str, label: str) -> dict[str, Any]:
        att: dict[str, Any] = {"hash": h, "algorithm": "sha256 over canonical JSON (sorted keys, no spaces)"}
        if not anchor_client:
            return {**att, "anchored": False, "reason": "anchoring is not configured on this server"}
        try:
            r = await anyio.to_thread.run_sync(anchor_client.anchor, [h], label)
            rc = next(x for x in r["receipts"] if x["hash"] == h)
            att.update(anchored=True, tx_hash=r["tx_hash"], proof=rc["proof"], merkle_root=r["merkle_root"],
                       block_number=r.get("block_number"), block_time=r.get("block_time"),
                       chain_id=r.get("chain_id"), status=r.get("status"), anchor_server=anchor_url)
        except (AnchorError, StopIteration, KeyError) as e:
            att.update(anchored=False, reason=f"anchoring failed: {e}")
        return att

    async def _chain_check(att: dict, h: str) -> dict[str, Any]:
        if not (att.get("anchored") and anchor_client and hasattr(anchor_client, "verify")):
            return {}
        try:
            v = await anyio.to_thread.run_sync(anchor_client.verify, h, att["tx_hash"], att["proof"])
            return {"onchain_verified": bool(v.get("verified")), "block_number": v.get("block_number"),
                    "block_time_utc": v.get("block_time_utc"), "tx_hash": att["tx_hash"]}
        except AnchorError as e:
            return {"onchain_verified": None, "onchain_error": str(e)}

    @mcp.tool(title="Issue a Privi Passport", annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                                                           idempotentHint=False, openWorldHint=True))
    async def passport_issue(
        ctx: Context,
        stream_id: Annotated[str | None, Field(description="Issue for one agent (stream). Omit for the whole organization")] = None,
    ) -> CallToolResult:
        """Issue a Privi Passport: a signed, on-chain-anchored trust credential for your agent or organization,
        scored 0-1000 (grade A-E) from verified history, integrity, anchoring, reliability, human oversight,
        compliance reports and confirmed handshakes. Show it to counterparties; they verify it free with
        passport_verify / passport_gate. Valid 30 days. Free on Pro/enterprise; free-plan organizations pay
        per passport via x402. Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        if stream_id:
            try:
                stream_id = check_id(stream_id, "stream_id")
            except ValueError as e:
                return _result({"error": str(e)}, is_error=True)

        async def work() -> dict[str, Any]:
            try:
                body = passports.build(org, stream_id)
            except PassportError as e:
                return {"error": str(e)}
            h = passport_hash(body)
            sig = passports.sign(h)
            att = await _anchor_hash(h, f"privi passport {org['org_id']}")
            passports.save(body, sig, att)
            try:
                ledger.record(org["org_id"], "privi-passport", "Privi Ledger", "other",
                              f"Passport {body['passport_id']} issued: {body['grade']} ({body['score']}/1000) for {body['subject']['stream_id']}",
                              body["passport_id"], "success", {"score": body["score"], "grade": body["grade"], "hash": h})
            except ValueError:
                pass
            return {"passport_id": body["passport_id"], "score": body["score"], "grade": body["grade"],
                    "passport": body, "body_hash": h, "signature": sig, "attestation": att,
                    "public_url": f"{public_url}/passports/{body['passport_id']}",
                    "badge_svg_url": f"{public_url}/passports/{body['passport_id']}/badge.svg",
                    "present_as": "Give counterparties the passport_id (or public_url); they call passport_verify or passport_gate."}

        if plans.status(org["org_id"])["plan"] != "free":
            return _result(await work())
        return await paywall.run("passport_issue", "Privi Passport: signed trust credential for an AI agent",
                                 dict(ctx.request_context.meta or {}), work)

    @mcp.tool(title="Verify a Privi Passport", annotations=READ_ONLY)
    async def passport_verify(
        passport_id: Annotated[str | None, Field(description="pp_... ID, or omit and pass the passport document")] = None,
        passport: Annotated[dict[str, Any] | None, Field(description="The 'passport' object exactly as issued")] = None,
    ) -> CallToolResult:
        """Check an AI agent's Privi Passport before trusting it: Privi signature, content unaltered, not expired or
        revoked, anchor on the Privi chain, and a live re-score of the agent right now (so tampering after issue
        is caught). Free; no key needed."""
        rec = None
        if passport_id:
            rec = passports.get(passport_id)
        elif passport:
            rec = passports.by_hash(passport_hash(passport))
            if not rec:
                return _result({"valid": False, "reason": "no passport with this exact content was issued; it may have been edited"})
        if not rec:
            return _result({"valid": False, "reason": "no such passport"})
        v = passports.check(rec)
        v.update(await _chain_check(rec["attestation"], rec["body_hash"]))
        if v.get("onchain_verified") is False:
            v["valid"] = False
        v["issuer"] = passports.issuer()
        return _result(v)

    @mcp.tool(title="Gate on a Privi Passport", annotations=READ_ONLY)
    async def passport_gate(
        passport_id: Annotated[str, Field(description="pp_... ID presented by the other agent")],
        ctx: Context,
        min_score: Annotated[int, Field(description="Minimum current score 0-1000", ge=0, le=1000)] = 550,
        min_grade: Annotated[str | None, Field(description="Minimum grade A-E (alternative to min_score)")] = None,
        require_anchored: Annotated[bool, Field(description="Require the passport to be anchored on the Privi chain")] = False,
        purpose: Annotated[str, Field(description="What you are about to do with this counterparty (recorded in your log if you send your key)")] = "",
    ) -> CallToolResult:
        """One-call allow/deny decision before transacting with another AI agent: verifies its Privi Passport and
        applies your minimums, returning the reasons. If you send your organization API key the decision is
        recorded in your own tamper-evident log as due-diligence evidence. Free."""
        rec = passports.get(passport_id)
        if not rec:
            d = {"allow": False, "reasons": ["no such passport"], "passport_id": passport_id}
        else:
            v = passports.check(rec)
            v.update(await _chain_check(rec["attestation"], rec["body_hash"]))
            if v.get("onchain_verified") is False:
                v["valid"] = False
            d = {"passport_id": passport_id, "subject": v["subject"],
                 **passports.gate(v, min_score, min_grade, True, require_anchored), "verification": v}
        org = org_from(ctx)
        if org:
            try:
                e = ledger.record(org["org_id"], "privi-passport", "Privi Ledger", "decision",
                                  f"Passport gate {'allowed' if d['allow'] else 'denied'} {passport_id}"
                                  + (f" for: {purpose[:120]}" if purpose else ""), passport_id,
                                  "success" if d["allow"] else "blocked",
                                  {"min_score": min_score, "min_grade": min_grade, "reasons": d["reasons"],
                                   "current_score": d.get("current_score")})
                d["recorded_in_your_log"] = {"stream_id": "privi-passport", "entry_hash": e["entry_hash"]}
            except ValueError:
                pass
        return _result(d)

    @mcp.tool(title="List your passports", annotations=READ_ONLY)
    def passport_list(ctx: Context) -> CallToolResult:
        """Your organization's issued passports with score, grade, expiry and revocation. Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        return _result({"org_id": org["org_id"], "passports": passports.list_for(org["org_id"]),
                        "issuer": passports.issuer()})

    @mcp.tool(title="Revoke a passport", annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True,
                                                                     idempotentHint=True, openWorldHint=False))
    def passport_revoke(
        passport_id: Annotated[str, Field(description="pp_... ID")],
        ctx: Context,
        reason: Annotated[str, Field(description="Why (shown to verifiers)")] = "",
    ) -> CallToolResult:
        """Revoke one of your passports (e.g. an agent was retired or compromised). Verifiers see it immediately.
        Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        try:
            return _result(passports.revoke(passport_id.strip(), org["org_id"], reason))
        except PassportError as e:
            return _result({"error": str(e)}, is_error=True)

    # ---------------- Privi KYA: Know-Your-Agent for blockchain wallets ----------------

    @mcp.tool(title="KYA: check a wallet", annotations=READ_ONLY)
    def kya_check(
        address: Annotated[str, Field(description="0x wallet address about to send or receive a transaction")],
        ctx: Context,
        min_score: Annotated[int, Field(description="Minimum current Passport score 0-1000", ge=0, le=1000)] = 550,
        min_grade: Annotated[str | None, Field(description="Minimum grade A-E")] = None,
        require_signed: Annotated[bool, Field(description="Require wallet ownership proven by signature (not just declared)")] = True,
        purpose: Annotated[str, Field(description="What the transaction is for (recorded in your log if you send your key)")] = "",
    ) -> CallToolResult:
        """Know-Your-Agent for blockchains: is this wallet operated by an audited AI agent, and how trustworthy is it
        right now? Resolves the address to its organization and live Privi Passport and returns allow/deny with
        reasons, plus a Privi-signed attestation (valid 60 min) you can cache. For chains, DeFi protocols, exchanges,
        stablecoin issuers and x402 facilitators. Free; send your organization key to log the check as evidence."""
        try:
            d = kya.check(address, min_score, min_grade, require_signed)
        except ValueError as e:
            return _result({"error": str(e)}, is_error=True)
        d.update(kya.attest(d))
        org = org_from(ctx)
        if org:
            try:
                e = ledger.record(org["org_id"], "privi-kya", "Privi Ledger", "decision",
                                  f"KYA {'allowed' if d['allow'] else 'denied'} {d['address']}" + (f" for: {purpose[:120]}" if purpose else ""),
                                  d["address"], "success" if d["allow"] else "blocked",
                                  {"min_score": min_score, "min_grade": min_grade, "reasons": d["reasons"],
                                   "current_score": d.get("current_score"), "passport_id": d.get("passport_id")})
                d["recorded_in_your_log"] = {"stream_id": "privi-kya", "entry_hash": e["entry_hash"]}
            except ValueError:
                pass
        return _result(d)

    @mcp.tool(title="KYA: challenge for a wallet", annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                                                               idempotentHint=False, openWorldHint=False))
    def kya_challenge(
        address: Annotated[str, Field(description="0x wallet address your agent controls")],
        ctx: Context,
    ) -> CallToolResult:
        """Step 1 of binding a wallet to your Privi Passport: get a message to sign with that wallet (EIP-191
        personal_sign). Valid 30 minutes. Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        try:
            return _result(kya.challenge(org["org_id"], org["name"], address))
        except ValueError as e:
            return _result({"error": str(e)}, is_error=True)

    @mcp.tool(title="KYA: bind a wallet", annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                                                      idempotentHint=True, openWorldHint=False))
    def kya_bind_wallet(
        address: Annotated[str, Field(description="0x wallet address")],
        ctx: Context,
        challenge_id: Annotated[str | None, Field(description="From kya_challenge")] = None,
        signature: Annotated[str | None, Field(description="65-byte hex signature of the challenge message by the wallet")] = None,
        stream_id: Annotated[str | None, Field(description="The agent (stream) that uses this wallet; omit for the whole organization")] = None,
        label: Annotated[str, Field(description="Friendly name, e.g. 'treasury-agent hot wallet'")] = "",
    ) -> CallToolResult:
        """Step 2: bind the wallet to your organization's Privi Passport so its transactions pass KYA checks. With a
        wallet signature the binding is *proven*; without one it is only *declared* (most checkers require proven).
        Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        if blocked := over_limit(org["org_id"]):
            return blocked
        try:
            sid = check_id(stream_id, "stream_id") if stream_id else "*"
            b = kya.bind(org["org_id"], address, sid, label, challenge_id, signature)
            ledger.record(org["org_id"], "privi-kya", "Privi Ledger", "other",
                          f"Wallet {b['address']} bound ({b['proof']}) to {sid}", b["address"], "success",
                          {"proof": b["proof"], "stream_id": sid})
            return _result({"bound": True, **b, "public_url": f"{public_url}/kya/{b['address']}",
                            "next": "Counterparties and facilitators call kya_check on this address; issue a Passport with passport_issue if you have not."})
        except (KYAError, ValueError) as e:
            return _result({"error": str(e)}, is_error=True)

    @mcp.tool(title="KYA: your wallets", annotations=READ_ONLY)
    def kya_wallets(ctx: Context) -> CallToolResult:
        """Wallets bound to your organization and how each was proven. Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        return _result({"org_id": org["org_id"], "wallets": kya.list_for(org["org_id"])})

    @mcp.tool(title="KYA: unbind a wallet", annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True,
                                                                        idempotentHint=True, openWorldHint=False))
    def kya_unbind_wallet(
        address: Annotated[str, Field(description="0x wallet address")],
        ctx: Context,
    ) -> CallToolResult:
        """Remove a wallet from your Passport (rotated or compromised key). KYA checks deny it immediately. Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        try:
            return _result(kya.unbind(org["org_id"], address))
        except (KYAError, ValueError) as e:
            return _result({"error": str(e)}, is_error=True)

    # ---------------- Privi Guard: wallets, transactions, approvals, escrow, registry ----------------

    def gerr(e: Exception) -> CallToolResult:
        return _result({"error": str(e)}, is_error=True)

    @mcp.tool(title="Guard: preview a transaction", annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
    async def guard_tx_preview(
        tx: Annotated[dict[str, Any], Field(description=TX_DESC)],
        simulate: Annotated[bool, Field(description="Also simulate over JSON-RPC (eth_call) and check whether spenders are contracts")] = True,
    ) -> CallToolResult:
        """Explain an EVM transaction in plain English before anyone signs it: decodes transfers, approvals, NFT operator
        grants, permits, admin and batched calls; flags drainer patterns (unlimited approvals, approvals to personal wallets,
        operator grants, burns, admin actions); simulates it; and checks counterparties with Privi KYA. Free; no key needed."""
        try:
            return _result(await anyio.to_thread.run_sync(lambda: guard.preview(tx, simulate)))
        except (ValueError, GuardError) as e:
            return gerr(e)

    @mcp.tool(title="Guard: set a wallet policy", annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                                                               idempotentHint=True, openWorldHint=False))
    def guard_policy_set(
        wallet: Annotated[str, Field(description="Agent wallet (0x), already bound to your organization with kya_bind_wallet")],
        owner_address: Annotated[str, Field(description="The human owner's wallet (0x). Only its signature can approve risky transactions")],
        max_tx_usd: Annotated[float, Field(description="Hard limit per transaction in USD", ge=0)],
        daily_cap_usd: Annotated[float, Field(description="Hard limit per rolling 24 hours in USD", ge=0)],
        ctx: Context,
        approval_above_usd: Annotated[float | None, Field(description="Transactions above this need the owner's signature (default: the lower of max_tx_usd and $100)", ge=0)] = None,
        allowed_chains: Annotated[list[int] | None, Field(description="Chain IDs the agent may use (default [8453] Base)")] = None,
        allowed_contracts: Annotated[list[str] | None, Field(description="If set, the only contracts/recipients the agent may call")] = None,
        block_unlimited_approvals: Annotated[bool, Field(description="Refuse unlimited token approvals outright")] = True,
        require_known_counterparty: Annotated[bool, Field(description="Ask the owner when the recipient or spender is not a KYA-verified agent")] = False,
        expires_at: Annotated[str | None, Field(description="ISO 8601 time after which the agent may not transact")] = None,
        active: Annotated[bool, Field(description="false pauses the wallet instantly (kill switch)")] = True,
    ) -> CallToolResult:
        """Set the rules an AI agent's wallet must obey: per-transaction and daily USD caps, chains, allowed contracts, an
        approval threshold above which the human owner must sign, expiry, and a pause switch. Every change is written to
        your tamper-evident log. Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        if blocked := over_limit(org["org_id"]):
            return blocked
        try:
            return _result(guard.set_policy(org["org_id"], wallet, {
                "owner_address": owner_address, "max_tx_usd": max_tx_usd, "daily_cap_usd": daily_cap_usd,
                "approval_above_usd": approval_above_usd, "allowed_chains": allowed_chains,
                "allowed_contracts": allowed_contracts, "block_unlimited_approvals": block_unlimited_approvals,
                "require_known_counterparty": require_known_counterparty, "expires_at": expires_at, "active": active}))
        except (ValueError, GuardError) as e:
            return gerr(e)

    @mcp.tool(title="Guard: your wallet policies", annotations=READ_ONLY)
    def guard_policies(ctx: Context) -> CallToolResult:
        """Your wallets' Guard policies with spend in the last 24 hours. Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        ps = guard.policies(org["org_id"])
        for p in ps:
            p["spent_24h_usd"] = format(guard.spent_24h(org["org_id"], p["wallet"]).normalize(), "f")
        return _result({"org_id": org["org_id"], "policies": ps})

    @mcp.tool(title="Guard: check before signing", annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                                                                idempotentHint=False, openWorldHint=True))
    async def guard_check_tx(
        tx: Annotated[dict[str, Any], Field(description=TX_DESC)],
        ctx: Context,
        usd_value: Annotated[float | None, Field(description="Your best estimate of the USD value moved or exposed", ge=0)] = None,
        approval_id: Annotated[str | None, Field(description="apr_... ID once the owner has approved this exact transaction")] = None,
        purpose: Annotated[str, Field(description="Why the agent is sending it (recorded in your log)")] = "",
        simulate: Annotated[bool, Field(description="Simulate over JSON-RPC")] = True,
    ) -> CallToolResult:
        """Call before your agent signs any transaction. Applies the wallet's Guard policy to a decoded, simulated and
        risk-scanned preview and returns verdict 'allow' (sign it; includes a Privi-signed Guard attestation and counts
        toward the daily cap), 'needs_approval' (returns an approval link for the human owner; call again with
        approval_id after they sign) or 'block' (do not sign), with reasons. Every decision is recorded in your
        tamper-evident log. Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        if blocked := over_limit(org["org_id"]):
            return blocked
        try:
            return _result(await anyio.to_thread.run_sync(
                lambda: guard.check(org["org_id"], tx, usd_value, approval_id, simulate, purpose)))
        except (ValueError, GuardError) as e:
            return gerr(e)

    @mcp.tool(title="Guard: approvals", annotations=READ_ONLY)
    def guard_approvals(
        ctx: Context,
        status: Annotated[str | None, Field(description="pending | approved | rejected | used; omit for all")] = None,
    ) -> CallToolResult:
        """Transactions waiting for (or decided by) the human owner. Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        return _result({"approvals": guard.approvals(org["org_id"], status)})

    @mcp.tool(title="Guard: owner decision", annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                                                          idempotentHint=True, openWorldHint=False))
    def guard_approve(
        approval_id: Annotated[str, Field(description="apr_... ID")],
        decision: Annotated[str, Field(description="approve or reject")],
        signature: Annotated[str, Field(description="Owner wallet's EIP-191 personal_sign of the approval message for this decision")],
    ) -> CallToolResult:
        """Record the human owner's decision on a pending transaction. Valid only with a signature from the policy's
        owner wallet over the exact approval message (see the approval's messages), so an agent cannot approve itself.
        Usually done on the approval page. No API key needed."""
        try:
            return _result(guard.decide(approval_id.strip(), decision.strip().lower(), signature.strip()))
        except (ValueError, GuardError) as e:
            return gerr(e)

    @mcp.tool(title="Guard: open an escrow", annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                                                          idempotentHint=False, openWorldHint=False))
    def guard_escrow_open(
        payee_org_id: Annotated[str, Field(description="org_id of the agent's company you are paying (on Privi Ledger)")],
        amount: Annotated[str, Field(description="Amount in token units, e.g. '250' for 250 USDC")],
        payer_wallet: Annotated[str, Field(description="Your agent wallet that pays (bound to your organization)")],
        payee_wallet: Annotated[str, Field(description="Wallet that receives on release")],
        terms: Annotated[str, Field(description="What must be delivered for release, in plain words")],
        ctx: Context,
        chain_id: Annotated[int, Field(description="Chain ID (default 8453 Base)")] = 8453,
        token: Annotated[str | None, Field(description="ERC-20 token address (default USDC on the chosen Base network)")] = None,
        decimals: Annotated[int, Field(description="Token decimals (USDC: 6)", ge=0, le=36)] = 6,
        deadline_hours: Annotated[float, Field(description="Hours for the payee to deliver", gt=0, le=2160)] = 72,
    ) -> CallToolResult:
        """Pay another company's AI agent through escrow: terms both sides see, recorded in both logs. Release and refund
        are authorized by the Privi Guard arbiter signature, which any EVM contract can verify with ecrecover
        (contracts/PriviEscrow.sol). Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        if blocked := over_limit(org["org_id"]):
            return blocked
        tok = token or {8453: "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
                        84532: "0x036CbD53842c5426634e7929541eC2318f3dCF7e"}.get(chain_id)
        if not tok:
            return gerr(ValueError("token is required on this chain"))
        try:
            return _result(guard.escrow_open(org["org_id"], payee_org_id.strip(), amount, payer_wallet, payee_wallet,
                                             chain_id, tok, decimals, terms, deadline_hours))
        except (ValueError, GuardError) as e:
            return gerr(e)

    @mcp.tool(title="Guard: act on an escrow", annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                                                            idempotentHint=False, openWorldHint=False))
    def guard_escrow_act(
        escrow_id: Annotated[str, Field(description="esc_... ID")],
        action: Annotated[str, Field(description="payee: accept | deliver | refund | dispute; payer: fund | release | refund (after deadline) | cancel (before acceptance) | dispute")],
        ctx: Context,
        note: Annotated[str, Field(description="Delivery proof, reason or comment (shared with the other side)")] = "",
        tx_hash: Annotated[str, Field(description="On-chain transaction hash, for 'fund'")] = "",
    ) -> CallToolResult:
        """Move an escrow forward. 'release' (payer) and 'refund' return an arbiter-signed authorization the escrow
        contract accepts. Every step is recorded in both companies' logs. Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        try:
            return _result(guard.escrow_act(org["org_id"], escrow_id.strip(), action.strip().lower(), note, tx_hash))
        except (ValueError, GuardError) as e:
            return gerr(e)

    @mcp.tool(title="Guard: your escrows", annotations=READ_ONLY)
    def guard_escrows(ctx: Context) -> CallToolResult:
        """Escrows where your organization pays or is paid, with terms and history. Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        return _result({"org_id": org["org_id"], "escrows": guard.escrow_list(org["org_id"]), "arbiter": guard.arbiter.address})

    @mcp.tool(title="Guard: escrow status", annotations=READ_ONLY)
    def guard_escrow_status(escrow_id: Annotated[str, Field(description="esc_... ID")]) -> CallToolResult:
        """Public status of an escrow: parties, amount, deadline, history and any arbiter authorization. Terms text is
        not revealed. Free."""
        s = guard.escrow_public(escrow_id.strip())
        return _result(s) if s else gerr(GuardError("no such escrow"))

    @mcp.tool(title="Registry: list your agent", annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                                                              idempotentHint=False, openWorldHint=True))
    async def registry_register(
        stream_id: Annotated[str, Field(description="The agent's stream ID")],
        name: Annotated[str, Field(description="Public name of the agent")],
        ctx: Context,
        description: Annotated[str, Field(description="What it does, in a sentence or two")] = "",
        endpoint: Annotated[str, Field(description="Where other agents reach it (MCP or A2A URL)")] = "",
        capabilities: Annotated[list[str] | None, Field(description="Short capability tags, e.g. ['payments', 'invoicing']")] = None,
    ) -> CallToolResult:
        """Publish your agent in the Privi Agent Registry so any dApp, wallet or agent can look it up by ID, wallet or
        capability. The record lists its bound wallets and current Passport; each version is anchored on the Privi
        chain. Calling again publishes a new version. Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        if blocked := over_limit(org["org_id"]):
            return blocked
        try:
            sid = check_id(stream_id, "stream_id")
        except ValueError as e:
            return gerr(e)
        rec = guard.registry_build(org, sid, name, description, endpoint, capabilities or [])
        h = passport_hash(rec)
        att = await _anchor_hash(h, f"privi agent registry {rec['agent_id']} v{rec['record_version']}")
        att["signature"] = passports.sign(h)
        att["key_id"] = passports.key_id
        guard.registry_save(rec, h, att)
        return _result({"registered": True, **guard.registry_get(rec["agent_id"])})

    @mcp.tool(title="Registry: look up agents", annotations=READ_ONLY)
    def registry_lookup(
        agent_id: Annotated[str | None, Field(description="agt_... ID")] = None,
        address: Annotated[str | None, Field(description="Find the agent that uses this wallet")] = None,
        query: Annotated[str, Field(description="Search names, descriptions and organizations")] = "",
        capability: Annotated[str, Field(description="Only agents with this capability tag")] = "",
        limit: Annotated[int, Field(ge=1, le=100)] = 25,
    ) -> CallToolResult:
        """Find AI agents in the Privi Agent Registry by ID, wallet, name or capability: who operates them, their wallets,
        endpoint and Passport. Free; no key needed."""
        if agent_id:
            r = guard.registry_get(agent_id.strip())
            return _result({"agents": [r] if r else [], "total_registered": guard.registry_count()})
        try:
            return _result({"agents": guard.registry_search(query, address or "", capability, limit),
                            "total_registered": guard.registry_count()})
        except ValueError as e:
            return gerr(e)

    @mcp.tool(title="Registry: verify a record", annotations=READ_ONLY)
    async def registry_verify(agent_id: Annotated[str, Field(description="agt_... ID")]) -> CallToolResult:
        """Check a registry record: content hash, Privi signature and anchor on the Privi chain, plus the agent's live
        Passport status. Free."""
        r = guard.registry_get(agent_id.strip())
        if not r:
            return _result({"valid": False, "reason": "no such agent"})
        h = passport_hash(r["agent"])
        att = r["attestation"]
        out = {"agent_id": agent_id, "record_hash": h, "hash_matches": h == r["record_hash"],
               "signature_valid": passports.signature_ok(h, att.get("signature", "")), "revoked": r["revoked"],
               "anchored": bool(att.get("anchored"))}
        out.update(await _chain_check(att, h))
        pid = r["agent"].get("passport_id")
        if pid and (rec := passports.get(pid)):
            v = passports.check(rec)
            out["passport"] = {"passport_id": pid, "valid": v["valid"], "live_score": (v.get("live") or {}).get("score")}
        out["valid"] = out["hash_matches"] and out["signature_valid"] and not r["revoked"] and out.get("onchain_verified") is not False
        return _result(out)

    @mcp.tool(title="Registry: remove your agent", annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True,
                                                                                idempotentHint=True, openWorldHint=False))
    def registry_remove(agent_id: Annotated[str, Field(description="agt_... ID")], ctx: Context) -> CallToolResult:
        """Remove your agent from the public registry (retired or compromised). Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        try:
            return _result(guard.registry_revoke(org["org_id"], agent_id.strip()))
        except GuardError as e:
            return gerr(e)

    # ---------------- Guard http ----------------

    @mcp.custom_route("/guard/approvals/{approval_id}.json", methods=["GET"], include_in_schema=False)
    async def approval_json(request: Request) -> JSONResponse:
        a = guard.approval_public(request.path_params["approval_id"])
        return JSONResponse(a or {"error": "no such approval"}, status_code=200 if a else 404,
                            headers={"Cache-Control": "no-store"})

    @mcp.custom_route("/guard/approvals/{approval_id}", methods=["GET"], include_in_schema=False)
    async def approval_page(_: Request) -> Response:
        return Response(APPROVAL_PAGE, media_type="text/html", headers={"Cache-Control": "no-store"})

    @mcp.custom_route("/guard/approvals/{approval_id}/decide", methods=["POST"], include_in_schema=False)
    async def approval_decide(request: Request) -> JSONResponse:
        try:
            body = await request.json()
            r = guard.decide(request.path_params["approval_id"], str(body.get("decision", "")).lower(), str(body.get("signature", "")))
        except (ValueError, GuardError, AttributeError) as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        return JSONResponse(r)

    @mcp.custom_route("/registry/{agent_id}", methods=["GET"], include_in_schema=False)
    async def registry_json(request: Request) -> JSONResponse:
        r = guard.registry_get(request.path_params["agent_id"])
        return JSONResponse(r or {"error": "not found"}, status_code=200 if r else 404,
                            headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "no-store"})

    @mcp.custom_route("/registry", methods=["GET"], include_in_schema=False)
    async def registry_index(request: Request) -> JSONResponse:
        q = request.query_params
        try:
            agents = guard.registry_search(q.get("q", ""), q.get("address", ""), q.get("capability", ""), min(int(q.get("limit", 50)), 100))
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        return JSONResponse({"agents": agents, "total_registered": guard.registry_count()},
                            headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "no-store"})

    @mcp.custom_route("/.well-known/privi-guard.json", methods=["GET"], include_in_schema=False)
    async def guard_wellknown(_: Request) -> JSONResponse:
        return JSONResponse({"service": "Privi Guard", "version": __version__, "arbiter_address": guard.arbiter.address,
                             "escrow_contract": guard.escrow_contract, "attestation_issuer": passports.issuer(),
                             "simulation_chains": sorted(guard.rpc.urls) if guard.rpc else [],
                             "chain_names": CHAIN_NAMES, "mcp": f"{public_url}/mcp",
                             "tools": ["guard_tx_preview", "guard_check_tx", "guard_policy_set", "guard_approve",
                                       "guard_escrow_open", "guard_escrow_act", "registry_register", "registry_lookup"],
                             "registry": f"{public_url}/registry"},
                            headers={"Access-Control-Allow-Origin": "*"})

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

    @mcp.custom_route("/reports/{report_id}.pdf", methods=["GET"], include_in_schema=False)
    async def report_pdf(request: Request):
        org = ledger.org_for_key(_bearer(request.headers))
        if not org:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        rid = request.path_params["report_id"]
        rec = reports.get(rid, org["org_id"])
        if not rec:
            return JSONResponse({"error": "not found"}, status_code=404)
        pdf = render_pdf(rec["body"], rec["attestation"], rid)
        return Response(pdf, media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{rid}.pdf"'})

    @mcp.custom_route("/kya/{address}", methods=["GET"], include_in_schema=False)
    async def kya_json(request: Request) -> JSONResponse:
        q = request.query_params
        try:
            d = kya.check(request.path_params["address"], int(q.get("min_score", 550)), q.get("min_grade"),
                          q.get("require_signed", "true").lower() != "false")
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        d.update(kya.attest(d))
        return JSONResponse(d, headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "no-store"})

    @mcp.custom_route("/kya/{address}/badge.svg", methods=["GET"], include_in_schema=False)
    async def kya_badge(request: Request) -> Response:
        try:
            d = kya.check(request.path_params["address"], 0, None, False)
        except ValueError:
            d = {"known": False}
        if not d.get("known") or not d.get("passport_valid"):
            return Response(badge_svg("E", 0, expired=True).replace("Privi Trust", "Privi KYA"), media_type="image/svg+xml")
        return Response(badge_svg(d["current_grade"], d["current_score"]).replace("Privi Trust", "Privi KYA"),
                        media_type="image/svg+xml", headers={"Cache-Control": "max-age=300"})

    @mcp.custom_route("/passports/{passport_id}", methods=["GET"], include_in_schema=False)
    async def passport_json(request: Request) -> JSONResponse:
        rec = passports.get(request.path_params["passport_id"])
        if not rec:
            return JSONResponse({"error": "not found"}, status_code=404)
        v = passports.check(rec)
        return JSONResponse({"passport": rec["body"], "signature": rec["signature"], "body_hash": rec["body_hash"],
                             "attestation": rec["attestation"], "verification": v, "issuer": passports.issuer()},
                            headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "no-store"})

    @mcp.custom_route("/passports/{passport_id}/badge.svg", methods=["GET"], include_in_schema=False)
    async def passport_badge(request: Request) -> Response:
        rec = passports.get(request.path_params["passport_id"])
        if not rec:
            return Response(badge_svg("E", 0, expired=True), media_type="image/svg+xml", status_code=404)
        v = passports.check(rec)
        live = v.get("live") or {}
        return Response(badge_svg(live.get("grade", rec["grade"]), live.get("score", rec["score"]),
                                  revoked=v["revoked"], expired=v["expired"] or not v["valid"]),
                        media_type="image/svg+xml", headers={"Cache-Control": "max-age=300"})

    @mcp.custom_route("/.well-known/privi-passport.json", methods=["GET"], include_in_schema=False)
    async def passport_issuer(_: Request) -> JSONResponse:
        return JSONResponse({**passports.issuer(), "version": PASSPORT_VERSION_HTTP,
                             "verify": {"mcp": f"{public_url}/mcp", "tools": ["passport_verify", "passport_gate", "kya_check"]},
                             "kya": f"{public_url}/kya/{{address}}",
                             "lookup": f"{public_url}/passports/{{passport_id}}"},
                            headers={"Access-Control-Allow-Origin": "*"})

    @mcp.custom_route("/.well-known/glama.json", methods=["GET"], include_in_schema=False)
    async def glama(_: Request) -> JSONResponse:
        return JSONResponse({"$schema": "https://glama.ai/mcp/schemas/server.json",
                             "maintainers": ["canoydario847-cloud"]})

    @mcp.custom_route("/health", methods=["GET"], include_in_schema=False)
    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"ok": True, "service": "privi-ledger", "version": __version__})

    @mcp.custom_route("/", methods=["GET"], include_in_schema=False)
    async def index(_: Request) -> JSONResponse:
        return JSONResponse({"service": "Privi Ledger MCP", "mcp_endpoint": "/mcp",
                             "payments": "x402 (USDC on Base)" if settings.payments_enabled else "disabled",
                             "source": SOURCE})

    return mcp


def bootstrap(ledger: Ledger) -> None:
    """Optional first-customer setup: LEDGER_BOOTSTRAP_ORG_NAME + LEDGER_BOOTSTRAP_ORG_KEY create that
    organization (idempotent); LEDGER_IMPORT_FILE loads a JSON log into one of its streams if empty."""
    name, key = os.getenv("LEDGER_BOOTSTRAP_ORG_NAME", ""), os.getenv("LEDGER_BOOTSTRAP_ORG_KEY", "")
    if not (name and key):
        return
    try:
        org = ledger.ensure_org(name, key)
        print(f"privi-ledger: organization ready: {org['name']} ({org['org_id']})", flush=True)
        path = os.getenv("LEDGER_IMPORT_FILE", "")
        if path:
            data = json.loads(open(path, encoding="utf-8").read())
            n = ledger.import_entries(org["org_id"], data["stream_id"], data["entries"])
            print(f"privi-ledger: imported {n} entries into {data['stream_id']}" if n else
                  f"privi-ledger: {data['stream_id']} already has entries; import skipped", flush=True)
    except Exception as e:
        print(f"privi-ledger: bootstrap error: {e}", flush=True)


def first_report(mcp: MCPServer, ledger: Ledger, delay_s: float = 75.0) -> None:
    """LEDGER_BOOTSTRAP_REPORT=1: once, issue a sealed compliance report for the bootstrap organization."""
    key = os.getenv("LEDGER_BOOTSTRAP_ORG_KEY", "")
    org = ledger.org_for_key(key)
    if not org or ledger._db.execute("SELECT 1 FROM reports WHERE org_id=?", (org["org_id"],)).fetchone():
        return

    def run() -> None:
        time.sleep(delay_s)  # let the checkpoint loop anchor the logs first
        try:
            from mcp import Client

            async def call():
                os.environ["LEDGER_LOCAL_ORG_KEY"] = key   # in-process call has no HTTP headers
                async with Client(mcp) as c:
                    return (await c.call_tool("ledger_compliance_report", {})).structured_content
            r = anyio.run(call)
            a = r["attestation"]
            print(f"privi-ledger: first compliance report {r['report_id']} for {org['name']}: "
                  f"status={r['report']['status']} hash={a['report_hash']} anchored={a.get('anchored')} "
                  f"tx={a.get('tx_hash')} block={a.get('block_number')}", flush=True)
        except Exception as e:
            print(f"privi-ledger: first report error: {e}", flush=True)
        finally:
            os.environ.pop("LEDGER_LOCAL_ORG_KEY", None)

    threading.Thread(target=run, daemon=True).start()


def first_passport(mcp: MCPServer, ledger: Ledger, delay_s: float = 90.0) -> None:
    """LEDGER_BOOTSTRAP_PASSPORT=1: once, issue an organization passport for the bootstrap organization."""
    key = os.getenv("LEDGER_BOOTSTRAP_ORG_KEY", "")
    org = ledger.org_for_key(key)
    if not org or ledger._db.execute("SELECT 1 FROM passports WHERE org_id=?", (org["org_id"],)).fetchone():
        return

    def run() -> None:
        time.sleep(delay_s)
        try:
            from mcp import Client

            async def call():
                os.environ["LEDGER_LOCAL_ORG_KEY"] = key
                async with Client(mcp) as c:
                    return (await c.call_tool("passport_issue", {})).structured_content
            r = anyio.run(call)
            a = r.get("attestation", {})
            print(f"privi-ledger: first passport {r.get('passport_id')} for {org['name']}: grade={r.get('grade')} "
                  f"score={r.get('score')} anchored={a.get('anchored')} tx={a.get('tx_hash')} block={a.get('block_number')} "
                  f"url={r.get('public_url')}", flush=True)
        except Exception as e:
            print(f"privi-ledger: first passport error: {e}", flush=True)
        finally:
            os.environ.pop("LEDGER_LOCAL_ORG_KEY", None)

    threading.Thread(target=run, daemon=True).start()


def main() -> None:
    p = argparse.ArgumentParser(description="Privi Ledger MCP server")
    p.add_argument("--stdio", action="store_true", help="run over stdio instead of HTTP")
    p.add_argument("--host", default=os.getenv("HOST", "0.0.0.0"))
    p.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000")))
    args = p.parse_args()
    settings = Settings.from_env()
    ledger = Ledger(settings.db_path)
    bootstrap(ledger)
    mcp = build_server(settings, ledger)
    key = os.getenv("LEDGER_ANCHOR_KEY", "")
    if key:
        client = HttpAnchorClient(os.getenv("LEDGER_ANCHOR_URL", DEFAULT_ANCHOR_URL), key)
        cps = Checkpoints(ledger._db, ledger._lock)
        start_loop(lambda: cps.run_once(ledger.heads(), client, "privi-ledger"),
                   float(os.getenv("LEDGER_ANCHOR_INTERVAL", "300")), "privi-ledger")
    if os.getenv("LEDGER_BOOTSTRAP_REPORT") == "1":
        first_report(mcp, ledger)
    if os.getenv("LEDGER_BOOTSTRAP_PASSPORT") == "1":
        first_passport(mcp, ledger)
    if args.stdio:
        mcp.run("stdio")
        return
    import uvicorn
    uvicorn.run(mcp.streamable_http_app(host=args.host, stateless_http=True, json_response=True),
                host=args.host, port=args.port)


if __name__ == "__main__":
    main()
