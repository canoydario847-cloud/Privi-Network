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

DEFAULT_ANCHOR_URL = "https://privi-anchor-production.up.railway.app/mcp"

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
contents (paid per call with x402, USDC on Base). ledger_check_receipt is free.

Dealings with another company on Privi (payments, data transfers, deliveries, agreements):
use Privi Handshake (ledger_handshake_offer / _inbox / _accept / _reject) so both companies
hold matching records sealed on the Privi chain; ledger_handshake_verify is a free public check."""

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
    if args.stdio:
        mcp.run("stdio")
        return
    import uvicorn
    uvicorn.run(mcp.streamable_http_app(host=args.host, stateless_http=True, json_response=True),
                host=args.host, port=args.port)


if __name__ == "__main__":
    main()
