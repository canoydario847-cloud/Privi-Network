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
from .mandate import MandateError, Mandates
from .fortress import Fortress, FortressError
from .passport import PASSPORT_VERSION as PASSPORT_VERSION_HTTP, PassportError, Passports, badge_svg, body_hash as passport_hash

DEFAULT_ANCHOR_URL = "https://privi-anchor.onrender.com/mcp"

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

Defense-grade controls (Privi Fortress): every attestation is co-signed with ML-DSA-87 (FIPS 204,
CNSA 2.0) as well as Ed25519; all entries form an RFC 9162 transparency log (ledger_tree_head,
ledger_inclusion_proof, ledger_consistency_proof, free); sensitive actions can require two-person
integrity (fortress_tpi_policy / _request, approved by officers' wallet signatures); and
ledger_evidence_bundle exports a package verifiable fully offline.

Spending on behalf of a person: ask them for a Privi Mandate. mandate_create drafts the terms
(budget, per-payment cap, allowed payees, expiry) and returns a sign_url for the human; once
they sign with their wallet, call mandate_spend before each payment. Merchants and facilitators
call mandate_check (free) to confirm a human authorized the payment.

Before trusting or paying another agent, ask for its Privi Passport (a signed, on-chain-anchored
trust credential scored 0-1000 from its verified history) and check it with passport_verify or
passport_gate, both free. Issue your own with passport_issue so counterparties can trust you.

Dealings with another company on Privi (payments, data transfers, deliveries, agreements):
use Privi Handshake (ledger_handshake_offer / _inbox / _accept / _reject) so both companies
hold matching records sealed on the Privi chain; ledger_handshake_verify is a free public check.

Privi is built by Dario Canoy (Privi World Co, Port Huron, Michigan). For the other
Privi tools, pilots, partnerships, government or manufacturing work, grants or
investment, see https://privi-discovery.onrender.com/llms.txt or the A2A card at
https://privi-discovery.onrender.com/.well-known/agent.json."""

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)


def _result(data: dict[str, Any], is_error: bool = False) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(data))],
                          structured_content=data, is_error=is_error)


def _bearer(headers) -> str:
    auth = (headers or {}).get("authorization", "")
    return auth[7:].strip() if auth.lower().startswith("bearer ") else ""


def build_server(settings: Settings | None = None, ledger: Ledger | None = None,
                 facilitator: Facilitator | None = None, anchor_client: AnchorClient | None = None) -> MCPServer:
    settings = settings or Settings.from_env()
    ledger = ledger or Ledger(settings.db_path)
    _pub = os.getenv("LEDGER_PUBLIC_URL", "https://privi-ledger.onrender.com").rstrip("/")
    paywall = Paywall(settings, facilitator, service={
        "url": f"{_pub}/mcp", "serviceName": "Privi Ledger",
        "tags": ["audit", "compliance", "ai-agents", "trust", "post-quantum"],
        "iconUrl": "https://privi-discovery.onrender.com/icon.svg"},
        discovery={"ledger_audit_stream": {
            "inputSchema": {"type": "object", "properties": {
                "org_id": {"type": "string", "description": "Organization ID, e.g. org_1a2b3c4d5e6f7a8b"},
                "stream_id": {"type": "string", "description": "Stream ID, usually the agent's name"}},
                "required": ["org_id", "stream_id"]},
            "example": {"org_id": "org_ecaa55d291af2c57", "stream_id": "claude-build-2026-10-19"},
            "output": {"found": True, "intact": True, "entry_count": 16, "failures": 0,
                       "head_hash": "<64-hex>", "onchain_checkpoint": {"anchored": True}}}})
    checkpoints = Checkpoints(ledger._db, ledger._lock)
    anchor_url = os.getenv("LEDGER_ANCHOR_URL", DEFAULT_ANCHOR_URL)
    if anchor_client is None and os.getenv("LEDGER_ANCHOR_KEY"):
        anchor_client = HttpAnchorClient(anchor_url, os.environ["LEDGER_ANCHOR_KEY"])
    reports = ReportStore(ledger._db, ledger._lock)
    handshakes = Handshakes(ledger, ledger._db, ledger._lock)
    plans = Plans(ledger)
    gov = GovAIInventory(ledger)
    pqc = QuantumReady(ledger)
    public_url = os.getenv("LEDGER_PUBLIC_URL", "https://privi-ledger.onrender.com").rstrip("/")

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
    mandates = Mandates(ledger._db, ledger._lock, passports, public_url)
    fortress = Fortress(ledger, passports, public_url, os.getenv("LEDGER_PQ_SIGNING_KEY", ""))
    mcp.privi_fortress = fortress  # used by the tree-head anchoring loop in main()

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
                "mandate_create": "organization API key", "mandate_check": "free", "mandate_spend": "organization API key",
                "mandate_get": "free", "mandate_list": "organization API key", "mandate_revoke": "organization API key",
                "fortress_keys": "free", "ledger_tree_head": "free", "ledger_inclusion_proof": "free",
                "ledger_consistency_proof": "free", "fortress_tpi_status": "free",
                "fortress_tpi_policy": "organization API key", "fortress_tpi_request": "organization API key",
                "fortress_tpi_execute": "organization API key", "fortress_tpi_list": "organization API key",
                "ledger_evidence_bundle": "organization API key",
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
        att["post_quantum"] = fortress.cosign(h, "compliance_report")
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
        out.update(fortress.check_cosign(h))
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
            pq = fortress.cosign(h, "passport")
            att = await _anchor_hash(h, f"privi passport {org['org_id']}")
            passports.save(body, sig, att)
            try:
                ledger.record(org["org_id"], "privi-passport", "Privi Ledger", "other",
                              f"Passport {body['passport_id']} issued: {body['grade']} ({body['score']}/1000) for {body['subject']['stream_id']}",
                              body["passport_id"], "success", {"score": body["score"], "grade": body["grade"], "hash": h})
            except ValueError:
                pass
            return {"passport_id": body["passport_id"], "score": body["score"], "grade": body["grade"],
                    "passport": body, "body_hash": h, "signature": sig, "post_quantum": pq, "attestation": att,
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
        v.update(fortress.check_cosign(rec["body_hash"]))
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
        d["ml_dsa_87_signature"] = fortress.pq_sign(d["attestation_hash"])
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

    # ---------------- Privi Mandates: human-authorized agent spending ----------------

    def _mandate_log(m: dict, action_type: str, summary: str, outcome: str = "success", details: dict | None = None):
        try:
            return ledger.record(m["org_id"], m["stream_id"], "Privi Ledger", action_type, summary, m["mandate_id"],
                                 outcome, details or {})
        except ValueError:
            return None

    async def _activate_mandate(mandate_id: str, signature: str) -> dict:
        m = mandates.activate(mandate_id, signature)
        att = await _anchor_hash(m["terms_hash"], f"privi mandate {mandate_id}")
        mandates.set_anchor(mandate_id, att)
        fortress.cosign(m["terms_hash"], "mandate")
        _mandate_log(m, "approval", f"Human {m['principal']} signed mandate {mandate_id}: up to {m['max_total_usdc']} USDC "
                     f"until {m['expires_at']}", details={"terms_hash": m["terms_hash"], "anchored": att.get("anchored")})
        return mandates.public(mandate_id)

    @mcp.tool(title="Create a spending mandate", annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                                                             idempotentHint=False, openWorldHint=False))
    def mandate_create(
        stream_id: Annotated[str, Field(description="The agent (stream) that will spend, e.g. 'shopping-agent'")],
        principal_wallet: Annotated[str, Field(description="0x wallet of the human who authorizes the spending")],
        max_total_usdc: Annotated[str, Field(description="Total budget in USDC, e.g. '250'")],
        purpose: Annotated[str, Field(description="What the agent may spend on, in plain words")],
        ctx: Context,
        max_per_payment_usdc: Annotated[str | None, Field(description="Cap per payment; defaults to the total")] = None,
        payees: Annotated[list[str] | None, Field(description="Allowed payees (0x addresses or domains); omit for any")] = None,
        days: Annotated[int, Field(description="Days until the mandate expires (1-365)", ge=1, le=365)] = 30,
        agent_wallet: Annotated[str | None, Field(description="0x wallet the agent pays from (optional)")] = None,
    ) -> CallToolResult:
        """Draft a Privi Mandate: the human's signed permission for your agent to spend, with a budget, per-payment cap,
        allowed payees and expiry. Returns sign_url: send it to the human, who reads the plain-English terms and signs
        once with their wallet (free, no transaction). Nothing can be spent until they sign. Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        try:
            sid = check_id(stream_id, "stream_id")
            m = mandates.draft(org, sid, principal_wallet, max_total_usdc, max_per_payment_usdc, payees, days,
                               purpose, agent_wallet)
        except (MandateError, ValueError) as e:
            return _result({"error": str(e)}, is_error=True)
        return _result({**m, "next": f"Send the human this link to review and sign: {m['sign_url']}"})

    @mcp.tool(title="Check a payment against a mandate", annotations=READ_ONLY)
    def mandate_check(
        mandate_id: Annotated[str, Field(description="mdt_... ID the agent presented")],
        amount_usdc: Annotated[str, Field(description="Payment amount in USDC")],
        payee: Annotated[str, Field(description="Who is being paid: your 0x address or domain")],
    ) -> CallToolResult:
        """For merchants, payment facilitators and counterparties: did a human authorize this AI agent to pay you this
        amount? Verifies the human's wallet signature, status, expiry, per-payment cap, remaining budget and payee list,
        and returns allow/deny with reasons plus a Privi-signed attestation. Free; no key needed."""
        try:
            d = mandates.check(mandate_id, amount_usdc, payee)
            d["ml_dsa_87_signature"] = fortress.pq_sign(d["attestation_hash"])
            return _result(d)
        except (MandateError, ValueError) as e:
            return _result({"error": str(e)}, is_error=True)

    @mcp.tool(title="Spend under a mandate", annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                                                         idempotentHint=False, openWorldHint=False))
    def mandate_spend(
        mandate_id: Annotated[str, Field(description="mdt_... ID")],
        amount_usdc: Annotated[str, Field(description="Payment amount in USDC")],
        payee: Annotated[str, Field(description="Who is being paid: 0x address or domain")],
        ctx: Context,
        reference: Annotated[str, Field(description="Order, invoice or transaction reference")] = "",
    ) -> CallToolResult:
        """Call before each payment: checks the mandate and, if allowed, deducts the amount from the budget and records the
        payment in the agent's tamper-evident log. Refused payments are logged as blocked. Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        if blocked := over_limit(org["org_id"]):
            return blocked
        try:
            r = mandates.spend(mandate_id.strip(), org["org_id"], amount_usdc, payee, reference)
        except (MandateError, ValueError) as e:
            m = mandates._row(mandate_id)
            if m and m["org_id"] == org["org_id"]:
                _mandate_log(m, "payment", f"Blocked payment of {amount_usdc} USDC to {payee}: {e}", "blocked",
                             {"mandate_id": mandate_id, "reference": reference})
            return _result({"allow": False, "error": str(e)}, is_error=True)
        m = mandates._row(r["mandate_id"])
        e = _mandate_log(m, "payment", f"Paid {r['amount_usdc']} USDC to {r['payee']} under mandate {r['mandate_id']}",
                         details={"spend_id": r["spend_id"], "reference": reference, "remaining_usdc": r["remaining_usdc"]})
        if e:
            mandates.attach_entry(r["spend_id"], e["entry_hash"])
            r["entry_hash"] = e["entry_hash"]
        return _result({"allow": True, **r})

    @mcp.tool(title="Get a mandate", annotations=READ_ONLY)
    def mandate_get(mandate_id: Annotated[str, Field(description="mdt_... ID")]) -> CallToolResult:
        """Public view of a mandate: terms, status, the human's signature, spent and remaining budget, and recent spends. Free."""
        try:
            return _result(mandates.public(mandate_id))
        except MandateError as e:
            return _result({"error": str(e)}, is_error=True)

    @mcp.tool(title="List your mandates", annotations=READ_ONLY)
    def mandate_list(ctx: Context) -> CallToolResult:
        """Your organization's mandates with status and remaining budget. Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        return _result({"org_id": org["org_id"], "mandates": mandates.list_for(org["org_id"])})

    @mcp.tool(title="Revoke a mandate", annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True,
                                                                    idempotentHint=True, openWorldHint=False))
    def mandate_revoke(
        mandate_id: Annotated[str, Field(description="mdt_... ID")],
        ctx: Context,
        reason: Annotated[str, Field(description="Why")] = "",
    ) -> CallToolResult:
        """Stop an agent from spending under a mandate (the human can also revoke from the sign_url page). Requires the
        organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        try:
            m = mandates.revoke(mandate_id.strip(), reason, org_id=org["org_id"])
            _mandate_log(mandates._row(mandate_id.strip()), "approval", f"Mandate {mandate_id} revoked by the organization",
                         details={"reason": reason})
            return _result(m)
        except MandateError as e:
            return _result({"error": str(e)}, is_error=True)

    # ---------------- Privi Fortress: defense-grade controls ----------------

    @mcp.tool(title="Fortress keys", annotations=READ_ONLY)
    def fortress_keys() -> dict[str, Any]:
        """Privi's public signing keys: Ed25519 and ML-DSA-87 (NIST FIPS 204, CNSA 2.0 post-quantum). Pin these to
        verify Privi signatures offline. Free."""
        return fortress.keys()

    @mcp.tool(title="Signed tree head", annotations=READ_ONLY)
    def ledger_tree_head() -> CallToolResult:
        """The latest signed tree head of Privi's transparency log: an RFC 9162 Merkle root over every entry ever
        recorded, signed with Ed25519 and ML-DSA-87, and periodically anchored on the Privi chain. Free."""
        return _result({**fortress.tree_head(), "recent": fortress.history(10)})

    @mcp.tool(title="Inclusion proof", annotations=READ_ONLY)
    def ledger_inclusion_proof(
        entry_hash: Annotated[str, Field(description="64-hex entry_hash (an action receipt)")],
        tree_size: Annotated[int | None, Field(description="Prove against this signed tree head size; omit for latest")] = None,
    ) -> CallToolResult:
        """Merkle audit path proving an entry is in Privi's append-only transparency log (RFC 9162). Verifiable offline
        against the signed tree head. Reveals no entry contents. Free."""
        try:
            return _result(fortress.inclusion(entry_hash, tree_size))
        except FortressError as e:
            return _result({"error": str(e)}, is_error=True)

    @mcp.tool(title="Consistency proof", annotations=READ_ONLY)
    def ledger_consistency_proof(
        first: Annotated[int, Field(description="Older signed tree size", ge=1)],
        second: Annotated[int | None, Field(description="Newer signed tree size; omit for latest")] = None,
    ) -> CallToolResult:
        """Proof that Privi's log only grew between two signed tree heads: nothing recorded earlier was edited, removed
        or reordered (RFC 9162). Free."""
        try:
            return _result(fortress.consistency(first, second))
        except FortressError as e:
            return _result({"error": str(e)}, is_error=True)

    @mcp.tool(title="Set a two-person policy", annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                                                           idempotentHint=True, openWorldHint=False))
    def fortress_tpi_policy(
        name: Annotated[str, Field(description="Policy name, e.g. 'treasury-transfers'")],
        officer_wallets: Annotated[list[str], Field(description="0x wallets of the officers who may approve (at least 2)")],
        required: Annotated[int, Field(description="Approvals needed (2..number of officers)", ge=2)],
        ctx: Context,
    ) -> CallToolResult:
        """Define a Two-Person Integrity policy: which officers can approve, and how many distinct approvals an action
        needs. Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        try:
            p = fortress.tpi_policy(org["org_id"], check_id(name, "name"), officer_wallets, required)
            ledger.record(org["org_id"], "privi-fortress", "Privi Ledger", "other",
                          f"Two-person policy '{p['policy']}' set: {p['required']} of {len(p['officers'])} officers",
                          p["policy"], "success", p)
            return _result(p)
        except (FortressError, ValueError) as e:
            return _result({"error": str(e)}, is_error=True)

    @mcp.tool(title="Request two-person approval", annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                                                               idempotentHint=False, openWorldHint=False))
    def fortress_tpi_request(
        policy: Annotated[str, Field(description="Policy name")],
        stream_id: Annotated[str, Field(description="The agent asking")],
        summary: Annotated[str, Field(description="Exactly what will be done, in plain words")],
        ctx: Context,
        details: Annotated[dict[str, Any] | None, Field(description="Exact parameters; their hash is what officers sign")] = None,
        hours: Annotated[int, Field(description="Hours until the request expires (1-168)", ge=1, le=168)] = 24,
    ) -> CallToolResult:
        """Ask officers to authorize a sensitive action under a two-person policy. Returns approve_url for the officers;
        each signs with their wallet. Do not act until fortress_tpi_status shows 'authorized', then call
        fortress_tpi_execute. Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        if blocked := over_limit(org["org_id"]):
            return blocked
        try:
            sid = check_id(stream_id, "stream_id")
            r = fortress.tpi_request(org["org_id"], policy, sid, summary, details, hours)
            ledger.record(org["org_id"], sid, "Privi Ledger", "approval", f"Two-person approval requested: {r['summary']}",
                          r["request_id"], "pending", {"policy": policy, "details_hash": r["details_hash"]})
            return _result({**r, "next": f"Send officers this link: {r['approve_url']}"})
        except (FortressError, ValueError) as e:
            return _result({"error": str(e)}, is_error=True)

    @mcp.tool(title="Two-person status", annotations=READ_ONLY)
    def fortress_tpi_status(request_id: Annotated[str, Field(description="tpi_... ID")]) -> CallToolResult:
        """Status of a two-person request (pending, authorized, vetoed, expired, executed) and who approved. Free."""
        try:
            return _result(fortress.tpi_public(request_id))
        except FortressError as e:
            return _result({"error": str(e)}, is_error=True)

    @mcp.tool(title="Execute an authorized action", annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                                                                idempotentHint=False, openWorldHint=False))
    def fortress_tpi_execute(
        request_id: Annotated[str, Field(description="tpi_... ID")],
        ctx: Context,
    ) -> CallToolResult:
        """Consume a two-person authorization right before performing the action. Single use; refused unless authorized.
        Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        try:
            r = fortress.tpi_execute(request_id.strip(), org["org_id"])
            ledger.record(org["org_id"], r["stream_id"], "Privi Ledger", "approval",
                          f"Two-person authorization used: {r['summary']}", r["request_id"], "success",
                          {"approved_by": [a["officer"] for a in r["approvals"]]})
            return _result(r)
        except FortressError as e:
            return _result({"error": str(e)}, is_error=True)

    @mcp.tool(title="List two-person requests", annotations=READ_ONLY)
    def fortress_tpi_list(ctx: Context) -> CallToolResult:
        """Your organization's two-person requests. Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        return _result({"org_id": org["org_id"], "requests": fortress.tpi_list(org["org_id"])})

    @mcp.tool(title="Evidence bundle", annotations=READ_ONLY)
    def ledger_evidence_bundle(
        stream_id: Annotated[str, Field(description="Stream to export")],
        ctx: Context,
    ) -> CallToolResult:
        """Export a self-contained evidence package for auditors, courts or air-gapped systems: every entry, the hash
        chain, an RFC 9162 inclusion proof, the signed tree head, on-chain checkpoint and Privi's keys, signed with
        Ed25519 and ML-DSA-87. Verify offline with verify_bundle.py (GET /tools/verify_bundle.py). Requires the
        organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        try:
            return _result(fortress.bundle(org, check_id(stream_id, "stream_id"), checkpoints))
        except (FortressError, ValueError) as e:
            return _result({"error": str(e)}, is_error=True)

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

    @mcp.custom_route("/log/sth", methods=["GET"], include_in_schema=False)
    async def log_sth(_: Request) -> JSONResponse:
        return JSONResponse({**fortress.tree_head(), "keys": fortress.keys()},
                            headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "no-store"})

    @mcp.custom_route("/log/inclusion", methods=["GET"], include_in_schema=False)
    async def log_inclusion(request: Request) -> JSONResponse:
        q = request.query_params
        try:
            ts = int(q["tree_size"]) if q.get("tree_size") else None
            return JSONResponse(fortress.inclusion(q.get("hash", ""), ts), headers={"Access-Control-Allow-Origin": "*"})
        except (FortressError, ValueError) as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    @mcp.custom_route("/log/consistency", methods=["GET"], include_in_schema=False)
    async def log_consistency(request: Request) -> JSONResponse:
        q = request.query_params
        try:
            return JSONResponse(fortress.consistency(int(q.get("first", "0")), int(q["second"]) if q.get("second") else None),
                                headers={"Access-Control-Allow-Origin": "*"})
        except (FortressError, ValueError) as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    @mcp.custom_route("/tools/verify_bundle.py", methods=["GET"], include_in_schema=False)
    async def verifier_script(_: Request) -> Response:
        from pathlib import Path
        return Response((Path(__file__).parent / "verify_bundle.py").read_text(encoding="utf-8"),
                        media_type="text/x-python; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="verify_bundle.py"'})

    @mcp.custom_route("/tpi/{request_id}", methods=["GET"], include_in_schema=False)
    async def tpi_page(_: Request) -> Response:
        from pathlib import Path
        return Response((Path(__file__).parent / "tpi_sign.html").read_text(encoding="utf-8"),
                        media_type="text/html; charset=utf-8")

    @mcp.custom_route("/tpi/{request_id}/status", methods=["GET"], include_in_schema=False)
    async def tpi_status_http(request: Request) -> JSONResponse:
        try:
            return JSONResponse(fortress.tpi_public(request.path_params["request_id"]), headers={"Cache-Control": "no-store"})
        except FortressError as e:
            return JSONResponse({"error": str(e)}, status_code=404)

    async def _tpi_decide_http(request: Request, decision: str) -> JSONResponse:
        rid = request.path_params["request_id"]
        try:
            body = await request.json()
            r = fortress.tpi_decide(rid, decision, str(body.get("signature", "")))
            row = fortress.tpi_row(rid)
            ledger.record(row["org_id"], row["stream_id"], "Privi Ledger", "approval",
                          f"Officer {r['decided_by']} {'approved' if decision == 'approve' else 'vetoed'}: {r['summary']} "
                          f"({r['approvals_count']}/{r['required']})", rid,
                          "success" if decision == "approve" else "blocked", {"status": r["status"]})
            return JSONResponse(r)
        except (FortressError, ValueError, AttributeError) as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    @mcp.custom_route("/tpi/{request_id}/approve", methods=["POST"], include_in_schema=False)
    async def tpi_approve_http(request: Request) -> JSONResponse:
        return await _tpi_decide_http(request, "approve")

    @mcp.custom_route("/tpi/{request_id}/veto", methods=["POST"], include_in_schema=False)
    async def tpi_veto_http(request: Request) -> JSONResponse:
        return await _tpi_decide_http(request, "veto")

    @mcp.custom_route("/mandates/{mandate_id}", methods=["GET"], include_in_schema=False)
    async def mandate_json(request: Request) -> JSONResponse:
        try:
            return JSONResponse(mandates.public(request.path_params["mandate_id"]),
                                headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "no-store"})
        except MandateError as e:
            return JSONResponse({"error": str(e)}, status_code=404)

    @mcp.custom_route("/mandates/{mandate_id}/sign", methods=["GET"], include_in_schema=False)
    async def mandate_page(_: Request) -> Response:
        from pathlib import Path
        return Response((Path(__file__).parent / "mandate_sign.html").read_text(encoding="utf-8"),
                        media_type="text/html; charset=utf-8")

    @mcp.custom_route("/mandates/{mandate_id}/check", methods=["GET"], include_in_schema=False)
    async def mandate_check_http(request: Request) -> JSONResponse:
        q = request.query_params
        try:
            d = mandates.check(request.path_params["mandate_id"], q.get("amount", ""), q.get("payee", ""))
            d["ml_dsa_87_signature"] = fortress.pq_sign(d["attestation_hash"])
            return JSONResponse(d, headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "no-store"})
        except (MandateError, ValueError) as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    @mcp.custom_route("/mandates/{mandate_id}/activate", methods=["POST"], include_in_schema=False)
    async def mandate_activate_http(request: Request) -> JSONResponse:
        try:
            body = await request.json()
            return JSONResponse(await _activate_mandate(request.path_params["mandate_id"], str(body.get("signature", ""))))
        except (MandateError, ValueError, AttributeError) as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    @mcp.custom_route("/mandates/{mandate_id}/revoke", methods=["POST"], include_in_schema=False)
    async def mandate_revoke_http(request: Request) -> JSONResponse:
        mid = request.path_params["mandate_id"]
        try:
            body = await request.json()
            m = mandates.revoke(mid, str(body.get("reason", "")), signature=str(body.get("signature", "")))
            _mandate_log(mandates._row(mid), "approval", f"Mandate {mid} revoked by the human {m['principal']}")
            return JSONResponse(m)
        except (MandateError, ValueError, AttributeError) as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    @mcp.custom_route("/kya/connect", methods=["GET"], include_in_schema=False)
    async def kya_connect(_: Request) -> Response:
        from pathlib import Path
        return Response((Path(__file__).parent / "kya_connect.html").read_text(encoding="utf-8"),
                        media_type="text/html; charset=utf-8")

    @mcp.custom_route("/kya/challenge", methods=["POST"], include_in_schema=False)
    async def kya_challenge_http(request: Request) -> JSONResponse:
        org = ledger.org_for_key(_bearer(request.headers))
        if not org:
            return JSONResponse({"error": "a valid organization API key is required"}, status_code=401)
        try:
            body = await request.json()
            return JSONResponse(kya.challenge(org["org_id"], org["name"], str(body.get("address", ""))))
        except (ValueError, AttributeError) as e:
            return JSONResponse({"error": str(e) or "send JSON like {\"address\": \"0x...\"}"}, status_code=400)

    @mcp.custom_route("/kya/bind", methods=["POST"], include_in_schema=False)
    async def kya_bind_http(request: Request) -> JSONResponse:
        org = ledger.org_for_key(_bearer(request.headers))
        if not org:
            return JSONResponse({"error": "a valid organization API key is required"}, status_code=401)
        try:
            body = await request.json()
            sid = check_id(body["stream_id"], "stream_id") if body.get("stream_id") else "*"
            if not body.get("signature"):
                raise KYAError("a wallet signature is required on this page")
            b = kya.bind(org["org_id"], str(body.get("address", "")), sid, str(body.get("label") or ""),
                         body.get("challenge_id"), body.get("signature"))
            ledger.record(org["org_id"], "privi-kya", "Privi Ledger", "other",
                          f"Wallet {b['address']} bound ({b['proof']}) to {sid}", b["address"], "success",
                          {"proof": b["proof"], "stream_id": sid, "via": "kya/connect"})
            return JSONResponse({"bound": True, **b})
        except (KYAError, ValueError, KeyError, AttributeError) as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    @mcp.custom_route("/kya/{address}", methods=["GET"], include_in_schema=False)
    async def kya_json(request: Request) -> JSONResponse:
        q = request.query_params
        try:
            d = kya.check(request.path_params["address"], int(q.get("min_score", 550)), q.get("min_grade"),
                          q.get("require_signed", "true").lower() != "false")
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        d.update(kya.attest(d))
        d["ml_dsa_87_signature"] = fortress.pq_sign(d["attestation_hash"])
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
                             "post_quantum": fortress.keys()["post_quantum"], "transparency_log": f"{public_url}/log/sth",
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
    if not org or any(json.loads(r["attestation"]).get("anchored") for r in ledger._db.execute(
            "SELECT attestation FROM reports WHERE org_id=?", (org["org_id"],)).fetchall()):
        return   # an anchored report already exists; unanchored ones (e.g. issued before gas) are re-issued

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


def first_passport(mcp: MCPServer, ledger: Ledger, delay_s: float = 150.0) -> None:
    """LEDGER_BOOTSTRAP_PASSPORT=1: once, issue an organization passport for the bootstrap organization."""
    key = os.getenv("LEDGER_BOOTSTRAP_ORG_KEY", "")
    org = ledger.org_for_key(key)
    if not org:
        return
    rows = ledger._db.execute("SELECT passport_id, attestation FROM passports WHERE org_id=? AND revoked_at IS NULL",
                              (org["org_id"],)).fetchall()
    if any(json.loads(r["attestation"]).get("anchored") for r in rows):
        return   # an anchored passport already exists
    stale = [r["passport_id"] for r in rows]

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
            if a.get("anchored") and stale:
                with ledger._lock:
                    ledger._db.executemany(
                        "UPDATE passports SET revoked_at=?, revoke_reason=? WHERE passport_id=? AND revoked_at IS NULL",
                        [(time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
                          f"superseded by {r.get('passport_id')} (issued before on-chain anchoring was funded)", pid)
                         for pid in stale])
                    ledger._db.commit()
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
        fort = mcp.privi_fortress

        def anchor_tree_head() -> int:
            sth = fort.tree_head()
            n = sth["tree_head"]["tree_size"]
            last = fort.last_anchored_sth()
            if not n or (last and last["tree_head"]["tree_size"] == n):
                return 0
            r = client.anchor([sth["body_hash"]], f"privi transparency log size {n}")
            rc = next(x for x in r["receipts"] if x["hash"] == sth["body_hash"])
            fort.set_sth_anchor(n, {"tx_hash": r["tx_hash"], "proof": rc["proof"], "block_number": r.get("block_number"),
                                    "chain_id": r.get("chain_id"), "anchored_hash": sth["body_hash"]})
            print(f"privi-ledger: anchored transparency log head size={n} block={r.get('block_number')}", flush=True)
            return 1

        start_loop(anchor_tree_head, float(os.getenv("LEDGER_STH_INTERVAL", "900")), "privi-ledger-sth")
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
    from .usage import UsageMiddleware
    app = UsageMiddleware(mcp.streamable_http_app(host=args.host, stateless_http=True, json_response=True),
                          ledger._db, ledger._lock, "privi-ledger")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
