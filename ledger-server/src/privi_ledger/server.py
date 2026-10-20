"""Privi Ledger MCP server: tamper-evident audit logs for AI agents.

Free:          ledger_pricing, ledger_check_receipt
Paid (x402):   ledger_audit_stream      (auditors, USDC on Base)
Org API key:   ledger_record_action, ledger_read_stream, ledger_list_streams
Admin (HTTP):  POST /admin/orgs         (create an organization and its API key)
"""

from __future__ import annotations

import argparse
import base64
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
contents (paid per call with x402, USDC on Base). ledger_check_receipt is free."""

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
