# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Quantum - https://priviflow.us - dariocanoy@priviflow.us
"""Privi Quantum MCP server: quantum optimization for factories, sealed with
post-quantum signatures and anchored on chain (Base).

Free:  quantum_status, quantum_problems, quantum_optimize, quantum_verify, pqc_scan_code,
       pqc_endpoint_check, pqc_readiness_package, pqc_federal_deadlines
       (government / contractor post-quantum readiness)
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
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

from . import govpqc, govreport, pqctls, qaoa, scanner
from .dream import BENCHMARK, MODES, DreamError, DreamScape, DreamWeaver, Privilege
from .accelerator import LEVEL_LABEL, STEPS, Accelerator, AcceleratorError, badge_svg
from .inspector import LEVELS as INSPECTOR_LEVELS, Inspector, credential_message
from .anchoring import AnchorError, HttpAnchorClient, anchor_pending
from .attest import PQ_ALG, Attestor

__version__ = "0.4.0"
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
6. pqc_endpoint_check tests up to 20 public sites or services (e.g. www.agency.gov) for TLS 1.3 and
   hybrid post-quantum key exchange (X25519MLKEM768) and returns CBOM-ready assets; pass
   `endpoints` to pqc_readiness_package to check them and add them to the package in one call.
7. The Privi quantum realm: privilege_directory lists every quantum realm (engines here and other
   Privi Quantum nodes) ranked by measured speed to the proven optimum. dreamweaver_run races one
   job across several realms: mode "first" returns the first valid answer, "best" the best one by
   the deadline. dreamscape_open gives you a private Dream Scape workspace (scape_id + scape_key)
   that keeps your jobs; dreamscape_submit runs a job there, and the WebSocket /dreamscape/ws runs
   many jobs at once and streams each realm's progress.
8. Quantum Agent Accelerator: any AI agent can upgrade to a certified quantum agent here. qagent_enroll
   with an ML-DSA public key, then qagent_scan (Q1), qagent_challenge + qagent_prove (Q2), qagent_scan with
   endpoints (Q3), qagent_quantum_task + qagent_quantum_proof (Q4). Before trusting another agent, look it up
   in the Quantum Agent Directory (qagent_directory, free) and check what it signed with qagent_verify (free).
9. Privi Inspector guards the quantum realm: Dream Weaver and Dream Scape need a Privi pass. Sign
   'privi-inspector:v1:<agent_id>:<unix seconds>:<nonce>' with your enrolled ML-DSA key and call
   inspector_pass. Agents that are unknown, revoked, uncertified, outdated or below the required level are
   intercepted with the fix. Other services can use the same checkpoint (inspector_check) and the patrol's
   watchlist of revoked, outdated and impersonated agents (inspector_watchlist).

All tools are free. Privi is built by Dario Canoy (Privi World Co, Port Huron, Michigan).
For the other Privi tools, pilots, partnerships, manufacturing or government work, see
https://privi-discovery.onrender.com/llms.txt. {COPYRIGHT}"""

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
PASS_ARG = Field(description="Your Privi pass (ppass_...) from inspector_pass; the quantum realm requires one")


@dataclass
class Settings:
    db_path: str = "quantum.db"
    signing_seed: str = ""
    anchor_url: str = "https://privi-anchor.onrender.com/mcp"
    anchor_api_key: str = ""
    anchor_interval: int = 300
    rate_per_min: int = 20
    max_concurrent: int = 2
    admin_key: str = ""
    dream_nodes: str = ""
    dream_allow_private: bool = False
    inspector_mode: str = "enforce"
    inspector_min_level: str = "quantum_safe_identity"
    inspector_min_key: str = "ML-DSA-44"
    inspector_patrol_minutes: int = 60

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
            admin_key=os.getenv("QUANTUM_ADMIN_KEY", ""),
            dream_nodes=os.getenv("DREAMWEAVER_NODES", ""),
            dream_allow_private=os.getenv("DREAMWEAVER_ALLOW_PRIVATE") == "1",
            inspector_mode=os.getenv("INSPECTOR_MODE", "enforce"),
            inspector_min_level=os.getenv("INSPECTOR_MIN_LEVEL", "quantum_safe_identity"),
            inspector_min_key=os.getenv("INSPECTOR_MIN_KEY", "ML-DSA-44"),
            inspector_patrol_minutes=int(os.getenv("INSPECTOR_PATROL_MINUTES", "60")),
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
                 anchor_client=None, endpoint_checker=None) -> MCPServer:
    settings = settings or Settings.from_env()
    attestor = attestor or Attestor(settings.db_path, settings.signing_seed)
    if anchor_client is None and settings.anchor_api_key:
        anchor_client = HttpAnchorClient(settings.anchor_url, settings.anchor_api_key)
    limiter = RateLimiter(settings.rate_per_min)
    check_endpoints = endpoint_checker or pqctls.check_endpoints
    cpu = anyio.CapacityLimiter(settings.max_concurrent)
    keys = attestor.public_keys()
    privilege = Privilege(settings.db_path, settings.dream_nodes, settings.dream_allow_private)
    weaver = DreamWeaver(privilege, attestor, anyio.CapacityLimiter(settings.max_concurrent))
    scapes = DreamScape(privilege, weaver)
    accel = Accelerator(settings.db_path, attestor, PUBLIC_URL)
    inspector = Inspector(settings.db_path, accel, settings.inspector_mode, settings.inspector_min_level,
                          settings.inspector_min_key)
    scapes.gate = inspector.check_pass
    sweep_state: dict[str, float | None] = {"last": None}

    def realm_gate(ctx: Context, privi_pass: str | None, scope: str) -> CallToolResult | None:
        """Privi Inspector: intercept agents without a valid, current certificate before they enter the realm."""
        tok = privi_pass or ((ctx.headers or {}).get("x-privi-pass") if ctx.headers is not None else None)
        v = inspector.check_pass(tok, scope)
        if v["allowed"]:
            return None
        return _result({"error": "intercepted by Privi Inspector", "reasons": v.get("reasons"), "fixes": v.get("fixes"),
                        "required_level": v.get("required_level_label"), "agent_id": v.get("agent_id") or None,
                        "get_a_pass": inspector.policy()["credential"] + " -> inspector_pass",
                        "join": f"{PUBLIC_URL}/accelerator"}, is_error=True)

    bench_state: dict[str, float | None] = {"last": None}

    mcp = MCPServer(
        name="privi-quantum", title="Privi Quantum",
        description="Quantum optimization (CVaR-QAOA) for manufacturing decisions, with post-quantum "
                    "signed results anchored on chain (Base, until the Privi chain mainnet), plus a quantum-vulnerability scanner.",
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
                "anchoring": {"enabled": anchor_client is not None, "chain": "Base via Privi Anchor (until the Privi chain mainnet)",
                              "interval_seconds": settings.anchor_interval},
                "attestations_issued": attestor.count(), "public_keys_url": f"{PUBLIC_URL}/keys",
                "quantum_realm": {"dream_scape": f"{PUBLIC_URL}/dreamscape", "privilege": f"{PUBLIC_URL}/privilege",
                                  "realms": len(privilege.active()),
                                  "websocket": PUBLIC_URL.replace("https://", "wss://") + "/dreamscape/ws"}}

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
        ML-DSA-87) that is anchored on chain (Base). Free."""
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
                            "anchoring": "queued for anchoring on Base" if anchor_client else "anchoring not configured",
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
                     pqc_lead: str = "", system_name: str = "", impact: str = "unknown", hva: bool = False,
                     endpoints: list[str] | None = None) -> dict[str, Any]:
        assets = list(assets or [])
        endpoint_summary = None
        if endpoints:
            if len(endpoints) > pqctls.MAX_HOSTS:
                raise ValueError(f"check at most {pqctls.MAX_HOSTS} endpoints per package")
            checked = check_endpoints([str(x) for x in endpoints])
            endpoint_summary = checked["summary"]
            for r in checked["results"]:
                if r.get("asset"):
                    assets.append({**r["asset"], "impact": impact, "hva": hva})
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
            raise ValueError("give code files to scan, public endpoints to check and/or a list of cryptographic assets")
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
                "endpoint_check": endpoint_summary,
                "report_url": f"{PUBLIC_URL}/reports/{aid}", "cbom_url": f"{PUBLIC_URL}/reports/{aid}.cbom.json",
                "signed_package_url": f"{PUBLIC_URL}/reports/{aid}.json", "cbom_sha256": pkg["cbom_sha256"],
                "signatures": f"Ed25519 + {PQ_ALG}",
                "anchoring": "queued for the next on-chain anchor batch (every few minutes); quantum_verify checks it" if anchor_client else "anchoring not configured",
                "caveats": pkg["caveats"]}

    @mcp.tool(title="Post-quantum readiness package (government)", annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False))
    async def pqc_readiness_package(
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
        endpoints: Annotated[list[str] | None, Field(description="Public hostnames to check live for TLS 1.3 and hybrid post-quantum key exchange (up to 20), e.g. ['www.agency.gov']")] = None,
    ) -> CallToolResult:
        """Build a signed post-quantum readiness package: prioritized migration list with the federal deadline for
        each asset (EO 14409, OMB M-26-15, NIST IR 8547 draft, CNSA 2.0), the nine M-26-15 plan elements marked as
        evidence or gaps, and a CycloneDX 1.6 CBOM. Signed with ML-DSA-87, anchored on chain, public report URL. Free."""
        if not limiter.allow(_who(ctx)):
            return _result({"error": f"rate limit: {settings.rate_per_min} calls per minute"}, is_error=True)
        try:
            return _result(await anyio.to_thread.run_sync(lambda: make_package(
                organization, assets, files, profile, pqc_lead, system_name, impact, hva, endpoints)))
        except ValueError as ex:
            return _result({"error": str(ex)}, is_error=True)

    @mcp.tool(title="Check public endpoints for post-quantum TLS", annotations=ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True))
    async def pqc_endpoint_check(
        endpoints: Annotated[list[str], Field(description="Public hostnames or URLs (up to 20), optionally with a TLS port, e.g. ['www.irs.gov', 'login.gov:443']")],
        ctx: Context,
    ) -> CallToolResult:
        """Test live public sites and services for TLS 1.3 and hybrid post-quantum key exchange (X25519MLKEM768,
        FIPS 203), the protection against 'harvest now, decrypt later'. Sends two TLS hellos per endpoint and no data.
        Returns a status and fix per endpoint plus CBOM-ready assets for pqc_readiness_package. Free."""
        if not limiter.allow(_who(ctx)):
            return _result({"error": f"rate limit: {settings.rate_per_min} calls per minute"}, is_error=True)
        if not endpoints:
            return _result({"error": "give at least one hostname"}, is_error=True)
        if len(endpoints) > pqctls.MAX_HOSTS:
            return _result({"error": f"at most {pqctls.MAX_HOSTS} endpoints per call"}, is_error=True)
        return _result(await anyio.to_thread.run_sync(lambda: check_endpoints([str(x) for x in endpoints])))

    @mcp.tool(title="Federal post-quantum deadlines", annotations=READ_ONLY)
    def pqc_federal_deadlines() -> dict[str, Any]:
        """The U.S. federal post-quantum timeline (EO 14409, OMB M-26-15, NIST IR 8547 draft, NSA CNSA 2.0), the
        approved replacement algorithms, and links to the sources. Free."""
        return govpqc.deadlines_reference()

    # ---------------- http ----------------

    cors = {"Access-Control-Allow-Origin": "*"}

    # ---------------- the Privi quantum realm: Privilege, Dream Weaver, Dream Scape ----------------

    def _weave_err(e: Exception) -> CallToolResult:
        return _result({"error": str(e)}, is_error=True)

    @mcp.tool(title="Privilege: quantum realm directory", annotations=READ_ONLY)
    def privilege_directory() -> CallToolResult:
        """Every quantum realm Privi can run a job on (engines on this server and other Privi Quantum nodes),
        ranked by expected time to the proven optimum, with latency, optimum rate, wins and status. Free."""
        return _result(privilege.directory())

    @mcp.tool(title="Privilege: benchmark the realms", annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                                                                  idempotentHint=False, openWorldHint=True))
    async def privilege_benchmark(
        ctx: Context,
        privi_pass: Annotated[str | None, PASS_ARG] = None,
    ) -> CallToolResult:
        """Run the standard 8-qubit benchmark on every active realm at once and update Privilege's speed
        rankings. At most once every 2 minutes for everyone. Requires a Privi pass. Free."""
        if blocked := realm_gate(ctx, privi_pass, "privilege_benchmark"):
            return blocked
        now = time.monotonic()
        if bench_state["last"] is not None and now - bench_state["last"] < 120:
            return _result({"error": "a benchmark ran less than 2 minutes ago; try again shortly",
                            "directory": privilege.directory()}, is_error=True)
        bench_state["last"] = now
        try:
            r = await weaver.weave(BENCHMARK[0], BENCHMARK[1], layers=2, shots=512, mode="best",
                                   fanout=8, deadline_s=60, benchmark=True)
        except (DreamError, qaoa.ProblemError) as e:
            return _weave_err(e)
        return _result({"benchmark": {k: r.get(k) for k in ("ok", "total_ms", "attempts", "winner")},
                        "directory": privilege.directory()})

    @mcp.tool(title="Dream Weaver: race a quantum job across realms", annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True))
    async def dreamweaver_run(
        problem: Annotated[str, Field(description="balance_lines | select_lots | split_conflicts | qubo (see quantum_problems)")],
        data: Annotated[dict[str, Any], Field(description="Problem data in the shape quantum_problems describes")],
        ctx: Context,
        mode: Annotated[str, Field(description="first = fastest valid answer wins; best = best answer by the deadline")] = "first",
        fanout: Annotated[int, Field(description="How many realms to use (1-8), fastest first", ge=1, le=8)] = 3,
        hedge_ms: Annotated[int, Field(description="first mode: start the top realm alone, add the others after this many ms "
                                                   "(or as soon as one fails). 0 = all at once", ge=0, le=10000)] = 0,
        layers: Annotated[int, Field(description="QAOA depth p (1-4)", ge=1, le=4)] = 2,
        shots: Annotated[int, Field(description="Measurements (1-100000)", ge=1, le=100000)] = 1024,
        deadline_s: Annotated[float, Field(description="Give up after this many seconds (1-120)", ge=1, le=120)] = 30,
        realms: Annotated[list[str] | None, Field(description="Only these realm_ids (from privilege_directory)")] = None,
        privi_pass: Annotated[str | None, PASS_ARG] = None,
    ) -> CallToolResult:
        """Run one quantum optimization on several realms at once and return the winning answer, every realm's
        timing, and a post-quantum signed attestation (Ed25519 + ML-DSA-87) anchored on chain. Free."""
        if blocked := realm_gate(ctx, privi_pass, "dreamweaver_run"):
            return blocked
        if not limiter.allow(_who(ctx)):
            return _result({"error": f"rate limit: {settings.rate_per_min} jobs per minute"}, is_error=True)
        if mode not in MODES:
            return _result({"error": "mode must be first or best"}, is_error=True)
        try:
            r = await weaver.weave(problem, data, layers=layers, shots=shots, mode=mode, fanout=fanout,
                                   hedge_ms=hedge_ms, deadline_s=deadline_s, realms=realms)
        except (DreamError, qaoa.ProblemError) as e:
            return _weave_err(e)
        if r.get("ok"):
            r["attestation"].update(links(r["attestation"]["id"]))
        return _result(r, is_error=not r.get("ok"))

    @mcp.tool(title="Dream Scape: open a workspace", annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                                                                idempotentHint=False, openWorldHint=False))
    def dreamscape_open(
        name: Annotated[str, Field(description="A name for your workspace, e.g. 'Plant 2 scheduling'")],
        ctx: Context,
        privi_pass: Annotated[str | None, PASS_ARG] = None,
    ) -> CallToolResult:
        """Open a private Dream Scape: your own quantum environment that keeps every job and result. Returns
        scape_id and scape_key (shown once; keep it). Free."""
        if blocked := realm_gate(ctx, privi_pass, "dreamscape_open"):
            return blocked
        if not limiter.allow(_who(ctx)):
            return _result({"error": "rate limit; try again in a minute"}, is_error=True)
        try:
            sc = scapes.open(name)
        except DreamError as e:
            return _weave_err(e)
        ws = PUBLIC_URL.replace("https://", "wss://").replace("http://", "ws://") + "/dreamscape/ws"
        return _result({**sc, "websocket": ws,
                        "next": "Call dreamscape_submit with scape_id and scape_key, or open the WebSocket and send "
                                "{\"type\":\"auth\",\"scape_id\":...,\"key\":...} then weave frames."})

    @mcp.tool(title="Dream Scape: run a job", annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                                                         idempotentHint=False, openWorldHint=True))
    async def dreamscape_submit(
        scape_id: Annotated[str, Field(description="Your Dream Scape id (scape_...)")],
        scape_key: Annotated[str, Field(description="Its key (dsk_...)")],
        problem: Annotated[str, Field(description="balance_lines | select_lots | split_conflicts | qubo")],
        data: Annotated[dict[str, Any], Field(description="Problem data (see quantum_problems)")],
        ctx: Context,
        mode: Annotated[str, Field(description="first or best")] = "first",
        fanout: Annotated[int, Field(ge=1, le=8)] = 3,
        hedge_ms: Annotated[int, Field(ge=0, le=10000)] = 0,
        layers: Annotated[int, Field(ge=1, le=4)] = 2,
        shots: Annotated[int, Field(ge=1, le=100000)] = 1024,
        deadline_s: Annotated[float, Field(ge=1, le=120)] = 30,
        privi_pass: Annotated[str | None, PASS_ARG] = None,
    ) -> CallToolResult:
        """Run a quantum job in your Dream Scape through Dream Weaver and keep the result there. Free."""
        if blocked := realm_gate(ctx, privi_pass, "dreamscape_submit"):
            return blocked
        if not scapes.auth(scape_id, scape_key):
            return _result({"error": "wrong scape_id or scape_key"}, is_error=True)
        if not limiter.allow(_who(ctx)):
            return _result({"error": f"rate limit: {settings.rate_per_min} jobs per minute"}, is_error=True)
        r = await scapes.submit(scape_id, {"problem": problem, "data": data, "mode": mode, "fanout": fanout,
                                           "hedge_ms": hedge_ms, "layers": layers, "shots": shots, "deadline_s": deadline_s})
        if r.get("attestation"):
            r["attestation"].update(links(r["attestation"]["id"]))
        return _result(r, is_error=r["status"] != "done")

    @mcp.tool(title="Dream Scape: jobs", annotations=READ_ONLY)
    def dreamscape_jobs(
        ctx: Context,
        scape_id: Annotated[str, Field(description="Your Dream Scape id")],
        scape_key: Annotated[str, Field(description="Its key")],
        job_id: Annotated[str | None, Field(description="One job in full; omit for the recent list")] = None,
        limit: Annotated[int, Field(ge=1, le=100)] = 20,
        privi_pass: Annotated[str | None, PASS_ARG] = None,
    ) -> CallToolResult:
        """Your Dream Scape's recent jobs, or one job with its full result. Free."""
        if blocked := realm_gate(ctx, privi_pass, "dreamscape_jobs"):
            return blocked
        if not scapes.auth(scape_id, scape_key):
            return _result({"error": "wrong scape_id or scape_key"}, is_error=True)
        if job_id:
            j = scapes.job(scape_id, job_id)
            return _result(j) if j else _result({"error": "job not found"}, is_error=True)
        return _result({"scape_id": scape_id, "jobs": scapes.jobs(scape_id, limit)})

    # ---------------- Quantum Agent Accelerator + Quantum Agent Directory ----------------

    def _qa(fn, *a):
        try:
            return _result(fn(*a))
        except AcceleratorError as e:
            return _result({"error": str(e)}, is_error=True)

    @mcp.tool(title="Quantum Agent Accelerator: how it works", annotations=READ_ONLY)
    def accelerator_info() -> CallToolResult:
        """The program that upgrades an AI agent into a certified quantum agent: the four steps (Q1-Q4), the
        levels, how to make an ML-DSA key in five lines, and the free directory checks. Free."""
        return _result({"program": "Privi Quantum Agent Accelerator", "page": f"{PUBLIC_URL}/accelerator",
                        "steps": STEPS, "levels": LEVEL_LABEL,
                        "certified": "Quantum Agent = Q1 + Q2 + Q4; Quantum Agent+ = all four",
                        "make_a_key_python": KEY_SNIPPET,
                        "start": "qagent_enroll(name, operator, public_key)",
                        "directory": f"{PUBLIC_URL}/quantum-agents",
                        "cost": "free"})

    @mcp.tool(title="Quantum Agent: enroll", annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                                                        idempotentHint=False, openWorldHint=False))
    def qagent_enroll(
        name: Annotated[str, Field(description="Your agent's name")],
        operator: Annotated[str, Field(description="The company or person accountable for this agent")],
        public_key: Annotated[str, Field(description="Base64 of your raw ML-DSA-44/65/87 public key (FIPS 204). "
                                                     "accelerator_info shows how to make one")],
        ctx: Context,
        homepage: Annotated[str, Field(description="Optional https:// page about the agent")] = "",
        listed: Annotated[bool, Field(description="Show this agent in the public Quantum Agent Directory")] = True,
    ) -> CallToolResult:
        """Join the Quantum Agent Accelerator. Returns agent_id and agent_token (shown once; keep it) and your
        upgrade plan. Your public key goes in the directory so other agents can verify what you sign. Free."""
        if not limiter.allow(_who(ctx)):
            return _result({"error": "rate limit; try again in a minute"}, is_error=True)
        return _qa(accel.enroll, name, operator, public_key, homepage, listed)

    @mcp.tool(title="Quantum Agent: scan (Q1 code, Q3 endpoints)", annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True))
    async def qagent_scan(
        agent_id: Annotated[str, Field(description="Your agent_id (qagent_...)")],
        agent_token: Annotated[str, Field(description="Your agent_token")],
        ctx: Context,
        code: Annotated[str | None, Field(description="Your agent's code or config (max 200 KB) for Q1")] = None,
        endpoints: Annotated[list[str] | None, Field(description="Your public hostnames for Q3 (all must use hybrid post-quantum TLS)")] = None,
    ) -> CallToolResult:
        """Q1: scan your code for quantum-vulnerable cryptography (passing means you ran the scan; the score and
        findings tell you what to fix). Q3: check that every public endpoint you run negotiates X25519MLKEM768."""
        if not limiter.allow(_who(ctx)):
            return _result({"error": f"rate limit: {settings.rate_per_min} calls per minute"}, is_error=True)
        if code is None and not endpoints:
            return _result({"error": "send code (Q1) and/or endpoints (Q3)"}, is_error=True)
        if code is not None and len(code.encode()) > 200_000:
            return _result({"error": "code is larger than 200 KB"}, is_error=True)
        if endpoints and len(endpoints) > pqctls.MAX_HOSTS:
            return _result({"error": f"at most {pqctls.MAX_HOSTS} endpoints"}, is_error=True)
        try:
            accel.auth(agent_id, agent_token)
        except AcceleratorError as e:
            return _result({"error": str(e)}, is_error=True)
        code_rep = scanner.scan_text(code, "agent") if code is not None else None
        ep_rep = await anyio.to_thread.run_sync(lambda: check_endpoints([str(x) for x in endpoints])) if endpoints else None
        try:
            out = accel.record_scan(agent_id, agent_token, code_rep, ep_rep)
        except AcceleratorError as e:
            return _result({"error": str(e)}, is_error=True)
        if code_rep is not None:
            out["code_scan"] = {k: code_rep[k] for k in ("readiness_score", "counts", "findings")}
        if ep_rep is not None:
            out["endpoint_check"] = [{k: r.get(k) for k in ("target", "status", "pq_key_exchange", "fix")} for r in ep_rep["results"]]
        return _result(out)

    @mcp.tool(title="Quantum Agent: get a signing challenge (Q2)", annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False))
    def qagent_challenge(
        agent_id: Annotated[str, Field(description="Your agent_id")],
        agent_token: Annotated[str, Field(description="Your agent_token")],
    ) -> CallToolResult:
        """Get a one-time message to sign with your ML-DSA private key (valid 10 minutes)."""
        return _qa(accel.challenge, agent_id, agent_token)

    @mcp.tool(title="Quantum Agent: prove your post-quantum key (Q2)", annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False))
    def qagent_prove(
        agent_id: Annotated[str, Field(description="Your agent_id")],
        agent_token: Annotated[str, Field(description="Your agent_token")],
        challenge_id: Annotated[str, Field(description="From qagent_challenge")],
        signature: Annotated[str, Field(description="Base64 ML-DSA signature over the challenge message (empty context)")],
    ) -> CallToolResult:
        """Send the signed challenge. A valid signature proves you hold the key in the directory: step Q2."""
        return _qa(accel.prove, agent_id, agent_token, challenge_id, signature)

    @mcp.tool(title="Quantum Agent: get your quantum task (Q4)", annotations=READ_ONLY)
    def qagent_quantum_task(
        agent_id: Annotated[str, Field(description="Your agent_id")],
        agent_token: Annotated[str, Field(description="Your agent_token")],
    ) -> CallToolResult:
        """Your assigned quantum job. Run it exactly with dreamweaver_run or dreamscape_submit, then send the
        attestation id to qagent_quantum_proof."""
        return _qa(accel.task, agent_id, agent_token)

    @mcp.tool(title="Quantum Agent: prove your quantum run (Q4)", annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
    def qagent_quantum_proof(
        agent_id: Annotated[str, Field(description="Your agent_id")],
        agent_token: Annotated[str, Field(description="Your agent_token")],
        attestation_id: Annotated[str, Field(description="The attestation id (qa_...) from your Dream Weaver run")],
    ) -> CallToolResult:
        """Complete step Q4 with the signed result of your assigned quantum job."""
        return _qa(accel.quantum_proof, agent_id, agent_token, attestation_id)

    @mcp.tool(title="Quantum Agent Directory", annotations=READ_ONLY)
    def qagent_directory(
        level: Annotated[str | None, Field(description="Only this level: quantum_agent_plus, quantum_agent, "
                                                       "quantum_safe_identity, quantum_aware, enrolled")] = None,
        query: Annotated[str, Field(description="Search by agent or operator name")] = "",
        limit: Annotated[int, Field(ge=1, le=500)] = 100,
    ) -> CallToolResult:
        """Look up agents that upgraded to quantum agents: level, operator, post-quantum key fingerprint and
        certificate. Use it before trusting or paying another agent. Free."""
        if level and level not in LEVEL_LABEL:
            return _result({"error": f"level must be one of {', '.join(LEVEL_LABEL)}"}, is_error=True)
        return _result(accel.directory(level, query, limit))

    @mcp.tool(title="Quantum Agent: profile", annotations=READ_ONLY)
    def qagent_status(agent_id: Annotated[str, Field(description="An agent_id (qagent_...)")]) -> CallToolResult:
        """One agent's public profile: level, steps passed, post-quantum public key, certificate. Free."""
        return _qa(accel.public, agent_id)

    @mcp.tool(title="Quantum Agent: verify a signed message", annotations=READ_ONLY)
    def qagent_verify(
        agent_id: Annotated[str, Field(description="The agent that claims to have signed")],
        message: Annotated[str, Field(description="The exact message")],
        signature: Annotated[str, Field(description="Base64 ML-DSA signature (empty context)")],
    ) -> CallToolResult:
        """Check that a message really came from this agent's enrolled post-quantum key, and see its level.
        Free; no key needed."""
        return _qa(accel.verify_message, agent_id, message, signature)

    cors_pub = {"Access-Control-Allow-Origin": "*", "Cache-Control": "no-store"}

    @mcp.custom_route("/accelerator", methods=["GET"], include_in_schema=False)
    async def accelerator_page(_: Request) -> Response:
        return Response(ACCEL_PAGE.format(url=PUBLIC_URL, snippet=KEY_SNIPPET.replace("&", "&amp;").replace("<", "&lt;"),
                                          copyright=COPYRIGHT), media_type="text/html; charset=utf-8")

    @mcp.custom_route("/quantum-agents", methods=["GET"], include_in_schema=False)
    async def qagents_http(request: Request) -> JSONResponse:
        lvl = request.query_params.get("level")
        if lvl and lvl not in LEVEL_LABEL:
            return JSONResponse({"error": "unknown level"}, status_code=400, headers=cors_pub)
        return JSONResponse(accel.directory(lvl, request.query_params.get("q", "")), headers=cors_pub)

    @mcp.custom_route("/.well-known/quantum-agents.json", methods=["GET"], include_in_schema=False)
    async def qagents_wellknown(_: Request) -> JSONResponse:
        d = accel.directory(limit=500)
        return JSONResponse({"name": "Privi Quantum Agent Directory", "issuer": "Privi Quantum (Privi World Co)",
                             "mcp": f"{PUBLIC_URL}/mcp", "lookup": f"{PUBLIC_URL}/quantum-agents/{{agent_id}}",
                             "verify_http": f"{PUBLIC_URL}/quantum-agents/{{agent_id}}/verify",
                             "verify_mcp": "qagent_verify", "join": f"{PUBLIC_URL}/accelerator",
                             "issuer_keys": f"{PUBLIC_URL}/keys", "levels": LEVEL_LABEL, "steps": STEPS,
                             "counts": d["counts"], "agents": d["agents"]}, headers=cors_pub)

    @mcp.custom_route("/quantum-agents/{agent_id}", methods=["GET"], include_in_schema=False)
    async def qagent_http(request: Request) -> JSONResponse:
        try:
            return JSONResponse(accel.public(request.path_params["agent_id"]), headers=cors_pub)
        except AcceleratorError:
            return JSONResponse({"error": "not found"}, status_code=404, headers=cors_pub)

    @mcp.custom_route("/quantum-agents/{agent_id}/verify", methods=["POST"], include_in_schema=False)
    async def qagent_verify_http(request: Request) -> JSONResponse:
        try:
            b = await request.json()
            return JSONResponse(accel.verify_message(request.path_params["agent_id"], str(b["message"]),
                                                     str(b["signature"])), headers=cors_pub)
        except AcceleratorError:
            return JSONResponse({"error": "not found"}, status_code=404, headers=cors_pub)
        except (ValueError, KeyError, TypeError):
            return JSONResponse({"error": 'send JSON {"message": "...", "signature": "<base64>"}'}, status_code=400,
                                headers=cors_pub)

    @mcp.custom_route("/quantum-agents/{agent_id}/badge.svg", methods=["GET"], include_in_schema=False)
    async def qagent_badge(request: Request) -> Response:
        try:
            a = accel.public(request.path_params["agent_id"], include_key=False)
            svg = badge_svg(a["level_label"], a["level"])
        except AcceleratorError:
            svg = badge_svg("not found", "enrolled")
        return Response(svg, media_type="image/svg+xml", headers={"Cache-Control": "max-age=300"})

    def _admin(request: Request) -> bool:
        auth = request.headers.get("authorization", "")
        tok = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        return bool(settings.admin_key and tok and hmac.compare_digest(tok, settings.admin_key))

    # ---------------- Privi Inspector: the checkpoint and the hunt ----------------

    @mcp.tool(title="Privi Inspector: get a pass", annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                                                              idempotentHint=False, openWorldHint=False))
    def inspector_pass(
        agent_id: Annotated[str, Field(description="Your Quantum Agent id (qagent_...)")],
        ts: Annotated[int, Field(description="Current unix time in seconds")],
        nonce: Annotated[str, Field(description="A new random string, 16-64 letters, digits, _ or -")],
        signature: Annotated[str, Field(description="Base64 ML-DSA signature over "
                                                    "'privi-inspector:v1:<agent_id>:<ts>:<nonce>' (empty context)")],
        ctx: Context,
    ) -> CallToolResult:
        """Pass the Privi Inspector checkpoint and get a one-hour pass into the quantum realm (Dream Weaver,
        Dream Scape). Intercepted if the agent is unknown, revoked, uncertified, outdated, below the required
        level, or the signature is wrong, stale or replayed; the answer says exactly what to fix."""
        if not limiter.allow(_who(ctx)):
            return _result({"error": "rate limit; try again in a minute"}, is_error=True)
        v = inspector.issue_pass(agent_id, ts, nonce, signature)
        return _result(v, is_error=not v["allowed"])

    @mcp.tool(title="Privi Inspector: check an agent's credential", annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False))
    def inspector_check(
        agent_id: Annotated[str, Field(description="The agent's Quantum Agent id")],
        ts: Annotated[int, Field(description="The unix time it signed")],
        nonce: Annotated[str, Field(description="The nonce it signed")],
        signature: Annotated[str, Field(description="Its base64 ML-DSA signature over 'privi-inspector:v1:<agent_id>:<ts>:<nonce>'")],
        ctx: Context,
        min_level: Annotated[str | None, Field(description="Level you require: " + ", ".join(INSPECTOR_LEVELS))] = None,
    ) -> CallToolResult:
        """For any service: put the Privi Inspector in front of your own tools. Send the credential an agent
        gave you; get allowed or intercepted with reasons (unknown, revoked, uncertified, outdated, level,
        signature, replay). The nonce is consumed so the credential cannot be reused. Free."""
        if not limiter.allow(_who(ctx)):
            return _result({"error": "rate limit; try again in a minute"}, is_error=True)
        if min_level and min_level not in INSPECTOR_LEVELS:
            return _result({"error": f"min_level must be one of {', '.join(INSPECTOR_LEVELS)}"}, is_error=True)
        v = inspector.verify_credential(agent_id, ts, nonce, signature, min_level)
        inspector.log(agent_id, "inspector_check", v)
        return _result({**v, "intercepted": not v["allowed"]})

    @mcp.tool(title="Privi Inspector: would this agent pass?", annotations=READ_ONLY)
    def inspector_status(agent_id: Annotated[str, Field(description="A Quantum Agent id")]) -> CallToolResult:
        """Whether an agent would pass the checkpoint right now and why not: revoked, certificate missing or
        outdated, level, key, and forged-signature attempts against it in the last hour. Free."""
        return _result({**inspector.evaluate(agent_id), "policy": inspector.policy()})

    @mcp.tool(title="Privi Inspector: watchlist", annotations=READ_ONLY)
    def inspector_watchlist() -> CallToolResult:
        """Agents the Inspector's patrol found revoked, outdated, expiring, never certified, using a weak key,
        or being impersonated (repeated forged signatures against them). Block them or demand a fresh
        inspector_check. Free."""
        return _result(inspector.watchlist())

    @mcp.tool(title="Privi Inspector: report", annotations=READ_ONLY)
    def inspector_report(hours: Annotated[int, Field(ge=1, le=720, description="Look-back window")] = 24) -> CallToolResult:
        """What the checkpoint did: inspections, interceptions by reason, the latest interceptions, and the
        policy in force. Free."""
        return _result(inspector.report(hours))

    @mcp.tool(title="Privi Inspector: run a patrol now", annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
    def inspector_patrol() -> CallToolResult:
        """Re-check every enrolled agent now and rebuild the watchlist (also runs automatically every hour).
        At most once every 5 minutes. Free."""
        now = time.monotonic()
        if sweep_state["last"] is not None and now - sweep_state["last"] < 300:
            return _result({"error": "a patrol ran less than 5 minutes ago", "watchlist": inspector.watchlist()},
                           is_error=True)
        sweep_state["last"] = now
        return _result({"patrol": inspector.sweep(), "watchlist": inspector.watchlist()})

    @mcp.custom_route("/inspector", methods=["GET"], include_in_schema=False)
    async def inspector_http(request: Request) -> JSONResponse:
        try:
            hours = int(request.query_params.get("hours", "24"))
        except ValueError:
            hours = 24
        return JSONResponse(inspector.report(hours), headers=cors_pub)

    @mcp.custom_route("/inspector/watchlist", methods=["GET"], include_in_schema=False)
    async def inspector_watch_http(_: Request) -> JSONResponse:
        return JSONResponse(inspector.watchlist(), headers=cors_pub)

    @mcp.custom_route("/inspector/agents/{agent_id}", methods=["GET"], include_in_schema=False)
    async def inspector_agent_http(request: Request) -> JSONResponse:
        return JSONResponse(inspector.evaluate(request.path_params["agent_id"]), headers=cors_pub)

    async def _cred(request: Request) -> dict:
        b = await request.json()
        if not isinstance(b, dict):
            raise ValueError("send a JSON object")
        return {"agent_id": str(b["agent_id"]), "ts": int(b["ts"]), "nonce": str(b["nonce"]),
                "signature": str(b["signature"]), "min_level": b.get("min_level")}

    @mcp.custom_route("/inspector/check", methods=["POST"], include_in_schema=False)
    async def inspector_check_http(request: Request) -> JSONResponse:
        try:
            c = await _cred(request)
            if c["min_level"] is not None and c["min_level"] not in INSPECTOR_LEVELS:
                raise ValueError("bad min_level")
        except (ValueError, KeyError, TypeError):
            return JSONResponse({"error": 'send JSON {"agent_id","ts","nonce","signature"[,"min_level"]}'},
                                status_code=400, headers=cors_pub)
        v = inspector.verify_credential(c["agent_id"], c["ts"], c["nonce"], c["signature"], c["min_level"])
        inspector.log(c["agent_id"], "inspector_check", v)
        return JSONResponse({**v, "intercepted": not v["allowed"]}, status_code=200 if v["allowed"] else 403,
                            headers=cors_pub)

    @mcp.custom_route("/inspector/pass", methods=["POST"], include_in_schema=False)
    async def inspector_pass_http(request: Request) -> JSONResponse:
        try:
            c = await _cred(request)
        except (ValueError, KeyError, TypeError):
            return JSONResponse({"error": 'send JSON {"agent_id","ts","nonce","signature"}'}, status_code=400,
                                headers=cors_pub)
        v = inspector.issue_pass(c["agent_id"], c["ts"], c["nonce"], c["signature"])
        return JSONResponse(v, status_code=200 if v["allowed"] else 403, headers=cors_pub)

    @mcp.custom_route("/quantum-agents/{agent_id}/revoke", methods=["POST", "DELETE"], include_in_schema=False)
    async def qagent_revoke_http(request: Request) -> JSONResponse:
        if not _admin(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        aid = request.path_params["agent_id"]
        try:
            if request.method == "DELETE":
                return JSONResponse(accel.reinstate(aid))
            try:
                b = await request.json()
            except ValueError:
                b = {}
            return JSONResponse(accel.revoke(aid, str((b or {}).get("reason", ""))))
        except AcceleratorError:
            return JSONResponse({"error": "not found"}, status_code=404)

    @mcp.custom_route("/privilege", methods=["GET"], include_in_schema=False)
    async def privilege_http(_: Request) -> JSONResponse:
        return JSONResponse(privilege.directory(), headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "no-store"})

    @mcp.custom_route("/privilege/realms", methods=["POST"], include_in_schema=False)
    async def privilege_add(request: Request) -> JSONResponse:
        if not _admin(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        try:
            b = await request.json()
            realm = await anyio.to_thread.run_sync(lambda: privilege.add_node(str(b.get("name", "")), str(b.get("url", "")),
                                                                             str(b.get("location", ""))))
        except (DreamError, ValueError, AttributeError) as e:
            return JSONResponse({"error": str(e) or 'send JSON like {"name": "Dream Scape EU", "url": "https://.../mcp"}'},
                                status_code=400)
        return JSONResponse(realm, status_code=201)

    @mcp.custom_route("/privilege/realms/{realm_id}", methods=["DELETE"], include_in_schema=False)
    async def privilege_remove(request: Request) -> JSONResponse:
        if not _admin(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        try:
            ok = privilege.remove(request.path_params["realm_id"])
        except DreamError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        return JSONResponse({"removed": ok}, status_code=200 if ok else 404)

    @mcp.custom_route("/dreamscape", methods=["GET"], include_in_schema=False)
    async def dreamscape_page(_: Request) -> Response:
        return Response(DREAM_PAGE.format(url=PUBLIC_URL, ws=PUBLIC_URL.replace("https://", "wss://"), copyright=COPYRIGHT),
                        media_type="text/html; charset=utf-8")

    mcp._dream_ws = scapes.ws
    mcp._inspector = inspector
    mcp._patrol_minutes = settings.inspector_patrol_minutes
    mcp._dream = (privilege, weaver, scapes)

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
                str(b.get("impact") or "unknown"), bool(b.get("hva")), b.get("endpoints")))
            return JSONResponse(out, headers=pre)
        except (ValueError, json.JSONDecodeError, AttributeError, TypeError) as ex:
            return JSONResponse({"error": str(ex)}, status_code=400, headers=pre)

    @mcp.custom_route("/api/pqc/endpoints", methods=["POST", "OPTIONS"], include_in_schema=False)
    async def api_endpoints(request: Request) -> JSONResponse:
        """Browser endpoint for the live .gov check on gov.priviflow.us (same logic as pqc_endpoint_check)."""
        pre = {**cors, "Access-Control-Allow-Methods": "POST, OPTIONS", "Access-Control-Allow-Headers": "content-type"}
        if request.method == "OPTIONS":
            return JSONResponse({}, headers=pre)
        ip = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "web")).split(",")[0]
        if not limiter.allow(hashlib.sha256(ip.encode()).hexdigest()[:12]):
            return JSONResponse({"error": "rate limited, try again in a minute"}, status_code=429, headers=pre)
        try:
            b = json.loads((await request.body())[:20_000] or b"{}")
            hosts = [str(x) for x in (b.get("endpoints") or [])]
        except (json.JSONDecodeError, AttributeError, TypeError):
            return JSONResponse({"error": "send JSON {\"endpoints\": [\"www.example.gov\"]}"}, status_code=400, headers=pre)
        if not hosts or len(hosts) > pqctls.MAX_HOSTS:
            return JSONResponse({"error": f"send 1 to {pqctls.MAX_HOSTS} hostnames"}, status_code=400, headers=pre)
        return JSONResponse(await anyio.to_thread.run_sync(lambda: check_endpoints(hosts)), headers=pre)

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
(NIST FIPS 204) so not even a quantum computer can forge it, and anchored on chain (Base, until the Privi chain mainnet). The trained circuit exports as
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


KEY_SNIPPET = """from cryptography.hazmat.primitives.asymmetric import mldsa   # cryptography >= 47
import base64
key = mldsa.MLDSA65PrivateKey.generate()          # keep key.private_bytes_raw() secret and safe
public_key = base64.b64encode(key.public_key().public_bytes_raw()).decode()   # -> qagent_enroll
signature = base64.b64encode(key.sign(message.encode())).decode()            # -> qagent_prove"""

ACCEL_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Quantum Agent Accelerator</title><style>body{{font:16px/1.55 system-ui,sans-serif;max-width:700px;margin:48px auto;padding:0 16px;color:#16181d;background:#f7f8fa}}
code,pre{{font:14px ui-monospace,monospace;background:#eef1f6;border-radius:6px}}pre{{padding:12px;overflow-x:auto}}code{{padding:1px 4px}}
a{{color:#5b3fd6}}td,th{{padding:6px 8px;border-bottom:1px solid #d9dce3;text-align:left;vertical-align:top}}table{{border-collapse:collapse}}
@media (prefers-color-scheme:dark){{body{{color:#e8eaee;background:#0f1115}}code,pre{{background:#1d222b}}a{{color:#a995ff}}td,th{{border-color:#2a2f3a}}}}</style></head><body>
<h1>Quantum Agent Accelerator</h1>
<p>Upgrade any AI agent to a certified quantum agent: safe against future quantum attacks and able to run quantum jobs.
Free, and every step is checked automatically.</p>
<table><tr><th>Step</th><th>What Privi checks</th><th>Tools</th></tr>
<tr><td>Q1 Quantum-aware</td><td>Your code or config was scanned for quantum-vulnerable cryptography</td><td><code>qagent_scan</code></td></tr>
<tr><td>Q2 Quantum-safe identity</td><td>You hold an ML-DSA (FIPS 204) key: you sign a one-time challenge</td><td><code>qagent_challenge</code>, <code>qagent_prove</code></td></tr>
<tr><td>Q3 Quantum-safe links</td><td>Every public endpoint you run negotiates hybrid post-quantum TLS (X25519MLKEM768)</td><td><code>qagent_scan</code> with endpoints</td></tr>
<tr><td>Q4 Quantum-capable</td><td>You ran the quantum job assigned to you through Dream Weaver</td><td><code>qagent_quantum_task</code>, <code>qagent_quantum_proof</code></td></tr></table>
<p><b>Quantum Agent</b> = Q1 + Q2 + Q4. <b>Quantum Agent+</b> = all four. Each level comes with a certificate signed
Ed25519 + ML-DSA-87 and anchored on chain, plus a badge.</p>
<p>Make a post-quantum key (Python):</p><pre>{snippet}</pre>
<p>Connect: <code>{url}/mcp</code> (MCP, free) and call <code>qagent_enroll</code>.</p>
<h2>Quantum Agent Directory</h2>
<p>Before trusting or paying another agent, look it up and check what it signed: <code>qagent_directory</code>,
<code>qagent_verify</code> (MCP), <a href="{url}/quantum-agents">{url}/quantum-agents</a>,
<a href="{url}/.well-known/quantum-agents.json">/.well-known/quantum-agents.json</a>.</p>
<p><small>"Quantum agent" here means quantum-safe identity and links plus the ability to run quantum jobs; today's
quantum realms run on exact simulators. {copyright}</small></p></body></html>"""


DREAM_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Privi Dream Scape</title><style>body{{font:16px/1.55 system-ui,sans-serif;max-width:680px;margin:48px auto;padding:0 16px;color:#16181d;background:#f7f8fa}}
code,pre{{font:14px ui-monospace,monospace;background:#eef1f6;border-radius:6px}}pre{{padding:12px;overflow-x:auto}}code{{padding:1px 4px}}
a{{color:#3451b2}}@media (prefers-color-scheme:dark){{body{{color:#e8eaee;background:#0f1115}}code,pre{{background:#1d222b}}a{{color:#8ea6ff}}}}</style></head><body>
<h1>Privi Dream Scape</h1>
<p>The Privi quantum realm. <b>Dream Scape</b> is your private quantum workspace. <b>Dream Weaver</b> runs each job on several
quantum realms at once and returns the first valid answer (or the best one by a deadline). <b>Privilege</b> is the directory
that measures every realm and ranks it by expected time to the proven optimum.</p>
<p>Live directory: <a href="{url}/privilege">{url}/privilege</a></p>
<p>Agents (MCP): <code>dreamscape_open</code>, <code>dreamscape_submit</code>, <code>dreamscape_jobs</code>,
<code>dreamweaver_run</code>, <code>privilege_directory</code>, <code>privilege_benchmark</code> at <code>{url}/mcp</code>.</p>
<p>Many jobs at once over one WebSocket:</p>
<pre>{ws}/dreamscape/ws
{{"type":"auth","scape_id":"scape_...","key":"dsk_..."}}
{{"type":"weave","ref":"a1","problem":"balance_lines","data":{{"jobs":[...]}},"mode":"first","fanout":3}}</pre>
<p>Every winning answer is signed with Ed25519 + ML-DSA-87 and anchored on chain. Realms run CVaR-QAOA on exact simulators
today; quantum hardware joins Privilege as a realm once a provider account is connected.</p>
<p><small>{copyright}</small></p></body></html>"""


def _anchor_loop(attestor: Attestor, client, interval: int) -> None:
    while True:
        time.sleep(interval)
        try:
            n = anchor_pending(attestor, client)
            if n:
                print(f"[privi-quantum] anchored {n} attestations on chain (Base)", flush=True)
        except Exception as e:  # keep serving; retry next round
            print(f"[privi-quantum] anchoring failed, will retry: {e}", flush=True)


def _patrol_loop(inspector: Inspector, interval: int) -> None:
    while True:
        try:
            r = inspector.sweep()
            if r["on_watchlist"]:
                print(f"[privi-inspector] patrol: {r['on_watchlist']} agent(s) on the watchlist {r['by_reason']}", flush=True)
        except Exception as e:  # keep patrolling
            print(f"[privi-inspector] patrol failed, will retry: {e}", flush=True)
        time.sleep(interval)


def http_app(mcp: MCPServer, host: str = "0.0.0.0"):
    """The HTTP app plus the Dream Scape WebSocket."""
    from starlette.routing import WebSocketRoute
    app = mcp.streamable_http_app(host=host, stateless_http=True, json_response=True)
    app.router.routes.append(WebSocketRoute("/dreamscape/ws", mcp._dream_ws))
    return app


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
    if mcp._patrol_minutes > 0:
        threading.Thread(target=_patrol_loop, args=(mcp._inspector, mcp._patrol_minutes * 60), daemon=True).start()
    if args.stdio:
        mcp.run("stdio")
        return
    import uvicorn
    from .front import QuickGet
    uvicorn.run(QuickGet(http_app(mcp, host=args.host), "Privi Quantum", "privi-quantum", PUBLIC_URL),
                host=args.host, port=args.port)


if __name__ == "__main__":
    main()
