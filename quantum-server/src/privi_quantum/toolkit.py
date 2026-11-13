# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Quantum - https://priviflow.us - dariocanoy@priviflow.us
"""Privi Quantum Toolkit: five planning tools for the move to post-quantum cryptography.

- pqc_certificate_check   read X.509 certificates and say which keys a quantum computer could break, and when they expire
- pqc_harvest_risk        "harvest now, decrypt later" exposure for each kind of data you hold (Mosca's inequality)
- pqc_size_impact         how many more bytes each handshake or signature costs after switching algorithm
- quantum_circuit_stats   qubits, gate counts and depth of an OpenQASM circuit before you pay to run it
- pqc_supplier_score      score a supplier's post-quantum readiness answers and issue a signed scorecard
"""
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Annotated, Any

from mcp_types import CallToolResult, TextContent, ToolAnnotations
from pydantic import Field

from . import circuits
from .govpqc import KEY_ESTABLISHMENT_DEADLINE, REMAINING_SYSTEMS_YEAR, SIGNATURE_DEADLINE

READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)

# Proposed prices (USD per call, x402). Merged into payments.DEFAULT_PRICES_USD; override with QUANTUM_PRICE_<TOOL>.
PRICES = {"pqc_certificate_check": "0.05", "pqc_harvest_risk": "0.05", "pqc_size_impact": "0.01",
          "quantum_circuit_stats": "0.01", "pqc_supplier_score": "1"}


class ToolkitError(ValueError):
    pass


# ---------------------------------------------------------------- 1. certificates

MAX_CERTS = 20
PQ_OIDS = {  # NIST CSOR object identifiers for the FIPS 204 / 205 signature algorithms
    "2.16.840.1.101.3.4.3.17": "ML-DSA-44", "2.16.840.1.101.3.4.3.18": "ML-DSA-65",
    "2.16.840.1.101.3.4.3.19": "ML-DSA-87",
    **{f"2.16.840.1.101.3.4.3.{n}": "SLH-DSA" for n in range(20, 32)},
}


def _key_info(cert) -> dict[str, Any]:
    from cryptography.hazmat.primitives.asymmetric import dsa, ec, ed448, ed25519, rsa
    oid = getattr(cert, "public_key_algorithm_oid", None)
    dotted = oid.dotted_string if oid is not None else ""
    if dotted in PQ_OIDS:
        return {"algorithm": PQ_OIDS[dotted], "quantum_safe": True}
    try:
        key = cert.public_key()
    except Exception:
        return {"algorithm": f"unrecognized ({dotted or 'unknown'})", "quantum_safe": None}
    if isinstance(key, rsa.RSAPublicKey):
        return {"algorithm": f"RSA-{key.key_size}", "bits": key.key_size, "quantum_safe": False,
                "classical_112_bit_class": key.key_size < 3072}
    if isinstance(key, ec.EllipticCurvePublicKey):
        return {"algorithm": f"ECDSA {key.curve.name}", "bits": key.curve.key_size, "quantum_safe": False,
                "classical_112_bit_class": key.curve.key_size < 256}
    if isinstance(key, (ed25519.Ed25519PublicKey, ed448.Ed448PublicKey)):
        return {"algorithm": type(key).__name__.replace("PublicKey", ""), "quantum_safe": False}
    if isinstance(key, dsa.DSAPublicKey):
        return {"algorithm": f"DSA-{key.key_size}", "bits": key.key_size, "quantum_safe": False,
                "classical_112_bit_class": True}
    name = type(key).__name__.replace("PublicKey", "")
    return {"algorithm": name, "quantum_safe": True if name.upper().startswith(("MLDSA", "SLHDSA")) else None}


def certificate_check(pem: str, now: datetime | None = None) -> dict[str, Any]:
    from cryptography import x509
    if not isinstance(pem, str) or "BEGIN CERTIFICATE" not in pem:
        raise ToolkitError("send one or more PEM certificates (-----BEGIN CERTIFICATE-----)")
    if len(pem) > 400_000:
        raise ToolkitError("certificate text is over 400 KB")
    try:
        certs = x509.load_pem_x509_certificates(pem.encode())
    except Exception as e:
        raise ToolkitError(f"could not read the certificates: {e}") from None
    if len(certs) > MAX_CERTS:
        raise ToolkitError(f"at most {MAX_CERTS} certificates per call")
    now = now or datetime.now(timezone.utc)
    sig_deadline = datetime.fromisoformat(SIGNATURE_DEADLINE + "T23:59:59+00:00")
    end_2030 = datetime(2030, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
    end_final = datetime(int(REMAINING_SYSTEMS_YEAR), 12, 31, 23, 59, 59, tzinfo=timezone.utc)
    out, worst = [], "ok"
    rank = {"ok": 0, "low": 1, "medium": 2, "high": 3}
    for c in certs:
        key, findings = _key_info(c), []
        sig_oid = c.signature_algorithm_oid.dotted_string
        sig_name = PQ_OIDS.get(sig_oid) or getattr(c.signature_algorithm_oid, "_name", sig_oid)
        after = c.not_valid_after_utc

        def add(sev: str, text: str):
            findings.append({"severity": sev, "finding": text})
        if after < now:
            add("high", "certificate has expired")
        if key["quantum_safe"] is False:
            if after > end_final:
                add("high", f"quantum-vulnerable key is valid past {REMAINING_SYSTEMS_YEAR}, when NIST IR 8547 (draft) "
                            "disallows these algorithms; reissue with a shorter life or a post-quantum key")
            elif after > sig_deadline:
                add("medium", f"quantum-vulnerable key is valid past {SIGNATURE_DEADLINE}, the federal date for "
                              "post-quantum signatures on high-impact systems")
            else:
                add("low", "quantum-vulnerable key; plan its post-quantum replacement at the next renewal")
            if key.get("classical_112_bit_class") and after > end_2030:
                add("medium", "112-bit-class key (e.g. RSA-2048) valid past 2030, when NIST IR 8547 (draft) deprecates it")
        elif key["quantum_safe"] is None:
            add("low", "key algorithm not recognized; check it by hand")
        if sig_oid not in PQ_OIDS and key["quantum_safe"] is True:
            add("low", "post-quantum key but the issuer signed it with a classical algorithm")
        sev = max((f["severity"] for f in findings), key=rank.get, default="ok")
        worst = max(worst, sev, key=rank.get)
        out.append({"subject": c.subject.rfc4514_string(), "issuer": c.issuer.rfc4514_string(),
                    "serial": format(c.serial_number, "x"), "key": key, "signed_with": sig_name,
                    "not_before": c.not_valid_before_utc.isoformat(), "not_after": after.isoformat(),
                    "days_left": (after - now).days, "severity": sev, "findings": findings})
    vuln = sum(1 for c in out if c["key"]["quantum_safe"] is False)
    return {"certificates": out, "count": len(out), "quantum_vulnerable": vuln, "worst_severity": worst,
            "dates_used": {"post_quantum_signatures_high_impact": SIGNATURE_DEADLINE,
                           "vulnerable_algorithms_disallowed_after": REMAINING_SYSTEMS_YEAR,
                           "source": "see pqc_federal_deadlines"},
            "note": "Reads the certificates you send; it does not connect anywhere. Use pqc_endpoint_check to test a live server."}


# ---------------------------------------------------------------- 2. harvest now, decrypt later

SAFE_PROTECTION = ("ml-kem", "mlkem", "kyber", "hybrid", "aes-256", "aes256", "chacha20", "symmetric", "post-quantum", "pqc")
DEFAULT_SCENARIOS = (2030, 2035, 2040)


def harvest_risk(datasets: list[dict], migration_years: float, quantum_years: list[int] | None = None,
                 this_year: int | None = None) -> dict[str, Any]:
    if not isinstance(datasets, list) or not 1 <= len(datasets) <= 50:
        raise ToolkitError("datasets must list 1-50 kinds of data")
    if not isinstance(migration_years, (int, float)) or not 0 <= migration_years <= 30:
        raise ToolkitError("migration_years must be 0-30 (how long your move to post-quantum encryption will take)")
    year = this_year or datetime.now(timezone.utc).year
    scenarios = sorted(set(quantum_years or DEFAULT_SCENARIOS))
    if not scenarios or len(scenarios) > 6 or any(not isinstance(y, int) or not year <= y <= year + 50 for y in scenarios):
        raise ToolkitError(f"quantum_years must be 1-6 years between {year} and {year + 50}")
    rows = []
    for d in datasets:
        if not isinstance(d, dict) or not str(d.get("name", "")).strip():
            raise ToolkitError('each dataset must be like {"name": "customer contracts", "secrecy_years": 10, "protected_by": "RSA-2048"}')
        secrecy = d.get("secrecy_years")
        if not isinstance(secrecy, (int, float)) or not 0 <= secrecy <= 100:
            raise ToolkitError(f"secrecy_years for '{d['name']}' must be 0-100")
        prot = str(d.get("protected_by", "") or "unknown").strip()
        safe = any(s in prot.lower() for s in SAFE_PROTECTION)
        secret_until = year + migration_years + secrecy       # data sent on the last day before migration finishes
        per = []
        for q in scenarios:
            exposed = 0.0 if safe else max(0.0, secret_until - q)
            per.append({"quantum_year": q, "exposed": exposed > 0, "years_exposed": round(min(exposed, secrecy), 1)})
        rows.append({"name": str(d["name"]).strip()[:120], "protected_by": prot, "secrecy_years": secrecy,
                     "already_quantum_safe": safe, "must_stay_secret_until": round(secret_until, 1), "scenarios": per,
                     "latest_safe_migration_finish": {str(q): round(q - secrecy, 1) for q in scenarios} if not safe else None})
    rows.sort(key=lambda r: -max(s["years_exposed"] for s in r["scenarios"]))
    at_risk = [r["name"] for r in rows if any(s["exposed"] for s in r["scenarios"])]
    return {"year": year, "migration_years": migration_years, "quantum_year_scenarios": scenarios,
            "datasets": rows, "at_risk": at_risk, "migrate_first": at_risk[:3],
            "method": "Mosca's inequality: data is exposed when (years it must stay secret) + (years to migrate) is "
                      "longer than the years until a quantum computer can break today's key exchange. Traffic recorded "
                      "today can be decrypted later, so the clock started already.",
            "note": "The quantum years are planning scenarios you choose, not predictions. Applies to encryption and "
                    "key exchange; signatures are only at risk once such a computer exists."}


# ---------------------------------------------------------------- 3. size impact

# Bytes on the wire. Post-quantum sizes are from FIPS 203 (ML-KEM), FIPS 204 (ML-DSA) and FIPS 205 (SLH-DSA).
KEX = {  # name: (client share, server share)
    "x25519": (32, 32), "p-256": (65, 65), "p-384": (97, 97),
    "ml-kem-512": (800, 768), "ml-kem-768": (1184, 1088), "ml-kem-1024": (1568, 1568),
    "x25519mlkem768": (1184 + 32, 1088 + 32), "secp256r1mlkem768": (65 + 1184, 65 + 1088),
}
SIG = {  # name: (public key, signature)
    "ed25519": (32, 64), "ecdsa-p256": (65, 64), "ecdsa-p384": (97, 96),
    "rsa-2048": (256, 256), "rsa-3072": (384, 384), "rsa-4096": (512, 512),
    "ml-dsa-44": (1312, 2420), "ml-dsa-65": (1952, 3309), "ml-dsa-87": (2592, 4627),
    "slh-dsa-sha2-128s": (32, 7856), "slh-dsa-sha2-128f": (32, 17088),
}


def _norm(name: str) -> str:
    return re.sub(r"[\s_]+", "-", str(name or "").strip().lower())


def size_impact(kind: str, current: str, target: str, per_day: int = 0, signatures_per_operation: int = 1,
                keys_per_operation: int = 1) -> dict[str, Any]:
    kind = _norm(kind)
    if kind not in ("key-exchange", "signature"):
        raise ToolkitError("kind must be key-exchange or signature")
    table = KEX if kind == "key-exchange" else SIG
    cur, tgt = _norm(current), _norm(target)
    for n in (cur, tgt):
        if n not in table:
            raise ToolkitError(f"unknown {kind} algorithm '{n}'; choose from: " + ", ".join(table))
    if not isinstance(per_day, int) or not 0 <= per_day <= 10**13:
        raise ToolkitError("per_day must be a whole number of operations per day")
    if not 0 <= signatures_per_operation <= 20 or not 0 <= keys_per_operation <= 20:
        raise ToolkitError("signatures_per_operation and keys_per_operation must be 0-20")
    if kind == "key-exchange":
        a, b = sum(table[cur]), sum(table[tgt])
        detail = {"current": {"client_share": table[cur][0], "server_share": table[cur][1]},
                  "target": {"client_share": table[tgt][0], "server_share": table[tgt][1]}}
        if table[tgt][0] > 1200:
            detail["warning"] = ("the client's first message grows past one typical network packet (about 1,200-1,400 "
                                 "bytes); test for middleboxes that drop split ClientHello messages")
    else:
        def per(n):
            return table[n][0] * keys_per_operation + table[n][1] * signatures_per_operation
        a, b = per(cur), per(tgt)
        detail = {"current": {"public_key": table[cur][0], "signature": table[cur][1]},
                  "target": {"public_key": table[tgt][0], "signature": table[tgt][1]},
                  "counted": f"{keys_per_operation} public key(s) + {signatures_per_operation} signature(s) per operation"}
    extra = b - a
    return {"kind": kind, "current": cur, "target": tgt, **detail,
            "bytes_per_operation": {"current": a, "target": b, "added": extra, "times_larger": round(b / a, 1)},
            "per_day": {"operations": per_day, "added_megabytes": round(extra * per_day / 1e6, 2),
                        "added_gigabytes_per_year": round(extra * per_day * 365 / 1e9, 2)} if per_day else None,
            "note": "Raw key, ciphertext and signature sizes; certificates, encodings and protocol framing add a little more."}


# ---------------------------------------------------------------- 4. circuit stats

def circuit_stats(qasm: str) -> dict[str, Any]:
    try:
        c = circuits.parse(qasm)
    except circuits.CircuitError as e:
        raise ToolkitError(str(e)) from None
    n, gates = c["qubits"], c["gates"]
    level, counts, used, pairs = [0] * n, Counter(), set(), Counter()
    for g in gates:
        counts[g[0]] += 1
        qs = [g[1], g[2]] if g[0] == "cx" else [g[1]]
        d = max(level[q] for q in qs) + 1
        for q in qs:
            level[q] = d
            used.add(q)
        if g[0] == "cx":
            pairs[tuple(sorted(qs))] += 1
    two = counts.get("cx", 0)
    return {"qubits": n, "qubits_used": len(used), "idle_qubits": sorted(set(range(n)) - used),
            "source_gates": c["source_gates"], "basis_gates": dict(counts), "basis_gate_total": len(gates),
            "two_qubit_gates": two, "depth": max(level, default=0), "qubit_pairs_coupled": len(pairs),
            "all_to_all_needed": len(pairs) > max(0, n - 1),
            "runs_on_local_simulator": n <= circuits.LOCAL_MAX_QUBITS,
            "openqasm_version": c["version"], "source_sha256": c["source_sha256"],
            "reading": ("Depth and two-qubit gate count drive error on real hardware: fewer is better. Counts are "
                        "after rewriting to Privi's basis (h, rz, rx, cx); a provider's own compiler may differ."),
            "next": "quantum_run_circuit runs it; quantum_backends lists hardware and limits."}


# ---------------------------------------------------------------- 5. supplier score

QUESTIONS: list[dict[str, Any]] = [
    {"id": "inventory", "weight": 15, "q": "Do you keep an inventory of where your products and systems use cryptography (a CBOM or equivalent)?"},
    {"id": "roadmap", "weight": 15, "q": "Do you have a written post-quantum migration plan with dates?"},
    {"id": "owner", "weight": 5, "q": "Is a named person accountable for the migration?"},
    {"id": "tls_hybrid", "weight": 15, "q": "Do your customer-facing services accept hybrid post-quantum key exchange in TLS 1.3 (e.g. X25519MLKEM768)?"},
    {"id": "tls13", "weight": 5, "q": "Do all customer-facing services support TLS 1.3?"},
    {"id": "data_at_rest", "weight": 10, "q": "Is long-lived customer data at rest protected with AES-256 or post-quantum key wrapping?"},
    {"id": "signing", "weight": 10, "q": "Can you sign software or firmware updates with ML-DSA or SLH-DSA (alone or alongside today's signature)?"},
    {"id": "agility", "weight": 10, "q": "Can you change cryptographic algorithms through configuration, without redesigning the product?"},
    {"id": "subsuppliers", "weight": 10, "q": "Have you asked your own critical suppliers for their post-quantum plans?"},
    {"id": "fips", "weight": 5, "q": "Do you use (or have a date to use) validated implementations of FIPS 203/204/205?"},
]
ANSWER_VALUE = {"yes": 1.0, "partial": 0.5, "planned": 0.25, "no": 0.0}


def supplier_questions() -> dict[str, Any]:
    return {"questions": [{"id": q["id"], "question": q["q"], "weight": q["weight"]} for q in QUESTIONS],
            "answers": "for each id: yes | partial | planned | no",
            "how": "Send these to a supplier, then call pqc_supplier_score with their answers."}


def supplier_score(supplier: str, answers: dict[str, str], evidence: dict[str, str] | None = None) -> dict[str, Any]:
    supplier = str(supplier or "").strip()
    if not 2 <= len(supplier) <= 160:
        raise ToolkitError("supplier must be the company's name (2-160 characters)")
    if not isinstance(answers, dict):
        raise ToolkitError("answers must map each question id to yes, partial, planned or no")
    ids = {q["id"] for q in QUESTIONS}
    if extra := sorted(set(answers) - ids):
        raise ToolkitError(f"unknown question id(s): {extra}; call pqc_supplier_score with no answers to see the questions")
    evidence = evidence or {}
    for k, v in evidence.items():
        if k not in ids or not re.fullmatch(r"[0-9a-f]{64}", str(v).lower()):
            raise ToolkitError("evidence must map question ids to SHA-256 fingerprints (64 hex characters)")
    total, rows, gaps = 0.0, [], []
    for q in QUESTIONS:
        a = str(answers.get(q["id"], "") or "unanswered").strip().lower()
        if a != "unanswered" and a not in ANSWER_VALUE:
            raise ToolkitError(f"answer for '{q['id']}' must be yes, partial, planned or no")
        pts = q["weight"] * ANSWER_VALUE.get(a, 0.0)
        total += pts
        rows.append({"id": q["id"], "answer": a, "points": pts, "of": q["weight"],
                     "evidence_sha256": str(evidence[q["id"]]).lower() if q["id"] in evidence else None})
        if a != "yes":
            gaps.append({"id": q["id"], "answer": a, "ask_for": q["q"], "points_missing": q["weight"] - pts})
    score = round(total)
    grade = "A" if score >= 85 else "B" if score >= 70 else "C" if score >= 50 else "D" if score >= 30 else "F"
    gaps.sort(key=lambda g: -g["points_missing"])
    return {"supplier": supplier, "score": score, "grade": grade, "answered": sum(1 for r in rows if r["answer"] != "unanswered"),
            "of_questions": len(QUESTIONS), "answers": rows, "gaps": gaps,
            "basis": "self-reported answers; evidence is recorded by fingerprint only and is not inspected by Privi"}


# ---------------------------------------------------------------- MCP registration

def _result(data: dict[str, Any], is_error: bool = False) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(data))], structured_content=data, is_error=is_error)


def register(mcp, attestor, public_url: str) -> None:

    def guard(fn, *a, **kw) -> CallToolResult:
        try:
            return _result(fn(*a, **kw))
        except ToolkitError as e:
            return _result({"error": str(e)}, is_error=True)

    @mcp.tool(title="Check certificates for quantum risk", annotations=READ)
    def pqc_certificate_check(
        pem: Annotated[str, Field(description="One or more X.509 certificates in PEM form (a full chain is fine)")],
    ) -> CallToolResult:
        """Read certificates and report, for each one, the key algorithm, whether a quantum computer could break
        it, when it expires, and whether it outlives the federal post-quantum dates. Nothing is contacted; the
        certificates are not stored."""
        return guard(certificate_check, pem)

    @mcp.tool(title="Harvest-now-decrypt-later risk", annotations=READ)
    def pqc_harvest_risk(
        datasets: Annotated[list[dict[str, Any]], Field(description=(
            'Kinds of data you send or store, each {"name": "patient records", "secrecy_years": 25, '
            '"protected_by": "RSA-2048"}. protected_by may be e.g. RSA-2048, ECDH P-256, X25519, ML-KEM-768, AES-256'))],
        migration_years: Annotated[float, Field(description="Years until your move to post-quantum encryption is finished", ge=0, le=30)],
        quantum_years: Annotated[list[int] | None, Field(description="Planning scenarios for when today's key exchange can be broken. Default 2030, 2035, 2040")] = None,
    ) -> CallToolResult:
        """Which of your data is exposed to "record now, decrypt later" attacks, under each planning scenario, and
        what to migrate first. Uses Mosca's inequality. Nothing is stored."""
        return guard(harvest_risk, datasets, migration_years, quantum_years)

    @mcp.tool(title="Post-quantum size impact", annotations=READ)
    def pqc_size_impact(
        kind: Annotated[str, Field(description="key-exchange or signature")],
        current: Annotated[str, Field(description="Today's algorithm. Key exchange: " + ", ".join(KEX) + ". Signature: " + ", ".join(SIG))],
        target: Annotated[str, Field(description="The algorithm you plan to move to (same lists)")],
        per_day: Annotated[int, Field(description="Handshakes or signed operations per day", ge=0)] = 0,
        signatures_per_operation: Annotated[int, Field(description="Signatures sent per operation (a TLS handshake with a two-certificate chain sends about 3)", ge=0, le=20)] = 1,
        keys_per_operation: Annotated[int, Field(description="Public keys sent per operation", ge=0, le=20)] = 1,
    ) -> CallToolResult:
        """How many more bytes each handshake or signature costs after switching to a post-quantum algorithm, and
        the added traffic per day and year. Sizes come from FIPS 203, 204 and 205."""
        return guard(size_impact, kind, current, target, per_day, signatures_per_operation, keys_per_operation)

    @mcp.tool(title="Quantum circuit stats", annotations=READ)
    def quantum_circuit_stats(
        qasm: Annotated[str, Field(description="The circuit as OpenQASM 2.0 or 3.0 text (Qiskit: qasm2.dumps(circuit))")],
    ) -> CallToolResult:
        """Qubits, gate counts, two-qubit gates and depth of a circuit after rewriting to basic gates, so you know
        what you are about to run before paying for hardware. The circuit is not run or stored."""
        return guard(circuit_stats, qasm)

    @mcp.tool(title="Score a supplier's post-quantum readiness", annotations=WRITE)
    def pqc_supplier_score(
        supplier: Annotated[str | None, Field(description="Supplier's company name. Omit (with answers) to get the questionnaire")] = None,
        answers: Annotated[dict[str, str] | None, Field(description="Question id -> yes | partial | planned | no")] = None,
        evidence: Annotated[dict[str, str] | None, Field(description="Optional: question id -> SHA-256 fingerprint of the supplier's evidence document")] = None,
    ) -> CallToolResult:
        """Send a supplier Privi's ten post-quantum questions, then score the answers 0-100 with a letter grade and
        a ranked list of gaps. The scorecard is signed (Ed25519 + ML-DSA-87) so the supplier can show it to other
        customers. Call with no arguments to get the questions."""
        if not supplier and not answers:
            return _result(supplier_questions())
        try:
            card = supplier_score(supplier or "", answers or {}, evidence)
        except ToolkitError as e:
            return _result({"error": str(e)}, is_error=True)
        att = attestor.issue("pqc_supplier_scorecard", card)
        return _result({**card, "scorecard_id": att["id"], "body_sha256": att["body_sha256"],
                        "signatures": att["signatures"], "attestation_url": f"{public_url}/attestations/{att['id']}",
                        "public_keys_url": f"{public_url}/keys"})
