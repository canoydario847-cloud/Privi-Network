"""MCP tools and HTTP routes for the "must-have" pack:
Privi AI Act Pack, Privi Supplier Proof and Privi Content Seal."""

from __future__ import annotations

import hashlib
from typing import Annotated, Any, Callable

from mcp.server.mcpserver import Context, MCPServer
from mcp_types import ToolAnnotations
from pydantic import Field
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response

from . import content_seal, supplier_proof
from .ai_act import ANNEX_III_AREAS, OBLIGATIONS, PROHIBITED, ROLES, AIActRegister, canon
from .content_seal import ContentSeals, SealError
from .supplier_proof import SupplierProof, SupplierProofError

READ = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)
SAVE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)
REVOKE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False)


def _cors(data: Any, status: int = 200) -> JSONResponse:
    return JSONResponse(data, status_code=status, headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "no-store"})


def register(mcp: MCPServer, ledger, *, aiact: AIActRegister, suppliers: SupplierProof, seals: ContentSeals,
             anchor_many: Callable, org_from: Callable, result: Callable, unauthorized, over_limit: Callable) -> None:

    def err(e):
        return result({"error": str(e)}, is_error=True)

    # ---------------- Privi AI Act Pack ----------------

    @mcp.tool(title="AI Act: register an AI system", annotations=SAVE)
    def ai_act_system_save(
        system: Annotated[dict[str, Any], Field(description=(
            "AI system record. Required: system_id. Recommended: name, owner, role (" + "|".join(ROLES) + "), "
            "intended_purpose, used_in_eu, vendor_name. Risk flags: annex_iii_area (" + "|".join(ANNEX_III_AREAS) +
            " or empty), annex_i_product, gpai_model, public_body_or_public_service, interacts_with_people, "
            "generates_synthetic_content, emotion_or_biometric_categorisation, deepfake_or_public_interest_text, "
            "not_high_risk_justification (Art. 6(3)). prohibited_screen {practice: true/false} for: "
            + ", ".join(PROHIBITED) + ". controls {obligation_id: {done, evidence, date}} for: " + ", ".join(OBLIGATIONS)
            + ". log_streams: Privi Ledger stream IDs holding the system's logs. retired: true to retire."))],
        actor: Annotated[str, Field(description="Who is making the change (person or agent)")],
        ctx: Context,
        merge: Annotated[bool, Field(description="Merge into the existing record (true) or replace it (false)")] = True,
    ) -> Any:
        """Add or update an AI system in your company's EU AI Act register. Privi screens it against the Article 5
        bans, classifies it (prohibited / high-risk / transparency / general-purpose / minimal), and lists the
        obligations that apply to your role with their dates. Every change is versioned and written to your
        tamper-evident 'ai-act' log. Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        if blocked := over_limit(org["org_id"]):
            return blocked
        try:
            return result(aiact.upsert(org["org_id"], actor, system, merge))
        except ValueError as e:
            return err(e)

    @mcp.tool(title="AI Act: your register", annotations=READ)
    def ai_act_register(
        ctx: Context,
        system_id: Annotated[str | None, Field(description="One system; omit for all")] = None,
    ) -> Any:
        """Your EU AI Act register: each AI system's current record, tier and applicable obligations.
        Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        return result({"org_id": org["org_id"], "systems": aiact.latest(org["org_id"], system_id)})

    @mcp.tool(title="AI Act: compliance check", annotations=READ)
    def ai_act_check(ctx: Context) -> Any:
        """What a customer's due-diligence or a regulator would flag today: prohibited practices, incomplete
        Article 5 screens, obligations already in force without evidence (critical), obligations due within 180
        days (medium), upcoming high-risk duties, and high-risk systems with no recent log. Requires the
        organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        return result(aiact.check(org["org_id"]))

    @mcp.tool(title="AI Act: export sealed register", annotations=WRITE)
    async def ai_act_export(ctx: Context) -> Any:
        """Export your AI Act register as JSON to hand to customers, auditors or regulators, with its SHA-256
        sealed on chain so anyone can prove it was not edited afterwards (check with ai_act_verify_export).
        Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        doc = aiact.register_doc(org["org_id"], org["name"])
        doc["check"] = {k: v for k, v in aiact.check(org["org_id"]).items() if k in
                        ("as_of", "compliant_today", "ready_for_next_180_days", "finding_counts")}
        text = canon(doc)
        h = hashlib.sha256(text.encode("utf-8")).hexdigest()
        att = (await anchor_many([h], f"AI Act register {org['org_id']}"))[h]
        aiact.save_export(org["org_id"], h, len(doc["systems"]), att)
        ledger.record(org["org_id"], "ai-act", "Privi Ledger", "data_access",
                      f"Exported AI Act register ({len(doc['systems'])} system(s))", "ai-act-export", "success",
                      {"export_hash": h, "anchored": att.get("anchored")})
        return result({"register_json": text, "export_hash": h, "attestation": att,
                       "share": "Send register_json as-is; recipients verify it with ai_act_verify_export."})

    @mcp.tool(title="AI Act: verify a register", annotations=READ)
    def ai_act_verify_export(
        register_json: Annotated[str, Field(description="The exact register_json a company shared with you")],
    ) -> Any:
        """Check that an AI Act register a supplier or partner sent you is exactly what they exported from Privi,
        and return its on-chain seal. Free; no key needed."""
        h = hashlib.sha256(register_json.encode("utf-8")).hexdigest()
        rec = aiact.find_export(h)
        if not rec:
            return result({"valid": False, "export_hash": h, "reason": "no export with this exact content; it may have been edited"})
        return result({"valid": True, "export_hash": h, **rec})

    # ---------------- Privi Supplier Proof ----------------

    @mcp.tool(title="Supplier Proof: require proof from suppliers", annotations=WRITE)
    def supplier_requirement_create(
        title: Annotated[str, Field(description="e.g. 'Approved supplier 2027'")],
        items: Annotated[list[dict[str, Any]], Field(description=(
            "What each supplier must prove: [{key: 'iso_9001', label: 'ISO 9001 certificate', document_required: true}, "
            "{key: 'ai_act_register', label: 'Sealed Privi AI Act register'}]. 1-30 items."))],
        ctx: Context,
        valid_days: Annotated[int, Field(description="How long an approved certificate lasts (1-1095 days)")] = 365,
    ) -> Any:
        """Publish a requirement your suppliers must meet. Share the returned invite_url with them: they answer it
        from their own Privi organization (free sign-up) and you approve or reject in supplier_proof_inbox.
        Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        try:
            return result(suppliers.create_requirement(org["org_id"], title, items, valid_days))
        except SupplierProofError as e:
            return err(e)

    @mcp.tool(title="Supplier Proof: view a requirement", annotations=READ)
    def supplier_requirement_get(req_id: Annotated[str, Field(description="Requirement ID (req_...)")]) -> Any:
        """See what a buyer requires of its suppliers. Free; no key needed."""
        req = suppliers.requirement(req_id)
        return result(req) if req else err("requirement not found")

    @mcp.tool(title="Supplier Proof: submit proof to a buyer", annotations=WRITE)
    def supplier_proof_submit(
        req_id: Annotated[str, Field(description="The buyer's requirement ID (req_...)")],
        evidence: Annotated[dict[str, Any], Field(description=(
            "One entry per requirement item: {item_key: {sha256: '<64-hex of the document>', note: '...', "
            "valid_until: 'YYYY-MM-DD'}}. Only fingerprints are sent; keep the documents yourself."))],
        ctx: Context,
    ) -> Any:
        """Answer a buyer's supplier requirement with fingerprints of your evidence documents. The buyer reviews
        and, if approved, Privi issues a certificate sealed on chain. Requires your organization API key
        (sign up free with ledger_signup)."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        try:
            return result(suppliers.submit(org["org_id"], req_id, evidence))
        except SupplierProofError as e:
            return err(e)

    @mcp.tool(title="Supplier Proof: inbox", annotations=READ)
    def supplier_proof_inbox(
        ctx: Context,
        status: Annotated[str, Field(description="pending | approved | rejected | superseded")] = "pending",
    ) -> Any:
        """Supplier submissions waiting for your decision (as the buyer). Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        return result({"submissions": suppliers.inbox(org["org_id"], status)})

    @mcp.tool(title="Supplier Proof: approve or reject", annotations=WRITE)
    async def supplier_proof_decide(
        sub_id: Annotated[str, Field(description="Submission ID (sub_...)")],
        approve: Annotated[bool, Field(description="true issues the certificate; false rejects")],
        ctx: Context,
        reason: Annotated[str, Field(description="Required when rejecting, so the supplier can fix it")] = "",
    ) -> Any:
        """Approve a supplier's proof (issues a certificate naming both companies and the evidence fingerprints,
        sealed on chain, with a public verify page and badge) or reject it with a reason. Requires the
        organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        try:
            out = suppliers.decide(org["org_id"], sub_id, approve, reason)
            if not approve:
                return result(out)
            att = (await anchor_many([out["body_hash"]], f"Supplier certificate {out['cert_id']}"))[out["body_hash"]]
            cert = suppliers.store_cert(org["org_id"], out, att)
            return result({**cert, "verify_url": cert["certificate"]["verify_url"],
                           "badge": cert["certificate"]["verify_url"] + "/badge.svg"})
        except SupplierProofError as e:
            return err(e)

    @mcp.tool(title="Supplier Proof: verify a certificate", annotations=READ)
    def supplier_cert_verify(
        cert_id: Annotated[str, Field(description="Certificate ID (spc_...)")],
        document_sha256: Annotated[str | None, Field(description="Optional: SHA-256 of a document to check it is the "
                                                                 "one the certificate covers")] = None,
    ) -> Any:
        """Check a Privi supplier certificate: untampered, not revoked, not expired, which buyer approved which
        supplier, and (optionally) whether a document is one it covers. Free; no key needed."""
        return result(suppliers.verify(cert_id, document_sha256))

    @mcp.tool(title="Supplier Proof: your certificates", annotations=READ)
    def supplier_certs(ctx: Context) -> Any:
        """Certificates you issued (as buyer) or hold (as supplier). Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        return result({"certificates": suppliers.list_certs(org["org_id"])})

    @mcp.tool(title="Supplier Proof: revoke a certificate", annotations=REVOKE)
    def supplier_cert_revoke(
        cert_id: Annotated[str, Field(description="Certificate ID (spc_...)")],
        reason: Annotated[str, Field(description="Why it is revoked")],
        ctx: Context,
    ) -> Any:
        """Revoke a certificate you issued (as the buyer). Verification shows it as revoked at once.
        Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        try:
            return result(suppliers.revoke(org["org_id"], cert_id, reason))
        except SupplierProofError as e:
            return err(e)

    # ---------------- Privi Content Seal ----------------

    @mcp.tool(title="Content Seal: seal files or text", annotations=WRITE)
    async def seal_content(
        items: Annotated[list[dict[str, Any]], Field(description=(
            "1-50 items: {sha256: '<64-hex of the file>' (or text: 'exact text'), origin: "
            "human|ai_assisted|ai_edited|ai_generated, ai_tool (required unless human), title, author, media_type, note}. "
            "Only the fingerprint is sent, never the file."))],
        ctx: Context,
    ) -> Any:
        """Seal content your company publishes (documents, images, video, press releases, invoices, AI output)
        with who made it and whether AI was involved. Each seal is anchored on chain; anyone can check a file
        for free at the returned verify_url or with seal_verify. Counts toward your plan's monthly entries.
        Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        try:
            prepared = seals.prepare(org["org_id"], org["name"], items)
        except SealError as e:
            return err(e)
        if blocked := over_limit(org["org_id"], len(prepared)):
            return blocked
        atts = await anchor_many([p["body_hash"] for p in prepared], f"Content seals {org['org_id']}")
        return result({"sealed": seals.store(org["org_id"], prepared, atts),
                       "check_page": f"{seals.public_url}/seal/check"})

    @mcp.tool(title="Content Seal: check a file", annotations=READ)
    def seal_verify(
        ctx: Context,
        sha256: Annotated[str | None, Field(description="SHA-256 (64 hex) of the file")] = None,
        text: Annotated[str | None, Field(description="Or the exact text")] = None,
    ) -> Any:
        """Is this exact file or text sealed, by whom, since when, and did they declare AI involvement? Any
        change to the content (one pixel, one character) means no match. Free; no key needed."""
        try:
            h = content_seal.text_hash(text) if text is not None else (sha256 or "")
            return result(seals.lookup(h))
        except SealError as e:
            return err(e)

    @mcp.tool(title="Content Seal: your seals", annotations=READ)
    def seal_list(ctx: Context, limit: Annotated[int, Field(description="1-200")] = 50) -> Any:
        """Your most recent content seals. Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        return result({"seals": seals.list(org["org_id"], limit)})

    @mcp.tool(title="Content Seal: revoke a seal", annotations=REVOKE)
    def seal_revoke(
        seal_id: Annotated[str, Field(description="Seal ID (seal_...)")],
        reason: Annotated[str, Field(description="Why it is revoked")],
        ctx: Context,
    ) -> Any:
        """Withdraw one of your seals (e.g. sealed by mistake). Checks then show it as revoked.
        Requires the organization API key."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        try:
            return result(seals.revoke(org["org_id"], seal_id, reason))
        except SealError as e:
            return err(e)


def http_routes(suppliers: SupplierProof, seals: ContentSeals) -> list[tuple[str, list[str], Callable]]:

    async def requirement(request: Request) -> JSONResponse:
        req = suppliers.requirement(request.path_params["req_id"])
        if not req:
            return _cors({"error": "not found"}, 404)
        return _cors({**req, "how_to_answer": {
            "1": "Sign up free: MCP tool ledger_signup (or POST /guard/v1/signup) to get your organization key",
            "2": "Hash each document (SHA-256); documents stay with you",
            "3": f"Call supplier_proof_submit with req_id={req['req_id']} at {suppliers.public_url}/mcp"}})

    async def cert(request: Request) -> JSONResponse:
        v = suppliers.verify(request.path_params["cert_id"], request.query_params.get("document_sha256"))
        return _cors(v, 200 if v.get("certificate") else 404)

    async def cert_badge(request: Request) -> Response:
        v = suppliers.verify(request.path_params["cert_id"])
        label = "revoked" if v.get("revoked") else "expired" if v.get("expired") else "not valid"
        return Response(supplier_proof.badge_svg(label, v["valid"]), media_type="image/svg+xml",
                        headers={"Cache-Control": "max-age=300"})

    async def seal_page(_: Request) -> HTMLResponse:
        return HTMLResponse(content_seal.CHECK_PAGE)

    async def seal_json(request: Request) -> JSONResponse:
        try:
            return _cors(seals.lookup(request.path_params["sha256"]))
        except SealError as e:
            return _cors({"error": str(e)}, 400)

    async def seal_badge(request: Request) -> Response:
        try:
            r = seals.lookup(request.path_params["sha256"])
        except SealError:
            r = {"sealed": False}
        state = "none" if not r["sealed"] else "ai" if r["ai_involved"] else "human"
        return Response(content_seal.badge_svg(state), media_type="image/svg+xml", headers={"Cache-Control": "max-age=300"})

    return [
        ("/supplier/requirements/{req_id}", ["GET"], requirement),
        ("/certs/{cert_id}", ["GET"], cert),
        ("/certs/{cert_id}/badge.svg", ["GET"], cert_badge),
        ("/seal/check", ["GET"], seal_page),
        ("/seal/{sha256}", ["GET"], seal_json),
        ("/seal/{sha256}/badge.svg", ["GET"], seal_badge),
    ]
