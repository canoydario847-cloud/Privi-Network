"""MCP tools and HTTP routes for the Privi Ops Pack (Trust Page, Incident Clock, Policy Sign-off,
Control Calendar, Release Seal)."""

from __future__ import annotations

from typing import Annotated, Any, Callable

from mcp.server.mcpserver import Context, MCPServer
from mcp_types import ToolAnnotations
from pydantic import Field
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse

from .ops_pack import REGIMES, SEVERITIES, OpsError, OpsPack, trust_html

READ = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)
SAVE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)

Sha = Annotated[str, Field(description="SHA-256 fingerprint of the document (64 hex characters); the file stays with you")]
Actor = Annotated[str, Field(description="Who is doing this (person or agent)")]


def register(mcp: MCPServer, ops: OpsPack, *, anchor_many: Callable, org_from: Callable, result: Callable,
             unauthorized, over_limit: Callable) -> None:

    def guarded(ctx, fn, write: bool = True):
        org = org_from(ctx)
        if not org:
            return unauthorized
        if write and (blocked := over_limit(org["org_id"])):
            return blocked
        try:
            return result(fn(org))
        except OpsError as e:
            return result({"error": str(e)}, is_error=True)

    # ---------------- Trust Page ----------------

    @mcp.tool(title="Trust Page: publish", annotations=SAVE)
    def trust_page_publish(
        slug: Annotated[str, Field(description="Short web name for the page, e.g. acme-tooling")],
        headline: Annotated[str, Field(description="One sentence buyers read first")],
        claims: Annotated[list[dict[str, Any]], Field(description=(
            'What you want buyers to know, each {"label": "ISO 9001 certified", "document_sha256": "<64 hex>", '
            '"valid_until": "2027-06-30T00:00:00Z"}; fingerprint and date are optional'))],
        ctx: Context,
        contact: Annotated[str, Field(description="Email or link for buyer questions")] = "",
    ) -> Any:
        """Publish (or replace) your company's public trust page: your claims with evidence fingerprints, plus the
        live health of your tamper-evident logs. Share the link in sales emails and security questionnaires.
        Requires the organization API key."""
        return guarded(ctx, lambda org: ops.trust_publish(org["org_id"], slug, headline, claims, contact))

    @mcp.tool(title="Trust Page: read a company's page", annotations=READ)
    def trust_page_view(slug: Annotated[str, Field(description="The page's web name")]) -> Any:
        """Read any company's Privi trust page: its claims, evidence fingerprints and whether its logs are intact
        right now. No organization key needed."""
        page = ops.trust_view(slug)
        return result(page) if page else result({"error": "no trust page with that name"}, is_error=True)

    # ---------------- Incident Clock ----------------

    @mcp.tool(title="Incident: open and start the clocks", annotations=WRITE)
    def incident_open(
        title: Annotated[str, Field(description="What happened, in a sentence")],
        severity: Annotated[str, Field(description="|".join(SEVERITIES))],
        actor: Actor, ctx: Context,
        regimes: Annotated[list[str] | None, Field(description=(
            "Notification rules that may apply: " + "; ".join(f"{k} = {v['name']}" for k, v in REGIMES.items())))] = None,
        aware_at: Annotated[str | None, Field(description="When you became aware (ISO 8601). Default: now")] = None,
        material_at: Annotated[str | None, Field(description="SEC only: when you decided the incident was material")] = None,
        contract_hours: Annotated[int | None, Field(description="Hours your customer contracts give you to notify them")] = None,
    ) -> Any:
        """Open a security or operations incident. Privi starts the notification clocks for the rules you pick
        (GDPR 72 hours, NIS2 24 hours / 72 hours / one month, SEC four business days, your contract's hours) and
        writes the incident to your tamper-evident 'incidents' log. Requires the organization API key."""
        return guarded(ctx, lambda org: ops.incident_open(org["org_id"], actor, title, severity, aware_at, regimes,
                                                          material_at, contract_hours))

    @mcp.tool(title="Incident: add an update", annotations=WRITE)
    def incident_update(
        incident_id: str, note: Annotated[str, Field(description="What was found or done")], actor: Actor, ctx: Context,
        completed_step: Annotated[str | None, Field(description=(
            "A notification you just made, e.g. gdpr.authority_notification, nis2.early_warning, sec_8k.form_8k, "
            "contract.notify"))] = None,
        material_at: Annotated[str | None, Field(description="SEC only: set when materiality is decided")] = None,
    ) -> Any:
        """Add a timestamped update to an open incident, and optionally mark a notification as made. Each update
        is hash-chained, so the timeline cannot be rewritten later. Requires the organization API key."""
        return guarded(ctx, lambda org: ops.incident_update(org["org_id"], incident_id, actor, note, completed_step,
                                                            material_at))

    @mcp.tool(title="Incident: status and deadlines", annotations=READ)
    def incident_status(
        ctx: Context,
        incident_id: Annotated[str | None, Field(description="One incident; omit to list all")] = None,
    ) -> Any:
        """Where an incident stands: each notification deadline, hours left or overdue, and the timeline. Omit
        incident_id for a list of your incidents. Requires the organization API key."""
        return guarded(ctx, lambda org: ops.incident(org["org_id"], incident_id) if incident_id
                       else {"incidents": ops.incidents(org["org_id"])}, write=False)

    @mcp.tool(title="Incident: close and seal the report", annotations=WRITE)
    async def incident_close(incident_id: str, root_cause: Annotated[str, Field(description="Root cause and fix")],
                             actor: Actor, ctx: Context) -> Any:
        """Close an incident and get a sealed post-incident report (timeline, deadlines met or missed, root
        cause) whose SHA-256 is anchored on chain, ready for customers, insurers or regulators. Requires the
        organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        try:
            doc, h = ops.incident_close_doc(org["org_id"], incident_id, actor, root_cause)
            att = (await anchor_many([h], f"Incident report {incident_id}"))[h]
            return result(ops.incident_store_close(org["org_id"], doc, h, att))
        except OpsError as e:
            return result({"error": str(e)}, is_error=True)

    # ---------------- Policy Sign-off ----------------

    @mcp.tool(title="Policy: publish a version", annotations=WRITE)
    def policy_publish(policy_id: Annotated[str, Field(description="Your short ID, e.g. acceptable-use")],
                       title: str, document_sha256: Sha, actor: Actor, ctx: Context) -> Any:
        """Publish a policy (or a new version of one) by its document fingerprint. People then acknowledge that
        exact version. Requires the organization API key."""
        return guarded(ctx, lambda org: ops.policy_publish(org["org_id"], actor, policy_id, title, document_sha256))

    @mcp.tool(title="Policy: acknowledge", annotations=WRITE)
    def policy_acknowledge(policy_id: str, person: Annotated[str, Field(description="Name or email of the person acknowledging")],
                           document_sha256: Sha, ctx: Context) -> Any:
        """Record that a person read and accepted the current version of a policy. The fingerprint must match
        the current version, so nobody signs off on an old document. Requires the organization API key."""
        return guarded(ctx, lambda org: ops.policy_acknowledge(org["org_id"], policy_id, person, document_sha256))

    @mcp.tool(title="Policy: who has signed", annotations=READ)
    def policy_status(policy_id: str, ctx: Context,
                      required_people: Annotated[list[str] | None, Field(description="Everyone who must sign; Privi lists who is missing")] = None) -> Any:
        """Who acknowledged the current version of a policy and who is still missing. This is the evidence
        auditors ask for. Requires the organization API key."""
        return guarded(ctx, lambda org: ops.policy_status(org["org_id"], policy_id, required_people), write=False)

    # ---------------- Control Calendar ----------------

    @mcp.tool(title="Control: add or update", annotations=SAVE)
    def control_save(control_id: Annotated[str, Field(description="Your short ID, e.g. backup-restore-test")],
                     title: str, every_days: Annotated[int, Field(description="How often it must be done, in days (90 = quarterly)")],
                     owner: Annotated[str, Field(description="Who is responsible")], actor: Actor, ctx: Context,
                     reference: Annotated[str, Field(description="Framework reference, e.g. SOC 2 CC6.2 or ISO 27001 A.8.13")] = "",
                     retired: bool = False) -> Any:
        """Add a recurring control (access review, backup restore test, vendor review) to your calendar.
        Requires the organization API key."""
        return guarded(ctx, lambda org: ops.control_save(org["org_id"], actor, control_id, title, every_days, owner,
                                                         reference, retired))

    @mcp.tool(title="Control: record that it was done", annotations=WRITE)
    def control_evidence(control_id: str, performed_by: str, document_sha256: Sha, ctx: Context, note: str = "",
                         performed_at: Annotated[str | None, Field(description="When it was done (ISO 8601). Default: now")] = None) -> Any:
        """Record that a control was performed, with the fingerprint of the evidence (screenshot, export,
        report). Hash-chained, so evidence cannot be back-dated after the fact without it showing. Requires the
        organization API key."""
        return guarded(ctx, lambda org: ops.control_evidence(org["org_id"], control_id, performed_by, document_sha256,
                                                             note, performed_at))

    @mcp.tool(title="Control: what is due", annotations=READ)
    def controls_due(ctx: Context, soon_days: Annotated[int, Field(description="Flag controls due within this many days", ge=0, le=365)] = 14) -> Any:
        """Your control calendar: overdue, never done, due soon and current, each with its last evidence.
        Requires the organization API key."""
        return guarded(ctx, lambda org: ops.controls_due(org["org_id"], soon_days), write=False)

    # ---------------- Release Seal ----------------

    @mcp.tool(title="Release: seal a software release", annotations=WRITE)
    async def release_seal(
        product: str, version: Annotated[str, Field(description="e.g. 1.4.2")],
        files: Annotated[list[dict[str, str]], Field(description='Release files, each {"name": "app-1.4.2.zip", "sha256": "<64 hex>"}')],
        actor: Actor, ctx: Context,
        commit: Annotated[str, Field(description="Source commit the release was built from")] = "",
        sbom_sha256: Annotated[str, Field(description="Fingerprint of the software bill of materials, if you have one")] = "",
    ) -> Any:
        """Seal a software release: its file fingerprints, source commit and SBOM fingerprint, anchored on chain.
        Customers check any download with release_check. A sealed release cannot be changed. Requires the
        organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        if blocked := over_limit(org["org_id"]):
            return blocked
        try:
            doc, h = ops.release_doc(org["org_id"], actor, product, version, files, commit, sbom_sha256)
            att = (await anchor_many([h], f"Release {product} {version}"))[h]
            return result(ops.release_store(doc, h, att))
        except OpsError as e:
            return result({"error": str(e)}, is_error=True)

    @mcp.tool(title="Release: check a downloaded file", annotations=READ)
    def release_check(file_sha256: Annotated[str, Field(description="SHA-256 of the file you downloaded")]) -> Any:
        """Check that a file you downloaded is part of a release its maker sealed with Privi, and see which
        company, product and version it belongs to. No organization key needed."""
        try:
            return result(ops.release_check(file_sha256))
        except OpsError as e:
            return result({"error": str(e)}, is_error=True)


def _cors(data: Any, status: int = 200) -> JSONResponse:
    return JSONResponse(data, status_code=status, headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "no-store"})


def http_routes(ops: OpsPack) -> list[tuple[str, list[str], Callable]]:

    async def trust_page(request: Request):
        page = ops.trust_view(request.path_params["slug"])
        if not page:
            return _cors({"error": "not found"}, 404)
        if "application/json" in request.headers.get("accept", "") or request.query_params.get("format") == "json":
            return _cors(page)
        return HTMLResponse(trust_html(page), headers={"Cache-Control": "no-store"})

    async def release(request: Request):
        try:
            v = ops.release_check(request.path_params["sha256"])
        except OpsError as e:
            return _cors({"error": str(e)}, 400)
        return _cors(v, 200 if v["genuine"] else 404)

    return [("/trust/{slug}", ["GET"], trust_page), ("/releases/check/{sha256}", ["GET"], release)]
