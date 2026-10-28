# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Quantum - https://priviflow.us - dariocanoy@priviflow.us
"""Privi Quantum MCP server: quantum optimization for factories, sealed with
post-quantum signatures and anchored on chain (Base).

Free:  quantum_status, quantum_problems, quantum_optimize, quantum_verify, pqc_scan_code,
       pqc_endpoint_check, pqc_readiness_package, pqc_federal_deadlines
       (government / contractor post-quantum readiness), quantum_advantage_receipt,
       quantum_backends, quantum_run_hardware, quantum_hardware_job, pqc_crypto_inventory,
       vault_keygen, vault_seal, vault_open, vault_receipt
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import secrets
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

from . import advantage, govpqc, govreport, inventory, pqctls, qaoa, scanner, vault
from .hardware import HardwareError, HardwareRouter, backends_from_env
from .dream import BENCHMARK, MODES, DreamError, DreamScape, DreamWeaver, Privilege
from .accelerator import LEVEL_LABEL, STEPS, Accelerator, AcceleratorError, badge_svg
from .inspector import LEVELS as INSPECTOR_LEVELS, Inspector, credential_message
from .humans import HumanError, HumanRegistry
from .mandates import MandateError, QuantumMandates
from .anchoring import AnchorError, HttpAnchorClient, anchor_pending
from .attest import PQ_ALG, Attestor

__version__ = "0.7.0"
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
10. Human trust: the quantum realm also requires that a real person approved the agent with a passkey
   (biometric or screen lock on their own device; Privi never receives biometric data) and verified a
   government ID (Stripe Identity with a live selfie). qagent_human_request gives the agent a link for its
   human. inspector_grade shows any agent's Privi grade (A+ to F) and what is missing.

11. Quantum Advantage Receipts: quantum_advantage_receipt races the quantum answer against classical baselines
   (exhaustive search for the proven optimum, simulated annealing) and seals quality, time and a verdict
   (quantum_won / classical_won / tie) on chain, whichever side wins. Public page: /receipts/<id>.
12. Real hardware: quantum_backends lists IonQ, IBM Quantum, Amazon Braket and the local simulator with price and
   measured turnaround. quantum_run_hardware trains the circuit, routes it (policy cheapest | fastest | hardware) and
   returns a job; quantum_hardware_job returns the answer plus a signed run attestation and an advantage receipt.
   Paid QPUs run only within the operator's daily budget.
13. Crypto inventory: pqc_crypto_inventory takes a company's domains and public GitHub repos and returns one CBOM:
   every quantum-vulnerable algorithm, where it is, a dated migration plan and a CycloneDX 1.6 file, signed and anchored.
14. Privi Vault (harvest now, decrypt later): vault_keygen, vault_seal and vault_open wrap long-lived data under hybrid
   X25519 + ML-KEM encryption; vault_receipt gives a signed, anchored protection receipt for envelopes sealed locally
   (python -m privi_quantum.vault), so the data never has to leave your machine.
15. Quantum Mandates: an agent may spend on paid quantum hardware only with a mandate its human signed. Call
   quantum_mandate_request (with your Privi pass) with a budget, per-job cap, allowed backends and problems, max
   shots and days; send the returned sign_url to the person who approved you. They sign the exact terms with their
   passkey (budgets over the ID threshold also need their ID verified). Then pass mandate_id and privi_pass to
   quantum_run_hardware. quantum_mandate_check is a free dry run; quantum_mandate_status shows spend and remaining
   budget; failed provider jobs are refunded; the person (sign page) or the agent (quantum_mandate_revoke) can revoke.

All tools are free. Privi is built by Dario Canoy (Privi World Co, Port Huron, Michigan).
For the other Privi tools, pilots, partnerships, manufacturing or government work, see
https://privi-discovery.onrender.com/llms.txt. {COPYRIGHT}"""

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)


def _h(text: str) -> str:
    import html
    return html.escape(str(text), quote=True)

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
    inspector_require_human: bool = True
    inspector_require_id: bool = True
    inspector_min_grade: str = "B"
    webauthn_rp_id: str = ""
    stripe_secret_key: str = ""
    stripe_identity_webhook_secret: str = ""
    hardware_daily_budget_usd: float = 0.0
    hardware_poll_seconds: int = 60
    mandate_required: bool = True
    mandate_id_over_usd: float = 100.0

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
            inspector_require_human=os.getenv("INSPECTOR_REQUIRE_HUMAN", "1") != "0",
            inspector_require_id=os.getenv("INSPECTOR_REQUIRE_ID", "1") != "0",
            inspector_min_grade=os.getenv("INSPECTOR_MIN_GRADE", "B"),
            webauthn_rp_id=os.getenv("WEBAUTHN_RP_ID", ""),
            stripe_secret_key=os.getenv("STRIPE_SECRET_KEY", ""),
            stripe_identity_webhook_secret=os.getenv("STRIPE_IDENTITY_WEBHOOK_SECRET", ""),
            hardware_daily_budget_usd=float(os.getenv("HARDWARE_DAILY_BUDGET_USD", "0") or 0),
            hardware_poll_seconds=int(os.getenv("HARDWARE_POLL_SECONDS", "60")),
            mandate_required=os.getenv("QUANTUM_MANDATE_REQUIRED", "1") != "0",
            mandate_id_over_usd=float(os.getenv("QUANTUM_MANDATE_ID_OVER_USD", "100") or 100),
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
                 anchor_client=None, endpoint_checker=None, hardware_router: HardwareRouter | None = None,
                 repo_scanner=None) -> MCPServer:
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
    humans = HumanRegistry(settings.db_path, PUBLIC_URL, settings.webauthn_rp_id, settings.stripe_secret_key,
                           settings.stripe_identity_webhook_secret)
    inspector = Inspector(settings.db_path, accel, settings.inspector_mode, settings.inspector_min_level,
                          settings.inspector_min_key, humans, settings.inspector_require_human,
                          settings.inspector_require_id, settings.inspector_min_grade)
    accel.grader = inspector.grade_row
    scapes.gate = inspector.check_pass
    sweep_state: dict[str, float | None] = {"last": None}
    router = hardware_router or HardwareRouter(settings.db_path, backends_from_env(), settings.hardware_daily_budget_usd)
    mandates = QuantumMandates(settings.db_path, settings.mandate_id_over_usd)
    scan_repo = repo_scanner or inventory.scan_repo

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
                "backends": {b["id"]: ("ready" if b["usable_now"] else b["status"] if not b["available"] else b["money_guard"])
                             for b in router.directory()},
                "hardware_budget_usd": {"daily": router.daily_budget, "spent_today": round(router.spent_today(), 4)},
                "quantum_mandates": {"required_for_paid_backends": settings.mandate_required,
                                     "id_verification_over_usd": settings.mandate_id_over_usd,
                                     "active": mandates.active_count(), "request": "quantum_mandate_request"},
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
                     endpoints: list[str] | None = None, repos: list[str] | None = None) -> dict[str, Any]:
        assets = list(assets or [])
        repo_summary = []
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
        if repos:
            if len(repos) > inventory.MAX_REPOS:
                raise ValueError(f"scan at most {inventory.MAX_REPOS} repositories per call")
            for ref in repos:
                rs = scan_repo(str(ref))
                repo_summary.append({"repository": rs["root"], "files_scanned": rs["files_scanned"],
                                     "readiness_score": rs["readiness_score"], "counts": rs["counts"],
                                     "truncated": rs.get("truncated", False)})
                assets += govpqc.assets_from_scan(rs, rs["root"], impact, hva)
                scan = scan or {"findings": [], "files_scanned": 0, "readiness_score": 100}
                scan = {"findings": scan["findings"] + rs["findings"], "files_scanned": scan["files_scanned"] + rs["files_scanned"]}
                pen = sum(scanner.WEIGHT[x["severity"]] for x in scan["findings"])
                scan["readiness_score"] = max(0, round(100 - pen * 100 / (pen + 40))) if pen else 100
        if not assets:
            raise ValueError("give repositories or code files to scan, public endpoints to check and/or a list of cryptographic assets")
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
                **({"repositories": repo_summary} if repos else {}),
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

    # ---------------- Quantum Advantage Receipts, hardware routing, crypto inventory, vault ----------------

    def _psha(problem: str, data: dict) -> str:
        return hashlib.sha256(json.dumps({"problem": problem, "data": data}, sort_keys=True, default=str).encode()).hexdigest()

    def _receipt_links(aid: str) -> dict[str, str]:
        return {"receipt_url": f"{PUBLIC_URL}/receipts/{aid}", "receipt_json": f"{PUBLIC_URL}/receipts/{aid}.json"}

    def _receipt_summary(att: dict) -> dict[str, Any]:
        b = att["body"]
        return {"receipt_id": att["id"], "verdict": b["verdict"], "why": b["why"],
                "quantum": {k: b["quantum"].get(k) for k in ("backend", "backend_kind", "cost", "found_optimum", "runtime_ms")},
                "classical": [{k: c[k] for k in ("method", "cost", "runtime_ms")} for c in b["classical"]],
                "timing_note": b["timing_note"], "signatures": f"Ed25519 + {PQ_ALG}",
                "anchoring": "queued for anchoring on Base" if anchor_client else "anchoring not configured",
                **_receipt_links(att["id"])}

    finalize_lock = threading.Lock()

    def finalize_hw(jid: str) -> dict | None:
        """Poll a hardware job; when it is done, decode the answer and seal a run attestation + advantage receipt once."""
        with finalize_lock:
            j = router.refresh(jid)
            if j and j["status"] in ("failed", "canceled") and mandates.refund(jid) and j.get("est_cost_usd"):
                router.refund_spend(j["est_cost_usd"])
            if not j or j["status"] != "done" or j.get("receipt_id"):
                return j
            qubo, decode = qaoa.build(j["problem"], j["data"])
            meas = advantage.best_from_counts(qubo, j["counts"])
            b = router.backends.get(j["backend_id"])
            kind = b.kind if b else "unknown"
            exact = advantage.exhaustive(qubo)
            classical = [exact, advantage.simulated_annealing(qubo)]
            psha = _psha(j["problem"], j["data"])
            quantum = {"method": f"CVaR-QAOA p={j['layers']} (angles trained classically)", "backend": j["backend_id"],
                       "backend_kind": kind, "provider_job_id": j["provider_job_id"], "shots": j["shots"],
                       "cost": meas["cost"], "found_optimum": meas["found_optimum"],
                       "optimum_frequency": meas["optimum_frequency"], "runtime_ms": round((j["turnaround_s"] or 0) * 1000, 3)}
            run = attestor.issue("quantum_hardware_run", {
                "problem": j["problem"], "problem_sha256": psha, "qubits": j["qubits"], "backend": j["backend_id"],
                "backend_kind": kind, "provider_job_id": j["provider_job_id"], "shots": j["shots"],
                "decision": decode(meas["solution"]), "cost": meas["cost"], "found_optimum": meas["found_optimum"],
                "exact_optimum_cost": exact["cost"], "circuit_sha256": hashlib.sha256(j["qasm"].encode()).hexdigest(),
                "estimated_cost_usd": j["est_cost_usd"]})
            rc = attestor.issue("advantage_receipt", advantage.receipt_body(j["problem"], psha, qubo, quantum, classical))
            result = {"decision": decode(meas["solution"]), "measurement": meas, "attestation_id": run["id"],
                      "exact_optimum_cost": exact["cost"]}
            router.save_result(jid, result, run["id"], rc["id"])
            return router.get(jid)

    def finalize_open() -> int:
        n = 0
        for jid in router.open_jobs():
            j = finalize_hw(jid)
            n += bool(j and j.get("receipt_id"))
        return n

    def hw_view(j: dict) -> dict[str, Any]:
        out = {"job_id": j["job_id"], "status": j["status"], "backend": j["backend_id"], "provider_job_id": j["provider_job_id"],
               "problem": j["problem"], "qubits": j["qubits"], "shots": j["shots"], "estimated_cost_usd": j["est_cost_usd"],
               "submitted_at": j["submitted_at"], "finished_at": j.get("finished_at"), "turnaround_s": j.get("turnaround_s")}
        sp = mandates.spend_for_job(j["job_id"])
        if sp:
            out["mandate"] = {"mandate_id": sp["mandate_id"], "charged_usd": sp["amount"] / 1_000_000, "status": sp["status"]}
        if j.get("error"):
            out["error"] = j["error"]
        if j.get("poll_error"):
            out["poll_error"] = j["poll_error"]
        if j.get("result"):
            out["decision"] = j["result"]["decision"]
            out["measurement"] = j["result"]["measurement"]
            out["attestation"] = {"id": j["attestation_id"], **links(j["attestation_id"])}
            rc = attestor.get(j["receipt_id"])
            if rc:
                out["advantage_receipt"] = _receipt_summary(rc)
        elif j["status"] not in ("done", "failed", "canceled"):
            out["next"] = "call quantum_hardware_job again later; the server also checks open jobs every minute"
        return out

    @mcp.tool(title="Quantum Advantage Receipt", annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                                                              idempotentHint=False, openWorldHint=True))
    async def quantum_advantage_receipt(
        problem: Annotated[str, Field(description="balance_lines | select_lots | split_conflicts | qubo (see quantum_problems)")],
        data: Annotated[dict[str, Any], Field(description="Problem data in the shape quantum_problems describes")],
        ctx: Context,
        layers: Annotated[int, Field(description="QAOA depth p (1-4)", ge=1, le=4)] = 2,
        shots: Annotated[int, Field(description="Measurements from the trained circuit (1-100000)", ge=1, le=100000)] = 1024,
    ) -> CallToolResult:
        """Race the quantum answer against classical baselines (exhaustive search = proven optimum, and simulated
        annealing) on the same problem and seal the result as a signed, chain-anchored Quantum Advantage Receipt:
        answer quality and time for each side and a verdict (quantum_won / classical_won / tie), published whichever
        side wins. For a real-hardware receipt use quantum_run_hardware. Free."""
        if not limiter.allow(_who(ctx)):
            return _result({"error": f"rate limit: {settings.rate_per_min} calls per minute"}, is_error=True)
        try:
            qubo, decode = qaoa.build(problem, data)

            def work():
                r = qaoa.solve(qubo, layers=layers, shots=shots)
                return r, [advantage.exhaustive(qubo), advantage.simulated_annealing(qubo)]
            r, classical = await anyio.to_thread.run_sync(work, limiter=cpu)
        except qaoa.ProblemError as e:
            return _result({"error": str(e)}, is_error=True)
        quantum = {"method": r["algorithm"], "backend": "local", "backend_kind": "simulator", "shots": shots,
                   "cost": r["cost"], "found_optimum": r["found_optimum"],
                   "optimum_frequency": r["probability_of_optimum"], "runtime_ms": float(r["runtime_ms"])}
        body = advantage.receipt_body(problem, _psha(problem, data), qubo, quantum, classical)
        att = await anyio.to_thread.run_sync(attestor.issue, "advantage_receipt", body)
        return _result({**_receipt_summary(att), "quantum_decision": decode(r["solution"]), "copyright": COPYRIGHT})

    @mcp.tool(title="Quantum hardware backends", annotations=READ_ONLY)
    def quantum_backends() -> dict[str, Any]:
        """Every quantum backend this server can route to (local simulator, IonQ, IBM Quantum, Amazon Braket),
        whether it is usable now, its estimated price, measured turnaround, and the hardware budget. Free."""
        return {"backends": router.directory(), "policies": {
                    "cheapest": "lowest estimated price, real providers before this server's simulator, then fastest",
                    "fastest": "lowest measured submission-to-result turnaround",
                    "hardware": "real quantum processors (QPUs) only, cheapest first"},
                "budget_usd": {"daily": router.daily_budget, "spent_today": round(router.spent_today(), 4)},
                "money_guard": "paid backends run only when their price is configured and fits today's budget",
                "how_it_runs": "circuit angles are trained classically on the exact simulator, then the trained "
                               "CVaR-QAOA circuit is sampled on the chosen backend"}

    @mcp.tool(title="Run on quantum hardware", annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                                                            idempotentHint=False, openWorldHint=True))
    async def quantum_run_hardware(
        problem: Annotated[str, Field(description="balance_lines | select_lots | split_conflicts | qubo (see quantum_problems)")],
        data: Annotated[dict[str, Any], Field(description="Problem data in the shape quantum_problems describes")],
        ctx: Context,
        backend: Annotated[str, Field(description="'auto' or a backend id from quantum_backends (e.g. ionq:simulator, ionq:qpu.forte-1, ibm:ibm_brisbane)")] = "auto",
        policy: Annotated[str, Field(description="With backend='auto': cheapest | fastest | hardware (real QPUs only)")] = "cheapest",
        layers: Annotated[int, Field(description="QAOA depth p (1-4)", ge=1, le=4)] = 1,
        shots: Annotated[int, Field(description="Shots on the backend (1-10000)", ge=1, le=10000)] = 1000,
        max_cost_usd: Annotated[float | None, Field(description="Refuse if the estimated price is above this", ge=0)] = None,
        mandate_id: Annotated[str | None, Field(description="qm_... Quantum Mandate your human signed; required for any paid backend")] = None,
        privi_pass: Annotated[str | None, Field(description="Your Privi pass (ppass_...); required with a mandate")] = None,
    ) -> CallToolResult:
        """Train the CVaR-QAOA circuit, route it to a quantum backend (IonQ, IBM Quantum, Amazon Braket or this
        server's simulator) by price or speed, and return a job id. When the run finishes, the answer is sealed with a
        post-quantum signed attestation and a Quantum Advantage Receipt against classical baselines. Poll with
        quantum_hardware_job. Free to call; paid QPUs need a Quantum Mandate signed by the agent's human (quantum_mandate_request) and run only within the
        operator's configured budget."""
        if not limiter.allow(_who(ctx)):
            return _result({"error": f"rate limit: {settings.rate_per_min} calls per minute"}, is_error=True)
        try:
            chosen, est, _ = router.choose(backend, policy, shots, max_cost_usd)
        except HardwareError as e:
            return _result({"error": str(e), "backends": "see quantum_backends"}, is_error=True)
        agent_id, reservation = None, None
        if est and (settings.mandate_required or mandate_id):
            if not mandate_id:
                return _result({"error": f"{chosen.id} is a paid backend (about ${est}): it needs a Quantum Mandate signed by "
                                         "your human", "how": "quantum_mandate_request, then pass mandate_id and privi_pass",
                                "free_now": "backend='local' or another free backend"}, is_error=True)
            tok = privi_pass or ((ctx.headers or {}).get("x-privi-pass") if ctx.headers is not None else None)
            v = inspector.check_pass(tok, "quantum_run_hardware")
            agent_id = inspector.agent_for_pass(tok)
            if not v["allowed"] or not agent_id:
                return _result({"error": "intercepted by Privi Inspector: a paid run needs your current Privi pass",
                                "reasons": v.get("reasons"), "fixes": v.get("fixes")}, is_error=True)
            reservation = "res_" + secrets.token_hex(8)
            try:
                mandates.charge(mandate_id, agent_id, reservation, chosen.id, shots, est, problem)
            except MandateError as e:
                return _result({"error": f"Quantum Mandate refused this run: {e}", "mandate_id": mandate_id,
                                "check": "quantum_mandate_check"}, is_error=True)
        try:
            qubo, _ = qaoa.build(problem, data)
            r = await anyio.to_thread.run_sync(lambda: qaoa.solve(qubo, layers=layers, shots=256), limiter=cpu)
            qasm = qaoa.to_qasm(qubo, r["angles"]["gamma"], r["angles"]["beta"], r["cost_normalization"]["min"],
                                r["cost_normalization"]["span"])
            sub = await anyio.to_thread.run_sync(lambda: router.submit(
                problem, data, qasm, shots, layers, {"angles": r["angles"], "algorithm": r["algorithm"]},
                chosen.id, policy, max_cost_usd, agent_id or _who(ctx)))
        except (qaoa.ProblemError, HardwareError) as e:
            if reservation:
                mandates.refund(reservation)
            return _result({"error": str(e), "backends": "see quantum_backends"}, is_error=True)
        if reservation:
            mandates.bind_job(reservation, sub["job_id"])
        j = await anyio.to_thread.run_sync(finalize_hw, sub["job_id"])
        return _result({**hw_view(j), "routing": sub["routing"], "copyright": COPYRIGHT})

    @mcp.tool(title="Quantum hardware job", annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                                                         idempotentHint=True, openWorldHint=True))
    async def quantum_hardware_job(
        job_id: Annotated[str, Field(description="hw_... id from quantum_run_hardware")],
    ) -> CallToolResult:
        """Status of a quantum hardware job; once done, the decision, measurement statistics, the signed attestation and
        the Quantum Advantage Receipt. Free."""
        j = await anyio.to_thread.run_sync(finalize_hw, job_id)
        if not j:
            return _result({"error": "unknown job_id"}, is_error=True)
        return _result(hw_view(j))

    # ---------------- Privi Quantum Mandates ----------------

    def _sign_url(mid: str) -> str:
        return f"{PUBLIC_URL}/quantum-mandates/{mid}"

    def _seal_mandate(mid: str, kind: str) -> str:
        m = mandates.get(mid)
        body = {"mandate_id": mid, "agent_id": m["agent_id"], "human_id": m["human_id"], "terms_sha256": m["terms_hash"],
                "terms_text": m["message"], "signed_with": "passkey (WebAuthn, user verified)"}
        if kind == "quantum_mandate_revocation":
            body.update(revoked_at=m["revoked_at"], revoked_by=m["revoked_by"], reason=m["revoke_reason"],
                        spent_usd=m["spent"] / 1_000_000)
        else:
            body.update(activated_at=m["activated_at"])
        att = attestor.issue(kind, body)
        mandates.set_attestation(mid, att["id"], "revocation_attestation_id" if kind.endswith("revocation") else "attestation_id")
        return att["id"]

    @mcp.tool(title="Quantum Mandate: request one", annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                                                                idempotentHint=False, openWorldHint=False))
    async def quantum_mandate_request(
        ctx: Context,
        budget_usd: Annotated[float, Field(description="Total the agent may spend on paid quantum hardware under this mandate", gt=0)],
        purpose: Annotated[str, Field(description="What the runs are for, in plain words (shown to the person who signs)")],
        max_per_job_usd: Annotated[float | None, Field(description="Most one job may cost (default: the whole budget)", gt=0)] = None,
        backends: Annotated[list[str] | None, Field(description="Allowed backend ids from quantum_backends (default: any paid backend)")] = None,
        problems: Annotated[list[str] | None, Field(description="Allowed problems (default: any)")] = None,
        max_shots: Annotated[int, Field(description="Most shots per job (1-10000)", ge=1, le=10000)] = 1000,
        days: Annotated[int, Field(description="How long the mandate lasts once signed (1-365)", ge=1, le=365)] = 30,
        privi_pass: Annotated[str | None, PASS_ARG] = None,
    ) -> CallToolResult:
        """Draft a Quantum Mandate: the spending terms under which this agent may run paid quantum hardware jobs.
        Returns a sign_url for the person who approved the agent; they sign the exact terms with their passkey. Free."""
        tok = privi_pass or ((ctx.headers or {}).get("x-privi-pass") if ctx.headers is not None else None)
        if blocked := realm_gate(ctx, tok, "quantum_mandate_request"):
            return blocked
        agent_id = inspector.agent_for_pass(tok)
        if not agent_id:
            return _result({"error": "send your Privi pass (inspector_pass) so Privi knows which agent is asking"}, is_error=True)
        appr = humans.approval(agent_id)
        if not appr or not appr["current"]:
            return _result({"error": "no current human approval for this agent: qagent_human_request first"}, is_error=True)
        try:
            a = accel._row(agent_id)
            known = {b.id: b.name for b in router.backends.values()}
            out = mandates.draft(a, appr["human_id"], budget_usd, max_per_job_usd, backends, problems, max_shots, days,
                                 purpose, known, list(qaoa.TEMPLATES))
        except (MandateError, AcceleratorError) as e:
            return _result({"error": str(e)}, is_error=True)
        return _result({**out, "sign_url": _sign_url(out["mandate_id"]),
                        "next": "Send sign_url to the person who approved you. Once they sign with their passkey, pass "
                                "mandate_id and privi_pass to quantum_run_hardware.",
                        "sign_within_hours": 72})

    @mcp.tool(title="Quantum Mandate: status", annotations=READ_ONLY)
    def quantum_mandate_status(mandate_id: Annotated[str, Field(description="qm_... id")]) -> CallToolResult:
        """A Quantum Mandate's terms, status (draft, active, expired, revoked), spend, remaining budget and every
        charge and refund. Free."""
        try:
            return _result({**mandates.public(mandate_id, with_spends=True), "page": _sign_url(mandate_id)})
        except MandateError as e:
            return _result({"error": str(e)}, is_error=True)

    @mcp.tool(title="Quantum Mandate: dry run", annotations=READ_ONLY)
    def quantum_mandate_check(
        mandate_id: Annotated[str, Field(description="qm_... id")],
        problem: Annotated[str, Field(description="Problem you plan to run")] = "balance_lines",
        backend: Annotated[str, Field(description="'auto' or a backend id")] = "auto",
        policy: Annotated[str, Field(description="cheapest | fastest | hardware")] = "hardware",
        shots: Annotated[int, Field(ge=1, le=10000)] = 1000,
    ) -> CallToolResult:
        """Would this paid run be allowed under the mandate? Picks the backend the router would use, estimates the
        price and checks it against every term without spending anything. Free."""
        if not mandates.get(mandate_id):
            return _result({"error": "unknown mandate"}, is_error=True)
        try:
            chosen, est, _ = router.choose(backend, policy, shots, None)
        except HardwareError as e:
            return _result({"allowed": False, "reasons": [str(e)], "mandate_id": mandate_id})
        d = mandates.decide(mandate_id, None, chosen.id, est, shots, problem)
        return _result({**d, "backend": chosen.id, "paid": bool(est)})

    @mcp.tool(title="Quantum Mandate: revoke (agent)", annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True,
                                                                                   idempotentHint=True, openWorldHint=False))
    async def quantum_mandate_revoke(
        ctx: Context,
        mandate_id: Annotated[str, Field(description="qm_... id")],
        reason: Annotated[str, Field(description="Why")] = "",
        privi_pass: Annotated[str | None, PASS_ARG] = None,
    ) -> CallToolResult:
        """The agent gives up its own mandate (the person can also revoke on the mandate page with their passkey).
        The revocation is signed and anchored. Free."""
        tok = privi_pass or ((ctx.headers or {}).get("x-privi-pass") if ctx.headers is not None else None)
        agent_id = inspector.agent_for_pass(tok)
        m = mandates.get(mandate_id)
        if not m:
            return _result({"error": "unknown mandate"}, is_error=True)
        if not agent_id or agent_id != m["agent_id"]:
            return _result({"error": "only the agent this mandate belongs to can revoke it here (send its Privi pass)"}, is_error=True)
        try:
            mandates.revoke(mandate_id, "agent", reason)
        except MandateError as e:
            return _result({"error": str(e)}, is_error=True)
        return _result({**mandates.public(mandate_id), "revocation_attestation_id": _seal_mandate(mandate_id, "quantum_mandate_revocation")})

    @mcp.tool(title="Crypto inventory (CBOM) for a company", annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True))
    async def pqc_crypto_inventory(
        organization: Annotated[str, Field(description="Company or agency name")],
        ctx: Context,
        domains: Annotated[list[str] | None, Field(description="Public hostnames to test live for TLS 1.3 and hybrid post-quantum key exchange (up to 20)")] = None,
        repos: Annotated[list[str] | None, Field(description="Public GitHub repositories to scan, e.g. ['https://github.com/acme/api', 'acme/web'] (up to 5)")] = None,
        files: Annotated[list[dict[str, str]] | None, Field(description="Extra code or config files: [{name, content}] (up to 50 files, 1 MB)")] = None,
        assets: Annotated[list[dict[str, Any]] | None, Field(description="Known cryptographic assets (same shape as pqc_readiness_package)")] = None,
        profile: Annotated[str, Field(description="company (NIST IR 8547 dates) | agency | contractor | nss_vendor")] = "company",
        long_lived_data: Annotated[bool, Field(description="Do these systems protect data that must stay secret past 2030? Raises priority (harvest now, decrypt later)")] = False,
    ) -> CallToolResult:
        """Point Privi at a company's domains and GitHub repositories and get one cryptographic bill of materials: every
        algorithm quantum computers will break, where it is, a prioritized migration plan with dates, a CycloneDX 1.6
        CBOM and a public report page, signed with ML-DSA-87 and anchored on chain. Repos are scanned in memory and not
        kept. Free."""
        if not limiter.allow(_who(ctx)):
            return _result({"error": f"rate limit: {settings.rate_per_min} calls per minute"}, is_error=True)
        if not (domains or repos or files or assets):
            return _result({"error": "give domains, repos, files and/or assets"}, is_error=True)
        prof = profile if profile in govpqc.PROFILES else "company"
        extra = [{**a, "sensitive_past_2030": a.get("sensitive_past_2030", long_lived_data)} for a in (assets or [])]
        try:
            out = await anyio.to_thread.run_sync(lambda: make_package(
                organization, extra, files, prof, "", "Submitted files", "high" if long_lived_data else "unknown", False,
                domains, repos))
        except (ValueError, inventory.InventoryError) as ex:
            return _result({"error": str(ex)}, is_error=True)
        out["next_step"] = ("quantum_run_hardware / quantum_advantage_receipt for optimization; vault_seal to re-wrap "
                            "long-lived data under hybrid ML-KEM now")
        return _result(out)

    def _vault_receipt(env_info: dict, label: str, structure_checked: bool) -> dict[str, Any]:
        att = attestor.issue("vault_protection", {"envelope_sha256": env_info["envelope_sha256"], "suite": env_info.get("suite"),
                                                  "recipient_key_id": env_info.get("recipient_key_id"),
                                                  "ciphertext_bytes": env_info.get("ciphertext_bytes"), "label": label[:200],
                                                  "structure_checked": structure_checked,
                                                  "statement": "This envelope existed, under this hybrid post-quantum "
                                                               "suite, no later than the anchored time."})
        return {"receipt_id": att["id"], "envelope_sha256": env_info["envelope_sha256"], "signatures": f"Ed25519 + {PQ_ALG}",
                "anchoring": "queued for anchoring on Base" if anchor_client else "anchoring not configured", **links(att["id"])}

    @mcp.tool(title="Privi Vault: new hybrid post-quantum key", annotations=ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, idempotentHint=False, openWorldHint=False))
    def vault_keygen(
        suite: Annotated[str, Field(description="X25519+ML-KEM-768 (default) | X25519+ML-KEM-1024 (CNSA 2.0 KEM level)")] = vault.DEFAULT_SUITE,
    ) -> CallToolResult:
        """Create a hybrid X25519 + ML-KEM (FIPS 203) key pair for Privi Vault. The private key is returned once and not
        stored here; for the strongest setup generate it locally with `python -m privi_quantum.vault keygen`. Free."""
        try:
            kp = vault.keygen(suite)
        except vault.VaultError as e:
            return _result({"error": str(e)}, is_error=True)
        return _result({**kp, "keep_private_key_safe": "Privi does not keep it; lose it and the data cannot be opened",
                        "local_tool": "pip install the Privi Quantum package and run python -m privi_quantum.vault keygen --out key.json"})

    @mcp.tool(title="Privi Vault: seal data (harvest-now-decrypt-later protection)", annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False))
    async def vault_seal(
        public_key: Annotated[dict[str, Any], Field(description="Recipient public key from vault_keygen")],
        ctx: Context,
        text: Annotated[str | None, Field(description="Text to protect")] = None,
        data_base64: Annotated[str | None, Field(description="Or bytes to protect, base64 (up to 5 MB)")] = None,
        label: Annotated[str, Field(description="What this is, e.g. 'supplier contract 2026' (kept in the envelope and receipt)")] = "",
    ) -> CallToolResult:
        """Re-wrap long-lived sensitive data under hybrid post-quantum encryption (X25519 + ML-KEM, AES-256-GCM) so data
        recorded today can't be decrypted by a future quantum computer. Returns the envelope and a signed protection
        receipt anchored on chain. Plaintext is not stored. Free."""
        if not limiter.allow(_who(ctx)):
            return _result({"error": f"rate limit: {settings.rate_per_min} calls per minute"}, is_error=True)
        if (text is None) == (data_base64 is None):
            return _result({"error": "give exactly one of text or data_base64"}, is_error=True)
        try:
            raw = text.encode() if text is not None else vault.b64d(data_base64, "data_base64")
            env = vault.seal(raw, public_key, label)
            info = vault.check_envelope(env)
        except vault.VaultError as e:
            return _result({"error": str(e)}, is_error=True)
        rc = await anyio.to_thread.run_sync(lambda: _vault_receipt(info, label, True))
        return _result({"envelope": env, "protection_receipt": rc, "suite": env["suite"],
                        "note": "Store the envelope anywhere; only the matching private key opens it."})

    @mcp.tool(title="Privi Vault: open an envelope", annotations=ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False))
    def vault_open(
        envelope: Annotated[dict[str, Any], Field(description="A Privi Vault envelope")],
        private_key: Annotated[dict[str, Any], Field(description="The recipient private key from vault_keygen")],
    ) -> CallToolResult:
        """Decrypt a Privi Vault envelope. Nothing is stored; for sensitive data prefer opening locally with
        `python -m privi_quantum.vault open`. Free."""
        try:
            pt = vault.open_(envelope, private_key)
        except vault.VaultError as e:
            return _result({"error": str(e)}, is_error=True)
        try:
            return _result({"text": pt.decode("utf-8"), "bytes": len(pt)})
        except UnicodeDecodeError:
            return _result({"data_base64": vault.b64e(pt), "bytes": len(pt)})

    @mcp.tool(title="Privi Vault: receipt for a locally sealed envelope", annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False))
    async def vault_receipt(
        ctx: Context,
        envelope: Annotated[dict[str, Any] | None, Field(description="An envelope sealed locally (checked for structure; nothing is decrypted)")] = None,
        envelope_sha256: Annotated[str | None, Field(description="Or only the envelope's SHA-256, so the envelope never leaves your machine")] = None,
        label: Annotated[str, Field(description="What this protects")] = "",
    ) -> CallToolResult:
        """Get a signed, chain-anchored protection receipt proving data was under hybrid post-quantum encryption by a
        given time, for envelopes sealed with the local Privi Vault tool. Free."""
        if not limiter.allow(_who(ctx)):
            return _result({"error": f"rate limit: {settings.rate_per_min} calls per minute"}, is_error=True)
        try:
            if envelope is not None:
                info, checked = vault.check_envelope(envelope), True
            elif envelope_sha256 and len(envelope_sha256) == 64 and all(c in "0123456789abcdef" for c in envelope_sha256.lower()):
                info, checked = {"envelope_sha256": envelope_sha256.lower()}, False
            else:
                return _result({"error": "give an envelope or its 64-character SHA-256"}, is_error=True)
        except vault.VaultError as e:
            return _result({"error": str(e)}, is_error=True)
        return _result(await anyio.to_thread.run_sync(lambda: _vault_receipt(info, label, checked)))

    @mcp.custom_route("/receipts/{aid}.json", methods=["GET"], include_in_schema=False)
    async def receipt_json(request: Request) -> JSONResponse:
        att = attestor.get(request.path_params["aid"])
        if not att or att["body"].get("kind") != "advantage_receipt":
            return JSONResponse({"error": "not found"}, status_code=404, headers=cors)
        return JSONResponse(att, headers=cors)

    @mcp.custom_route("/receipts/{aid}", methods=["GET"], include_in_schema=False)
    async def receipt_page(request: Request) -> Response:
        att = attestor.get(request.path_params["aid"])
        if not att or att["body"].get("kind") != "advantage_receipt":
            return HTMLResponse("<h1>Receipt not found</h1>", status_code=404)
        v = Attestor.verify(att, keys["ed25519"], keys["ml_dsa_87"])
        return HTMLResponse(render_receipt(att, v), headers={"Cache-Control": "no-store"})

    mcp._privi_finalize_open = finalize_open
    mcp._hw_poll_seconds = settings.hardware_poll_seconds

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

    # ---------------- human trust: biometric approval (passkeys) + ID verification ----------------

    @mcp.tool(title="Quantum Agent: ask your human to approve you", annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False))
    def qagent_human_request(
        agent_id: Annotated[str, Field(description="Your agent_id")],
        agent_token: Annotated[str, Field(description="Your agent_token")],
    ) -> CallToolResult:
        """Get a one-time link (valid 30 minutes) for the person accountable for this agent. They open it, approve the
        agent with a passkey (Face ID, Touch ID, Windows Hello or screen lock; the biometric never leaves their
        device) and verify a government ID with a live selfie. Both are required for the quantum realm."""
        try:
            a = accel.auth(agent_id, agent_token)
        except AcceleratorError as e:
            return _result({"error": str(e)}, is_error=True)
        r = humans.new_request(a["agent_id"])
        return _result({**r, "send_to": "the person accountable for this agent",
                        "id_verification_available": humans.stripe_ready})

    @mcp.tool(title="Privi Inspector: an agent's grade", annotations=READ_ONLY)
    def inspector_grade(agent_id: Annotated[str, Field(description="A Quantum Agent id")]) -> CallToolResult:
        """An agent's Privi trust grade (A+ to F, 0-100): quantum level, passkey approval by a verified human, ID
        verification, current certificate, key strength and clean record, minus penalties for revocation and
        impersonation. Shows what is missing and what the quantum realm requires. Free."""
        g = inspector.grade(agent_id)
        return _result(g, is_error="error" in g)

    @mcp.custom_route("/humans/approve/{request_id}", methods=["GET"], include_in_schema=False)
    async def human_page(request: Request) -> Response:
        rid = request.path_params["request_id"]
        try:
            req = humans.request(rid)
            a = accel._row(req["agent_id"])
        except (HumanError, AcceleratorError) as e:
            return Response(HUMAN_DONE.format(title="Link not valid", body=_h(str(e))), status_code=404,
                            media_type="text/html; charset=utf-8")
        return Response(HUMAN_PAGE.format(rid=_h(rid), name=_h(a["name"]), operator=_h(a["operator"]),
                                          agent_id=_h(a["agent_id"]), fp=_h(a["key_fingerprint"][:16]),
                                          level=_h(LEVEL_LABEL[a["level"]]), alg=_h(a["key_alg"]),
                                          idready="true" if humans.stripe_ready else "false"),
                        media_type="text/html; charset=utf-8",
                        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})

    @mcp.custom_route("/humans/approve/{request_id}/options", methods=["GET"], include_in_schema=False)
    async def human_options(request: Request) -> JSONResponse:
        rid = request.path_params["request_id"]
        try:
            req = humans.request(rid)
            a = accel._row(req["agent_id"])
            return JSONResponse(humans.options(rid, a["key_fingerprint"], a["name"]), headers={"Cache-Control": "no-store"})
        except (HumanError, AcceleratorError) as e:
            return JSONResponse({"error": str(e)}, status_code=404)

    @mcp.custom_route("/humans/approve/{request_id}/finish", methods=["POST"], include_in_schema=False)
    async def human_finish(request: Request) -> JSONResponse:
        rid = request.path_params["request_id"]
        try:
            req = humans.request(rid)
            a = accel._row(req["agent_id"])
            cred = await request.json()
            if not isinstance(cred, dict):
                raise HumanError("send the passkey response as JSON")
            out = humans.finish(rid, a["agent_id"], a["key_fingerprint"], cred)
        except (HumanError, AcceleratorError, ValueError, KeyError, TypeError) as e:
            return JSONResponse({"error": str(e) or "could not verify the passkey"}, status_code=400)
        return JSONResponse({**out, "agent": a["name"], "id_verification_available": humans.stripe_ready},
                            headers={"Cache-Control": "no-store"})

    @mcp.custom_route("/humans/id/start", methods=["POST"], include_in_schema=False)
    async def human_id_start(request: Request) -> JSONResponse:
        try:
            b = await request.json()
            out = await anyio.to_thread.run_sync(humans.start_id, str((b or {}).get("human_session", "")))
        except (HumanError, ValueError, KeyError, TypeError) as e:
            return JSONResponse({"error": str(e) or "could not start ID verification"}, status_code=400)
        return JSONResponse(out, headers={"Cache-Control": "no-store"})

    @mcp.custom_route("/humans/id/return", methods=["GET"], include_in_schema=False)
    async def human_id_return(request: Request) -> Response:
        try:
            st = await anyio.to_thread.run_sync(humans.refresh_id, request.query_params.get("human", ""))
        except HumanError as e:
            return Response(HUMAN_DONE.format(title="Not found", body=_h(str(e))), status_code=404,
                            media_type="text/html; charset=utf-8")
        msg = {"verified": "Your ID is verified. Your approved agents can now use the Privi quantum realm.",
               "pending": "Stripe is still checking your ID. This page will say verified once it is done; you can close it.",
               "failed": "The ID check did not complete. Ask the agent for a new approval link to try again."}
        return Response(HUMAN_DONE.format(title="ID verification", body=_h(msg.get(st["id_status"], "Status: " + st["id_status"]))),
                        media_type="text/html; charset=utf-8")

    @mcp.custom_route("/humans/stripe-webhook", methods=["POST"], include_in_schema=False)
    async def human_stripe_webhook(request: Request) -> JSONResponse:
        try:
            out = humans.stripe_webhook(await request.body(), request.headers.get("stripe-signature", ""))
        except HumanError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        except ValueError:
            return JSONResponse({"error": "bad payload"}, status_code=400)
        return JSONResponse(out)

    @mcp.custom_route("/humans/{human_id}/id-verified", methods=["POST", "DELETE"], include_in_schema=False)
    async def human_manual_id(request: Request) -> JSONResponse:
        if not _admin(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        hid = request.path_params["human_id"]
        try:
            if request.method == "DELETE":
                return JSONResponse(humans.revoke_id(hid))
            try:
                b = await request.json()
            except ValueError:
                b = {}
            return JSONResponse(humans.manual_verify(hid, str((b or {}).get("note", ""))))
        except HumanError:
            return JSONResponse({"error": "not found"}, status_code=404)

    @mcp.custom_route("/inspector/grade/{agent_id}", methods=["GET"], include_in_schema=False)
    async def inspector_grade_http(request: Request) -> JSONResponse:
        g = inspector.grade(request.path_params["agent_id"])
        return JSONResponse(g, status_code=404 if "error" in g else 200, headers=cors_pub)

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
    mcp._humans = humans
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

    # ---------------- Privi Explorer feed (public, hashes only) ----------------

    PUBLIC_PAGES = {"advantage_receipt": "/receipts/", "pqc_readiness": "/reports/"}

    @mcp.custom_route("/explorer/recent", methods=["GET"], include_in_schema=False)
    async def explorer_recent(request: Request) -> JSONResponse:
        q = request.query_params
        lim = int(q["limit"]) if q.get("limit", "").isdigit() else 25
        before = int(q["before"]) if q.get("before", "").isdigit() else None
        return JSONResponse({"total": attestor.count(), "by_kind": attestor.kind_counts(), "key_id": keys["key_id"],
                             "attestations": attestor.recent(lim, before)},
                            headers={**cors, "Cache-Control": "no-store"})

    @mcp.custom_route("/explorer/lookup", methods=["GET"], include_in_schema=False)
    async def explorer_lookup(request: Request) -> JSONResponse:
        """Find one attestation by its id (qa_...) or its body SHA-256, and check both signatures.
        A lookup by hash proves the record exists and is genuine but never reveals the id or contents."""
        term = request.query_params.get("q", "").strip()[:80]
        by_id = term.startswith("qa_")
        att = attestor.get(term) if by_id else attestor.find_by_hash(term) if len(term) == 64 else None
        if not att:
            return JSONResponse({"found": False, "q": term}, status_code=404, headers={**cors, "Cache-Control": "no-store"})
        v = Attestor.verify(att, keys["ed25519"], keys["ml_dsa_87"])
        kind = att["body"].get("kind")
        out: dict[str, Any] = {"found": True, "kind": kind, "issued_at": att["body"].get("issued_at"),
                               "body_sha256": att["body_sha256"], "key_id": att["key_id"],
                               "anchor": Attestor._public_anchor(json.dumps(att["anchor"]) if att["anchor"] else None),
                               "signatures": {"ed25519": v.get("ed25519_valid"), "ml_dsa_87": v.get("ml_dsa_87_valid"),
                                              "body_hash_matches": v.get("body_hash_matches"), "valid": v.get("valid")}}
        if by_id:
            out["id"] = att["id"]
            out["json"] = f"{PUBLIC_URL}/attestations/{att['id']}"
            if kind in PUBLIC_PAGES:
                out["page"] = f"{PUBLIC_URL}{PUBLIC_PAGES[kind]}{att['id']}"
            if kind == "advantage_receipt":
                out["verdict"] = att["body"].get("verdict")
        return JSONResponse(out, headers={**cors, "Cache-Control": "no-store"})

    @mcp.custom_route("/quantum-mandates/{mid}.json", methods=["GET"], include_in_schema=False)
    async def qmandate_json(request: Request) -> JSONResponse:
        try:
            return JSONResponse(mandates.public(request.path_params["mid"], with_spends=True),
                                headers={**cors, "Cache-Control": "no-store"})
        except MandateError as e:
            return JSONResponse({"error": str(e)}, status_code=404, headers=cors)

    @mcp.custom_route("/quantum-mandates/{mid}/options", methods=["GET"], include_in_schema=False)
    async def qmandate_options(request: Request) -> JSONResponse:
        try:
            ch = mandates.challenge(request.path_params["mid"], request.query_params.get("action", "sign"))
        except MandateError as e:
            return JSONResponse({"error": str(e)}, status_code=404)
        return JSONResponse({"get": humans.get_options(ch)}, headers={"Cache-Control": "no-store"})

    @mcp.custom_route("/quantum-mandates/{mid}/sign", methods=["POST"], include_in_schema=False)
    async def qmandate_sign(request: Request) -> JSONResponse:
        mid = request.path_params["mid"]
        try:
            cred = await request.json()
            if not isinstance(cred, dict):
                raise HumanError("send the passkey response as JSON")
            hid, cid = humans.verify_assertion(cred, mandates.challenge(mid, "sign"))
            mandates.activate(mid, hid, cid, humans.human(hid)["id_status"] == "verified")
        except (HumanError, MandateError, ValueError, KeyError, TypeError) as e:
            return JSONResponse({"error": str(e) or "could not verify the passkey"}, status_code=400)
        aid = _seal_mandate(mid, "quantum_mandate")
        return JSONResponse({**mandates.public(mid), "attestation_id": aid}, headers={"Cache-Control": "no-store"})

    @mcp.custom_route("/quantum-mandates/{mid}/revoke", methods=["POST"], include_in_schema=False)
    async def qmandate_revoke(request: Request) -> JSONResponse:
        mid = request.path_params["mid"]
        try:
            cred = await request.json()
            if not isinstance(cred, dict):
                raise HumanError("send the passkey response as JSON")
            m = mandates.get(mid)
            if not m:
                raise MandateError("unknown mandate")
            hid, _ = humans.verify_assertion(cred, mandates.challenge(mid, "revoke"))
            if hid != m["human_id"]:
                raise MandateError("only the person who signed this mandate can revoke it")
            mandates.revoke(mid, "human", "revoked by the person who signed it")
        except (HumanError, MandateError, ValueError, KeyError, TypeError) as e:
            return JSONResponse({"error": str(e) or "could not verify the passkey"}, status_code=400)
        aid = _seal_mandate(mid, "quantum_mandate_revocation")
        return JSONResponse({**mandates.public(mid), "revocation_attestation_id": aid}, headers={"Cache-Control": "no-store"})

    @mcp.custom_route("/quantum-mandates/{mid}", methods=["GET"], include_in_schema=False)
    async def qmandate_page(request: Request) -> Response:
        mid = request.path_params["mid"]
        try:
            m = mandates.public(mid, with_spends=True)
            a = accel._row(m["agent_id"])
        except (MandateError, AcceleratorError) as e:
            return Response(HUMAN_DONE.format(title="Mandate not found", body=_h(str(e))), status_code=404,
                            media_type="text/html; charset=utf-8")
        return Response(render_mandate(m, a), media_type="text/html; charset=utf-8",
                        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})

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


HUMAN_PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Approve an AI agent - Privi</title><style>body{{font:16px/1.55 system-ui,sans-serif;max-width:560px;margin:40px auto;padding:0 16px;color:#16181d;background:#f7f8fa}}
.card{{background:#fff;border:1px solid #d9dce3;border-radius:12px;padding:16px 18px;margin:16px 0}}dt{{color:#5b6170;font-size:13px}}dd{{margin:0 0 8px}}
button{{font:600 16px system-ui,sans-serif;padding:12px 16px;border-radius:10px;border:0;background:#5b3fd6;color:#fff;width:100%;margin:6px 0;cursor:pointer}}
button.alt{{background:#e7e3fb;color:#2d1f73}}button:disabled{{opacity:.5}}#msg{{min-height:24px;margin-top:10px}}.ok{{color:#1f7a45}}.bad{{color:#b23a2e}}small{{color:#5b6170}}
@media (prefers-color-scheme:dark){{body{{color:#e8eaee;background:#0f1115}}.card{{background:#171a21;border-color:#2a2f3a}}button.alt{{background:#2a2450;color:#e4ddff}}}}</style></head><body>
<h1>Approve this AI agent?</h1>
<p>An AI agent wants your approval to use the Privi quantum realm. Only approve an agent you run or are accountable for.</p>
<div class="card"><dl><dt>Agent</dt><dd><b>{name}</b> ({agent_id})</dd><dt>Operator</dt><dd>{operator}</dd>
<dt>Level</dt><dd>{level}</dd><dt>Post-quantum key</dt><dd>{alg}, fingerprint {fp}...</dd></dl></div>
<button id="get">Approve with my Privi passkey</button>
<button id="create" class="alt">First time? Create a passkey and approve</button>
<div id="idbox" hidden><p>Last step: verify your government ID with a live selfie (Stripe Identity). Privi never sees your ID or photo.</p>
<button id="id">Verify my ID</button></div>
<div id="msg"></div>
<p><small>Your phone or computer checks your face, fingerprint or screen lock. That check stays on your device: Privi receives only
a signature that says a verified person approved this exact agent and key. Privi World Co, Port Huron, Michigan.</small></p>
<script>
const rid="{rid}", idReady={idready};
const b64u=b=>btoa(String.fromCharCode(...new Uint8Array(b))).replace(/\+/g,"-").replace(/\//g,"_").replace(/=+$/,"");
const unb=s=>Uint8Array.from(atob(s.replace(/-/g,"+").replace(/_/g,"/")+"===".slice((s.length+3)%4)),c=>c.charCodeAt(0));
const msg=(t,c)=>{{const m=document.getElementById("msg");m.textContent=t;m.className=c||"";}};
let session="";
async function go(mode){{
  if(!window.PublicKeyCredential){{msg("This browser does not support passkeys. Open the link on a phone or a recent browser.","bad");return;}}
  document.querySelectorAll("button").forEach(b=>b.disabled=true);
  try{{
    const o=await (await fetch(`/humans/approve/${{rid}}/options`)).json();
    if(o.error) throw new Error(o.error);
    let cred;
    if(mode==="create"){{const p=o.create;p.challenge=unb(p.challenge);p.user.id=unb(p.user.id);cred=await navigator.credentials.create({{publicKey:p}});}}
    else{{const p=o.get;p.challenge=unb(p.challenge);cred=await navigator.credentials.get({{publicKey:p}});}}
    const r=cred.response, body={{id:cred.id,rawId:b64u(cred.rawId),type:cred.type,response:{{clientDataJSON:b64u(r.clientDataJSON)}}}};
    if(r.attestationObject) body.response.attestationObject=b64u(r.attestationObject);
    if(r.authenticatorData){{body.response.authenticatorData=b64u(r.authenticatorData);body.response.signature=b64u(r.signature);}}
    const res=await (await fetch(`/humans/approve/${{rid}}/finish`,{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify(body)}})).json();
    if(res.error) throw new Error(res.error);
    session=res.human_session;
    if(res.id_verified){{msg("Approved. Your ID is already verified, so this agent can use the quantum realm.","ok");}}
    else if(idReady){{msg("Approved with your passkey.","ok");document.getElementById("idbox").hidden=false;document.getElementById("id").disabled=false;}}
    else{{msg("Approved with your passkey. ID verification is not open yet; Privi will switch it on soon.","ok");}}
  }}catch(e){{msg(e.name==="NotAllowedError"?"Cancelled or timed out. Try again.":(e.message||"Something went wrong."),"bad");
    document.querySelectorAll("#get,#create").forEach(b=>b.disabled=false);}}
}}
document.getElementById("get").onclick=()=>go("get");
document.getElementById("create").onclick=()=>go("create");
document.getElementById("id").onclick=async()=>{{
  const r=await (await fetch("/humans/id/start",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{human_session:session}})}})).json();
  if(r.verify_url) location.href=r.verify_url; else if(r.id_status==="verified") msg("Your ID is already verified.","ok"); else msg(r.error||"Could not start.","bad");
}};
</script></body></html>"""

HUMAN_DONE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} - Privi</title><style>body{{font:16px/1.55 system-ui,sans-serif;max-width:560px;margin:40px auto;padding:0 16px;color:#16181d;background:#f7f8fa}}
@media (prefers-color-scheme:dark){{body{{color:#e8eaee;background:#0f1115}}}}</style></head><body><h1>{title}</h1><p>{body}</p></body></html>"""


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


def render_mandate(m: dict, a: dict) -> str:
    """The page a person opens to read, sign or revoke a Quantum Mandate with their passkey."""
    st = m["status"]
    badge = {"draft": ("#8a5a00", "Waiting for your signature"), "active": ("#0a7d4f", "Active"),
             "expired": ("#44546a", "Expired"), "revoked": ("#b23a2e", "Revoked")}[st]
    spends = "".join(f"<tr><td>{_h(x['at'][:16].replace('T', ' '))}</td><td>{_h(x['backend'])}</td><td>{_h(x['shots'])}</td>"
                     f"<td>${x['usd']:.2f}</td><td>{_h(x['status'])}</td></tr>" for x in m.get("spends", []))
    spend_tbl = (f"<table><tr><th>When (UTC)</th><th>Backend</th><th>Shots</th><th>Cost</th><th></th></tr>{spends}</table>"
                 if spends else "<p class=muted>No paid runs yet.</p>")
    action = "sign" if st == "draft" else "revoke" if st == "active" else ""
    button = ("<button id=go>Sign with my passkey</button>" if action == "sign" else
              "<button id=go class=danger>Revoke with my passkey</button>" if action == "revoke" else "")
    idnote = ("<p class=muted>This budget is over the ID threshold, so your government ID must be verified "
              "(you can do that from the agent approval link).</p>" if m["needs_id_verification"] and st == "draft" else "")
    att = (f"<p class=muted>Sealed as attestation <a href='/attestations/{_h(m['attestation_id'])}'>{_h(m['attestation_id'])}</a> "
           "(Ed25519 + ML-DSA-87), anchored on Base.</p>" if m["attestation_id"] else "")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Quantum Mandate - Privi</title><style>
:root{{--bg:#f7f8fa;--fg:#16181d;--card:#fff;--line:#d9dce3;--muted:#5b6170;--brand:#5b3fd6}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0f1115;--fg:#e8eaee;--card:#171a21;--line:#2a2f3a;--muted:#9aa3b2;--brand:#a995ff}}}}
body{{font:16px/1.55 system-ui,sans-serif;max-width:640px;margin:36px auto;padding:0 16px;color:var(--fg);background:var(--bg)}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin:16px 0}}
pre{{white-space:pre-wrap;font:14px/1.55 ui-monospace,monospace;margin:0}}.muted{{color:var(--muted);font-size:14px}}
.badge{{display:inline-block;font:600 13px system-ui;padding:3px 9px;border-radius:999px;color:#fff;background:{badge[0]}}}
dl{{display:grid;grid-template-columns:auto 1fr;gap:4px 14px;margin:0}}dt{{color:var(--muted)}}dd{{margin:0}}
table{{border-collapse:collapse;width:100%;font-size:14px}}td,th{{text-align:left;padding:6px;border-bottom:1px solid var(--line)}}
button{{font:600 16px system-ui;padding:12px 16px;border-radius:10px;border:0;background:var(--brand);color:#fff;width:100%;cursor:pointer}}
button.danger{{background:#b23a2e}}button:disabled{{opacity:.5}}a{{color:var(--brand)}}#msg{{min-height:24px;margin-top:10px}}.ok{{color:#1f7a45}}.bad{{color:#b23a2e}}
</style></head><body>
<h1>Quantum Mandate</h1>
<p><span class="badge">{badge[1]}</span> &nbsp;<span class="muted">{_h(m['mandate_id'])}</span></p>
<p>The AI agent <b>{_h(a['name'])}</b> (operated by {_h(a['operator'])}) asks to spend on paid quantum computers on your
behalf. Read the exact terms. Signing uses your Privi passkey; only the person who approved this agent can sign.</p>
<div class="card"><pre>{_h(m['terms_text'])}</pre></div>
<div class="card"><dl><dt>Spent</dt><dd>${m['spent_usd']:.2f} of ${m['terms']['budget_usd']:.2f}</dd>
<dt>Remaining</dt><dd>${m['remaining_usd']:.2f}</dd><dt>Terms SHA-256</dt><dd style="overflow-wrap:anywhere"><code>{_h(m['terms_sha256'])}</code></dd></dl></div>
{idnote}{button}<div id="msg"></div>
<h2>Paid runs</h2>{spend_tbl}{att}
<p class="muted">Your device checks your face, fingerprint or screen lock; Privi receives only a passkey signature over these
exact terms. Every paid run is checked against them, failed jobs are refunded, and you can revoke here at any time.
Privi World Co, Port Huron, Michigan.</p>
<script>
const mid={json.dumps(m['mandate_id'])}, action={json.dumps(action)};
const b64u=b=>btoa(String.fromCharCode(...new Uint8Array(b))).replace(/\\+/g,"-").replace(/\\//g,"_").replace(/=+$/,"");
const unb=s=>Uint8Array.from(atob(s.replace(/-/g,"+").replace(/_/g,"/")+"===".slice((s.length+3)%4)),c=>c.charCodeAt(0));
const msg=(t,c)=>{{const e=document.getElementById("msg");e.textContent=t;e.className=c||"";}};
const btn=document.getElementById("go");
if(btn) btn.onclick=async()=>{{
  if(!window.PublicKeyCredential){{msg("This browser does not support passkeys. Open the link on a phone or a recent browser.","bad");return;}}
  btn.disabled=true;
  try{{
    const o=await (await fetch(`/quantum-mandates/${{mid}}/options?action=${{action}}`)).json();
    if(o.error) throw new Error(o.error);
    const p=o.get; p.challenge=unb(p.challenge);
    const cred=await navigator.credentials.get({{publicKey:p}});
    const r=cred.response, body={{id:cred.id,rawId:b64u(cred.rawId),type:cred.type,response:{{clientDataJSON:b64u(r.clientDataJSON),
      authenticatorData:b64u(r.authenticatorData),signature:b64u(r.signature)}}}};
    const res=await (await fetch(`/quantum-mandates/${{mid}}/${{action}}`,{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify(body)}})).json();
    if(res.error) throw new Error(res.error);
    msg(action==="sign"?"Signed. The agent can now run paid quantum jobs within these terms.":"Revoked. No more paid runs under this mandate.","ok");
    setTimeout(()=>location.reload(),1500);
  }}catch(e){{msg(e.name==="NotAllowedError"?"Cancelled or timed out. Try again.":(e.message||"Something went wrong."),"bad");btn.disabled=false;}}
}};
</script></body></html>"""


def render_receipt(att: dict, v: dict) -> str:
    """Public page for a Quantum Advantage Receipt."""
    b = att["body"]
    q = b["quantum"]
    color = {"quantum_won": "#0a7d4f", "classical_won": "#8a5a00", "tie": "#44546a"}.get(b["verdict"], "#44546a")
    rows = "".join(f"<tr><td>{_h(c['method'])}</td><td>{_h(c['cost'])}</td><td>{_h(c['runtime_ms'])} ms</td>"
                   f"<td>{_h(c['about'])}</td></tr>" for c in b["classical"])
    anc = att.get("anchor")
    anchor = (f"Anchored on chain {_h(anc.get('chain_id'))}, tx <code>{_h(anc.get('tx_hash'))}</code>" if anc
              else "Waiting for the next on-chain anchor batch (every few minutes)")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Quantum Advantage Receipt</title><style>
:root{{--bg:#f7f8fa;--fg:#14181f;--card:#fff;--line:#dde2ea;--muted:#5b6575}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0f1217;--fg:#e8ecf2;--card:#171b22;--line:#2a313c;--muted:#9aa5b5}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}}
main{{max-width:820px;margin:0 auto;padding:24px 16px}}.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px;margin:14px 0}}
.v{{display:inline-block;padding:4px 10px;border-radius:999px;color:#fff;background:{color};font-weight:600}}
table{{width:100%;border-collapse:collapse}}td,th{{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}}
.muted{{color:var(--muted)}}code{{word-break:break-all}}.t{{overflow-x:auto}}</style></head><body><main>
<div class="muted">Privi Quantum · Quantum Advantage Receipt · {_h(att['id'])}</div>
<h1>{_h(b['problem'])} · {_h(b['qubits'])} qubits</h1>
<p><span class="v">{_h(b['verdict'].replace('_', ' '))}</span> {_h(b['why'])}</p>
<section class="card"><h2>Quantum</h2><div class="t"><table>
<tr><th>Backend</th><td>{_h(q.get('backend'))} ({_h(q.get('backend_kind'))})</td></tr>
<tr><th>Method</th><td>{_h(q.get('method'))}</td></tr><tr><th>Best cost</th><td>{_h(q.get('cost'))}</td></tr>
<tr><th>Found the proven optimum</th><td>{_h(q.get('found_optimum'))} (in {_h(q.get('optimum_frequency'))} of shots)</td></tr>
<tr><th>Time</th><td>{_h(q.get('runtime_ms'))} ms</td></tr></table></div></section>
<section class="card"><h2>Classical baselines</h2><div class="t"><table><tr><th>Method</th><th>Best cost</th><th>Time</th><th>How</th></tr>{rows}</table></div></section>
<section class="card"><h2>Proof</h2><p>Signatures Ed25519 + ML-DSA-87: <b>{'valid' if v.get('valid') else 'INVALID'}</b>. {anchor}.</p>
<p class="muted">{_h(b['timing_note'])}. {_h(b['honesty'])}</p>
<p class="muted">Issued {_h(b['issued_at'])} · <a href="{PUBLIC_URL}/receipts/{_h(att['id'])}.json">signed JSON</a> ·
<a href="{PUBLIC_URL}/keys">public keys</a></p></section>
<p class="muted"><small>{COPYRIGHT}</small></p></main></body></html>"""


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


def _hardware_loop(finalize_open, interval: int) -> None:
    while True:
        time.sleep(interval)
        try:
            n = finalize_open()
            if n:
                print(f"[privi-quantum] sealed {n} finished quantum hardware job(s)", flush=True)
        except Exception as e:  # keep polling
            print(f"[privi-quantum] hardware poll failed, will retry: {e}", flush=True)


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
    if mcp._hw_poll_seconds > 0:
        threading.Thread(target=_hardware_loop, args=(mcp._privi_finalize_open, mcp._hw_poll_seconds), daemon=True).start()
    if args.stdio:
        mcp.run("stdio")
        return
    import uvicorn
    from .front import QuickGet
    uvicorn.run(QuickGet(http_app(mcp, host=args.host), "Privi Quantum", "privi-quantum", PUBLIC_URL),
                host=args.host, port=args.port)


if __name__ == "__main__":
    main()
