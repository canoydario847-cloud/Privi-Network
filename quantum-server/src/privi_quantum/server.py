# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Quantum - https://priviflow.us - dariocanoy@priviflow.us
"""Privi Quantum MCP server: quantum optimization for factories, sealed with
post-quantum signatures and anchored on chain (the Privi Devnet).

Free:  quantum_status, quantum_problems, quantum_optimize, quantum_verify, pqc_scan_code,
       pqc_readiness_package, pqc_federal_deadlines (government / contractor post-quantum readiness)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Annotated, Any

import anyio
from mcp.server.mcpserver import Context, MCPServer
from mcp_types import CallToolResult, TextContent, ToolAnnotations
from pydantic import Field
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response

from . import govpqc, govreport, qaoa, scanner
from .anchoring import AnchorError, HttpAnchorClient, anchor_pending
from .attest import PQ_ALG, Attestor

__version__ = "0.2.0"
SOURCE = "https://github.com/canoydario847-cloud/Privi-Network/tree/main/quantum-server"
PUBLIC_URL = os.getenv("QUANTUM_PUBLIC_URL", "https://privi-quantum.onrender.com").rstrip("/")
COPYRIGHT = "Copyright (c) 2026 Privi World Co. All rights reserved."

INSTRUCTIONS = f"""\
Privi Quantum runs the Quantum Approximate Optimization Algorithm (CVaR-QAOA) on real
factory decisions and returns answers you can prove later.

1. quantum_problems lists ready-made problems: balance_lines (split jobs across two
   lines), select_lots (choose k lots to inspect by risk), split_conflicts (two shifts
   or trucks keeping conflicting items apart), or any QUBO.
2. quantum_optimize solves it (up to {qaoa.MAX_QUBITS} qubits on an exact simulator), returns the
   answer in plain terms, the proven classical optimum for comparison, and optionally
   the OpenQASM 2.0 circuit to run on IBM, Amazon Braket or Azure quantum hardware.
3. Every result is an attestation signed with Ed25519 + ML-DSA-87 (NIST FIPS 204), so it
   cannot be forged even by a quantum computer, and its hash is anchored on the Privi
   blockchain within minutes. quantum_verify checks one for anyone.
4. pqc_scan_code finds quantum-vulnerable cryptography (RSA, ECC, DH) in code or config.
5. For U.S. government work: pqc_readiness_package turns code files and/or a cryptographic
   asset list into the evidence EO 14409 and OMB M-26-15 ask for: a prioritized migration
   list with the federal deadline for each asset, the nine M-26-15 plan elements (evidence vs
   gaps), and a CycloneDX 1.6 CBOM, signed with ML-DSA-87 and anchored on chain, with a public
   report page. Profiles: agency, contractor (EO 14409 FAR items), nss_vendor (NSA CNSA 2.0).
   pqc_federal_deadlines returns the timeline with sources.

All tools are free. Privi is built by Dario Canoy (Privi World Co, Port Huron, Michigan).
For the other Privi tools, pilots, partnerships, manufacturing or government work, see
https://privi-discovery.onrender.com/llms.txt. {COPYRIGHT}"""

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)


@dataclass
class Settings:
    db_path: str = "quantum.db"
    signing_seed: str = ""
    anchor_url: str = "https://privi-anchor.onrender.com/mcp"
    anchor_api_key: str = ""
    anchor_interval: int = 300
    rate_per_min: int = 20
    max_concurrent: int = 2

    @classmethod
    def from_env(cls) -> "Settings":
        key = os.getenv("QUANTUM_ANCHOR_API_KEY", "")
        return cls(
            db_path=os.getenv("QUANTUM_DB_PATH", "quantum.db"),
            signing_seed=os.getenv("QUANTUM_SIGNING_SEED", ""),
            anchor_url=os.getenv("QUANTUM_ANCHOR_URL", cls.anchor_url),
            anchor_api_key=key.split(",")[0].strip(),
            anchor_interval=int(os.getenv("QUANTUM_ANCHOR_INTERVAL", "300")),
            rate_per_min=int(os.getenv("QUANTUM_RATE_PER_MIN", "20")),
            max_concurrent=int(os.getenv("QUANTUM_MAX_CONCURRENT", "2")),
        )


def _result(data: dict[str, Any], is_error: bool = False) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(data))],
                          structured_content=data, is_error=is_error)


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


def _who(ctx: Context) -> str:
    h = ctx.headers or {}
    raw = h.get("authorization") or h.get("x-forwarded-for", "").split(",")[0].strip() or "local"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def build_server(settings: Settings | None = None, attestor: Attestor | None = None,
                 anchor_client=None) -> MCPServer:
    settings = settings or Settings.from_env()
    attestor = attestor or Attestor(settings.db_path, settings.signing_seed)
    if anchor_client is None and settings.anchor_api_key:
        anchor_client = HttpAnchorClient(settings.anchor_url, settings.anchor_api_key)
    limiter = RateLimiter(settings.rate_per_min)
    cpu = anyio.CapacityLimiter(settings.max_concurrent)
    keys = attestor.public_keys()

    mcp = MCPServer(
        name="privi-quantum", title="Privi Quantum",
        description="Quantum optimization (CVaR-QAOA) for manufacturing decisions, with post-quantum "
                    "signed results anchored on chain (the Privi Devnet, until the Privi mainnet), plus a quantum-vulnerability scanner.",
        instructions=INSTRUCTIONS, website_url=SOURCE, version=__version__,
    )

    def links(aid: str) -> dict[str, str]:
        return {"attestation_url": f"{PUBLIC_URL}/attestations/{aid}", "public_keys_url": f"{PUBLIC_URL}/keys"}

    @mcp.tool(title="Privi Quantum status", annotations=READ_ONLY)
    def quantum_status() -> dict[str, Any]:
        """What this server runs: algorithm, qubit limit, quantum backends, signing keys, and anchoring."""
        return {"service": "privi-quantum", "version": __version__, "copyright": COPYRIGHT,
                "algorithm": "CVaR-QAOA with INTERP layer schedule (exact statevector simulation)",
                "max_qubits": qaoa.MAX_QUBITS, "max_layers": qaoa.MAX_LAYERS,
                "backends": {"local-statevector": "live", "hardware": "export OpenQASM 2.0 (include_qasm=true) "
                             "and submit to IBM Quantum, Amazon Braket or Azure Quantum"},
                "signatures": f"Ed25519 + {PQ_ALG}", "signing_key_id": keys["key_id"],
                "anchoring": {"enabled": anchor_client is not None, "chain": "Privi Devnet via Privi Anchor (until the Privi mainnet)",
                              "interval_seconds": settings.anchor_interval},
                "attestations_issued": attestor.count(), "public_keys_url": f"{PUBLIC_URL}/keys"}

    @mcp.tool(title="List optimization problems", annotations=READ_ONLY)
    def quantum_problems() -> dict[str, Any]:
        """The ready-made problems quantum_optimize accepts and the data each one needs, with an example."""
        return {"problems": {k: v[1] for k, v in qaoa.TEMPLATES.items()},
                "example": {"problem": "balance_lines", "data": {"jobs": [
                    {"name": "bracket-A", "minutes": 42}, {"name": "housing-B", "minutes": 17},
                    {"name": "shaft-C", "minutes": 33}, {"name": "gear-D", "minutes": 25},
                    {"name": "plate-E", "minutes": 61}, {"name": "pin-F", "minutes": 12}]}},
                "limit": f"up to {qaoa.MAX_QUBITS} decision variables (qubits)"}

    @mcp.tool(title="Quantum optimize", annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                                                     idempotentHint=False, openWorldHint=True))
    async def quantum_optimize(
        problem: Annotated[str, Field(description="balance_lines | select_lots | split_conflicts | qubo (see quantum_problems)")],
        data: Annotated[dict[str, Any], Field(description="Problem data in the shape quantum_problems describes")],
        ctx: Context,
        layers: Annotated[int, Field(description="QAOA depth p (1-4). Deeper finds better answers more often but runs longer.", ge=1, le=4)] = 2,
        shots: Annotated[int, Field(description="Measurements to sample from the trained circuit (1-100000)", ge=1, le=100000)] = 1024,
        include_qasm: Annotated[bool, Field(description="Also return the trained circuit as OpenQASM 2.0 for real quantum hardware")] = False,
    ) -> CallToolResult:
        """Solve a factory decision with the Quantum Approximate Optimization Algorithm. Returns the decision in
        plain terms, how close it is to the proven optimum, and a post-quantum signed attestation (Ed25519 +
        ML-DSA-87) that is anchored on chain (the Privi Devnet). Free."""
        if not limiter.allow(_who(ctx)):
            return _result({"error": f"rate limit: {settings.rate_per_min} optimizations per minute"}, is_error=True)
        try:
            qubo, decode = qaoa.build(problem, data)
            r = await anyio.to_thread.run_sync(lambda: qaoa.solve(qubo, layers=layers, shots=shots), limiter=cpu)
        except qaoa.ProblemError as e:
            return _result({"error": str(e)}, is_error=True)
        decision = decode(r["solution"])
        exact_decision = decode(r["exact"]["solution"])
        problem_sha = hashlib.sha256(json.dumps({"problem": problem, "data": data}, sort_keys=True,
                                                default=str).encode()).hexdigest()
        body = {"problem": problem, "problem_sha256": problem_sha, "qubits": r["qubits"], "layers": layers,
                "algorithm": r["algorithm"], "decision": decision, "cost": r["cost"],
                "found_optimum": r["found_optimum"], "approximation_ratio": r["approximation_ratio"],
                "exact_optimum_cost": r["exact"]["cost"], "angles": r["angles"], "backend": "local-statevector"}
        att = await anyio.to_thread.run_sync(attestor.issue, "quantum_optimization", body)
        out = {
            "decision": decision,
            "quality": {"found_optimum": r["found_optimum"], "approximation_ratio": r["approximation_ratio"],
                        "probability_of_optimum": r["probability_of_optimum"],
                        "random_guess_probability": r["random_guess_probability_of_optimum"],
                        "quantum_amplification": r["amplification"]},
            "classical_check": {"optimum_cost": r["exact"]["cost"], "method": r["exact"]["method"],
                                "same_as_quantum": r["found_optimum"],
                                **({} if r["found_optimum"] else {"optimal_decision": exact_decision})},
            "quantum_run": {k: r[k] for k in ("algorithm", "qubits", "shots", "angles", "top_samples",
                                               "objective_evaluations", "runtime_ms")},
            "attestation": {"id": att["id"], "body_sha256": att["body_sha256"], "signatures": f"Ed25519 + {PQ_ALG}",
                            "anchoring": "queued for anchoring on the Privi Devnet" if anchor_client else "anchoring not configured",
                            **links(att["id"])},
            "note": "Exact simulation; at this size classical solvers match it. The same circuit runs on quantum "
                    "hardware via the OpenQASM export.",
            "copyright": COPYRIGHT,
        }
        if include_qasm:
            out["openqasm"] = qaoa.to_qasm(qubo, r["angles"]["gamma"], r["angles"]["beta"],
                                           r["cost_normalization"]["min"], r["cost_normalization"]["span"])
        return _result(out)

    @mcp.tool(title="Verify a Privi Quantum attestation", annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
    async def quantum_verify(
        attestation_id: Annotated[str | None, Field(description="An attestation id (qa_...) issued by this server")] = None,
        attestation: Annotated[dict[str, Any] | None, Field(description="Or a full attestation object (from GET /attestations/<id>) to check offline")] = None,
    ) -> CallToolResult:
        """Check both post-quantum signatures, the body hash, and the on-chain anchor of a result. Free."""
        att = attestation or (attestor.get(attestation_id) if attestation_id else None)
        if not att:
            return _result({"error": "give an attestation_id issued here or a full attestation"}, is_error=True)
        v = Attestor.verify(att, keys["ed25519"], keys["ml_dsa_87"])
        out: dict[str, Any] = {"id": att.get("id"), **v, "signing_key_id": keys["key_id"]}
        anc = att.get("anchor") or ((attestor.get(att.get("id", "")) or {}).get("anchor"))
        if not anc:
            out["anchor"] = {"verified": False, "reason": "not anchored yet (batches go out every few minutes)"}
        elif anchor_client is None:
            out["anchor"] = {**anc, "verified": None, "reason": "chain check not configured on this server"}
        else:
            try:
                chk = await anyio.to_thread.run_sync(anchor_client.verify, att["body_sha256"], anc["tx_hash"], anc["proof"])
                out["anchor"] = {"verified": bool(chk.get("verified")), "tx_hash": anc["tx_hash"],
                                 "block_number": chk.get("block_number"), "block_time_utc": chk.get("block_time_utc"),
                                 "chain_id": chk.get("chain_id"), **({"reason": chk["reason"]} if chk.get("reason") else {})}
            except AnchorError as e:
                out["anchor"] = {**anc, "verified": None, "reason": f"could not reach the chain checker: {e}"}
        return _result(out)

    @mcp.tool(title="Scan code for quantum-vulnerable crypto", annotations=READ_ONLY)
    def pqc_scan_code(
        code: Annotated[str, Field(description="Source code or config text to scan (max 200 KB)")],
        filename: Annotated[str, Field(description="Optional file name, used in the report")] = "input",
    ) -> CallToolResult:
        """Find RSA, elliptic-curve, Diffie-Hellman, DSA, weak hashes and 128-bit ciphers that quantum
        computers break or weaken; returns a 0-100 readiness score and a fix per finding. Nothing is stored."""
        if len(code.encode()) > 200_000:
            return _result({"error": "code is larger than 200 KB"}, is_error=True)
        return _result(scanner.scan_text(code, filename))

    def make_package(organization: str, assets: list[dict] | None, files: list[dict] | None, profile: str,
                     pqc_lead: str = "", system_name: str = "", impact: str = "unknown", hva: bool = False) -> dict[str, Any]:
        assets = list(assets or [])
        scan = None
        files = files or []
        if len(files) > 50:
            raise ValueError("send at most 50 files per package")
        if sum(len(str(f.get("content", "")).encode()) for f in files) > 1_000_000:
            raise ValueError("files are larger than 1 MB in total")
        if files:
            merged: dict[str, Any] = {"findings": [], "files_scanned": 0}
            for f in files:
                r = scanner.scan_text(str(f.get("content", "")), str(f.get("name") or "file")[:200])
                merged["findings"] += r["findings"]
                merged["files_scanned"] += 1
            sev = [x["severity"] for x in merged["findings"]]
            pen = sum(scanner.WEIGHT[x] for x in sev)
            merged["readiness_score"] = max(0, round(100 - pen * 100 / (pen + 40))) if pen else 100
            scan = merged
            assets += govpqc.assets_from_scan(scan, system_name or "Scanned code", impact, hva)
        if not assets:
            raise ValueError("give code files to scan and/or a list of cryptographic assets")
        if len(assets) > 1000:
            raise ValueError("at most 1000 assets per package")
        pkg = govpqc.build_package({"name": organization, "pqc_lead": pqc_lead}, assets, profile, scan)
        att = attestor.issue("pqc_readiness", {"organization": pkg["organization"]["name"], "profile": pkg["profile"],
                                               "summary": pkg["summary"], "cbom_sha256": pkg["cbom_sha256"],
                                               "package_body": pkg, "copyright": COPYRIGHT})
        aid = att["id"]
        return {"package_id": aid, "summary": pkg["summary"],
                "top_priorities": [{k: a[k] for k in ("priority", "system", "asset", "algorithm", "deadline", "action")}
                                   for a in pkg["assets"][:10]],
                "plan_elements": [{k: x[k] for k in ("element", "name", "status")} for x in pkg["plan_elements"]] if pkg["plan_elements"] else None,
                "contractor_readiness": pkg.get("contractor_readiness"),
                "report_url": f"{PUBLIC_URL}/reports/{aid}", "cbom_url": f"{PUBLIC_URL}/reports/{aid}.cbom.json",
                "signed_package_url": f"{PUBLIC_URL}/reports/{aid}.json", "cbom_sha256": pkg["cbom_sha256"],
                "signatures": f"Ed25519 + {PQ_ALG}",
                "anchoring": "queued for the Privi Devnet (every few minutes); quantum_verify checks it" if anchor_client else "anchoring not configured",
                "caveats": pkg["caveats"]}

    @mcp.tool(title="Post-quantum readiness package (government)", annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False))
    def pqc_readiness_package(
        organization: Annotated[str, Field(description="Agency, office or company name")],
        ctx: Context,
        assets: Annotated[list[dict[str, Any]] | None, Field(description=(
            "Cryptographic assets: [{system, asset, algorithm, usage (key_establishment|signature|encryption|tls|ssh|vpn|"
            "code_signing|certificate|hash|other), protocol (e.g. 'TLS 1.2'), impact (high|moderate|low), hva (bool), "
            "sensitive_past_2030 (bool), owner, vendor, status, cnsa_category}]"))] = None,
        files: Annotated[list[dict[str, str]] | None, Field(description="Code or config files to scan: [{name, content}] (up to 50 files, 1 MB)")] = None,
        profile: Annotated[str, Field(description="agency (OMB M-26-15) | contractor (EO 14409 FAR items) | nss_vendor (NSA CNSA 2.0)")] = "agency",
        pqc_lead: Annotated[str, Field(description="Name of the PQC Migration Lead (M-26-15 governance)")] = "",
        system_name: Annotated[str, Field(description="System the scanned files belong to")] = "",
        impact: Annotated[str, Field(description="FIPS 199 impact of that system: high | moderate | low")] = "unknown",
        hva: Annotated[bool, Field(description="Is that system a High Value Asset (M-19-03)?")] = False,
    ) -> CallToolResult:
        """Build a signed post-quantum readiness package: prioritized migration list with the federal deadline for
        each asset (EO 14409, OMB M-26-15, NIST IR 8547 draft, CNSA 2.0), the nine M-26-15 plan elements marked as
        evidence or gaps, and a CycloneDX 1.6 CBOM. Signed with ML-DSA-87, anchored on chain, public report URL. Free."""
        if not limiter.allow(_who(ctx)):
            return _result({"error": f"rate limit: {settings.rate_per_min} calls per minute"}, is_error=True)
        try:
            return _result(make_package(organization, assets, files, profile, pqc_lead, system_name, impact, hva))
        except ValueError as ex:
            return _result({"error": str(ex)}, is_error=True)

    @mcp.tool(title="Federal post-quantum deadlines", annotations=READ_ONLY)
    def pqc_federal_deadlines() -> dict[str, Any]:
        """The U.S. federal post-quantum timeline (EO 14409, OMB M-26-15, NIST IR 8547 draft, NSA CNSA 2.0), the
        approved replacement algorithms, and links to the sources. Free."""
        return govpqc.deadlines_reference()

    # ---------------- http ----------------

    cors = {"Access-Control-Allow-Origin": "*"}

    @mcp.custom_route("/health", methods=["GET"], include_in_schema=False)
    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"ok": True, "service": "privi-quantum", "version": __version__}, headers=cors)

    @mcp.custom_route("/status", methods=["GET"], include_in_schema=False)
    async def status(_: Request) -> JSONResponse:
        return JSONResponse(quantum_status(), headers=cors)

    @mcp.custom_route("/keys", methods=["GET"], include_in_schema=False)
    async def public_keys(_: Request) -> JSONResponse:
        return JSONResponse({**keys, "issuer": "Privi Quantum (Privi World Co)", "copyright": COPYRIGHT},
                            headers={**cors, "Cache-Control": "public, max-age=3600"})

    @mcp.custom_route("/attestations/{aid}", methods=["GET"], include_in_schema=False)
    async def get_attestation(request: Request) -> JSONResponse:
        att = attestor.get(request.path_params["aid"])
        if not att:
            return JSONResponse({"error": "not found"}, status_code=404, headers=cors)
        return JSONResponse(att, headers=cors)

    @mcp.custom_route("/reports/{aid}.cbom.json", methods=["GET"], include_in_schema=False)
    async def report_cbom(request: Request) -> Response:
        att = attestor.get(request.path_params["aid"])
        if not att or att["body"].get("kind") != "pqc_readiness":
            return JSONResponse({"error": "not found"}, status_code=404, headers=cors)
        return Response(json.dumps(att["body"]["package_body"]["cbom"], indent=2), media_type="application/vnd.cyclonedx+json",
                        headers={**cors, "Content-Disposition": f'attachment; filename="{att["id"]}.cbom.json"'})

    @mcp.custom_route("/reports/{aid}.json", methods=["GET"], include_in_schema=False)
    async def report_json(request: Request) -> JSONResponse:
        att = attestor.get(request.path_params["aid"])
        if not att or att["body"].get("kind") != "pqc_readiness":
            return JSONResponse({"error": "not found"}, status_code=404, headers=cors)
        return JSONResponse(att, headers=cors)

    @mcp.custom_route("/reports/{aid}", methods=["GET"], include_in_schema=False)
    async def report_page(request: Request) -> Response:
        att = attestor.get(request.path_params["aid"])
        if not att or att["body"].get("kind") != "pqc_readiness":
            return HTMLResponse("<h1>Report not found</h1>", status_code=404)
        v = Attestor.verify(att, keys["ed25519"], keys["ml_dsa_87"])
        return HTMLResponse(govreport.render(att, v, PUBLIC_URL), headers={"Cache-Control": "no-store"})

    @mcp.custom_route("/api/pqc/package", methods=["POST", "OPTIONS"], include_in_schema=False)
    async def api_package(request: Request) -> JSONResponse:
        """Browser endpoint for the agency demo on gov.priviflow.us (same logic as the MCP tool)."""
        pre = {**cors, "Access-Control-Allow-Methods": "POST, OPTIONS", "Access-Control-Allow-Headers": "content-type"}
        if request.method == "OPTIONS":
            return JSONResponse({}, headers=pre)
        ip = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "web")).split(",")[0]
        if not limiter.allow(hashlib.sha256(ip.encode()).hexdigest()[:12]):
            return JSONResponse({"error": "rate limited, try again in a minute"}, status_code=429, headers=pre)
        try:
            raw = await request.body()
            if len(raw) > 1_200_000:
                return JSONResponse({"error": "request too large"}, status_code=413, headers=pre)
            b = json.loads(raw or b"{}")
            out = await anyio.to_thread.run_sync(lambda: make_package(
                str(b.get("organization") or "Demo agency")[:160], b.get("assets"), b.get("files"),
                str(b.get("profile") or "agency"), str(b.get("pqc_lead") or "")[:120], str(b.get("system_name") or "")[:120],
                str(b.get("impact") or "unknown"), bool(b.get("hva"))))
            return JSONResponse(out, headers=pre)
        except (ValueError, json.JSONDecodeError, AttributeError, TypeError) as ex:
            return JSONResponse({"error": str(ex)}, status_code=400, headers=pre)

    @mcp.custom_route("/api/pqc/deadlines", methods=["GET"], include_in_schema=False)
    async def api_deadlines(_: Request) -> JSONResponse:
        return JSONResponse(govpqc.deadlines_reference(), headers={**cors, "Cache-Control": "public, max-age=3600"})

    @mcp.custom_route("/.well-known/glama.json", methods=["GET"], include_in_schema=False)
    async def glama(_: Request) -> JSONResponse:
        return JSONResponse({"$schema": "https://glama.ai/mcp/schemas/server.json", "maintainers": ["canoydario847-cloud"]})

    @mcp.custom_route("/.well-known/mcp/server-card.json", methods=["GET"], include_in_schema=False)
    async def server_card(_: Request) -> JSONResponse:
        tools = [t.model_dump(by_alias=True, exclude_none=True) for t in await mcp.list_tools()]
        return JSONResponse({"serverInfo": {"name": "privi-quantum", "title": "Privi Quantum", "version": __version__,
                                            "description": "Quantum optimization for manufacturing with post-quantum signed, chain-anchored results.",
                                            "websiteUrl": "https://privi-hub.onrender.com"},
                             "authentication": {"required": False, "schemes": []},
                             "tools": tools, "resources": [], "prompts": []},
                            headers={**cors, "Cache-Control": "public, max-age=3600"})

    @mcp.custom_route("/", methods=["GET"], include_in_schema=False)
    async def root(_: Request) -> Response:
        return Response(LANDING.format(url=PUBLIC_URL, qubits=qaoa.MAX_QUBITS, copyright=COPYRIGHT),
                        media_type="text/html; charset=utf-8")

    mcp._privi_attestor = attestor  # used by main() for the anchoring loop
    mcp._privi_anchor = anchor_client
    return mcp


LANDING = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Privi Quantum</title><style>body{{font:16px/1.55 system-ui,sans-serif;max-width:680px;margin:48px auto;padding:0 16px;color:#16181d;background:#f7f8fa}}
code,pre{{font:14px ui-monospace,monospace;background:#eef1f6;border-radius:6px}}pre{{padding:12px;overflow-x:auto}}code{{padding:1px 4px}}
a{{color:#3451b2}}@media (prefers-color-scheme:dark){{body{{color:#e8eaee;background:#0f1115}}code,pre{{background:#1d222b}}a{{color:#8ea6ff}}}}</style></head><body>
<h1>Privi Quantum</h1>
<p>Quantum optimization for factory decisions (CVaR-QAOA, up to {qubits} qubits): balance production lines, choose which lots to inspect,
split conflicting jobs across shifts. Every answer is checked against the proven classical optimum, signed with Ed25519 + ML-DSA-87
(NIST FIPS 204) so not even a quantum computer can forge it, and anchored on chain (the Privi Devnet, until the Privi mainnet). The trained circuit exports as
OpenQASM for IBM, Amazon Braket and Azure quantum hardware.</p>
<p>Connect your AI agent (MCP, streamable HTTP, free):</p>
<pre>{{ "mcpServers": {{ "privi-quantum": {{ "url": "{url}/mcp" }} }} }}</pre>
<p>Tools: <code>quantum_optimize</code>, <code>quantum_problems</code>, <code>quantum_verify</code>, <code>pqc_scan_code</code>,
<code>pqc_readiness_package</code>, <code>pqc_federal_deadlines</code>, <code>quantum_status</code>.</p>
<p>For agencies and contractors: a signed post-quantum readiness package (EO 14409, OMB M-26-15, CycloneDX 1.6 CBOM)
in one call. Try the 10-minute demo at <a href="https://gov.priviflow.us/demo.html">gov.priviflow.us/demo.html</a>.
Public signing keys: <a href="{url}/keys">/keys</a>. Status: <a href="{url}/status">/status</a>.</p>
<p>Built by Privi World Co, Port Huron, Michigan. <a href="https://privi-hub.onrender.com">Everything Privi offers</a> ·
<a href="mailto:dariocanoy@priviflow.us">dariocanoy@priviflow.us</a></p>
<p><small>{copyright}</small></p></body></html>"""


def _anchor_loop(attestor: Attestor, client, interval: int) -> None:
    while True:
        time.sleep(interval)
        try:
            n = anchor_pending(attestor, client)
            if n:
                print(f"[privi-quantum] anchored {n} attestations on chain (the Privi Devnet)", flush=True)
        except Exception as e:  # keep serving; retry next round
            print(f"[privi-quantum] anchoring failed, will retry: {e}", flush=True)


def main() -> None:
    p = argparse.ArgumentParser(description="Privi Quantum MCP server")
    p.add_argument("--stdio", action="store_true")
    p.add_argument("--host", default=os.getenv("HOST", "0.0.0.0"))
    p.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000")))
    args = p.parse_args()
    settings = Settings.from_env()
    mcp = build_server(settings)
    if mcp._privi_anchor is not None:
        threading.Thread(target=_anchor_loop, args=(mcp._privi_attestor, mcp._privi_anchor, settings.anchor_interval),
                         daemon=True).start()
    if args.stdio:
        mcp.run("stdio")
        return
    import uvicorn
    from .front import QuickGet
    uvicorn.run(QuickGet(mcp.streamable_http_app(host=args.host, stateless_http=True, json_response=True),
                         "Privi Quantum", "privi-quantum", PUBLIC_URL), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
