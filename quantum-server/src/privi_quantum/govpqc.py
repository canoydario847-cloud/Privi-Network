# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Quantum - https://priviflow.us - dariocanoy@priviflow.us
"""Privi Quantum for government: post-quantum readiness packages.

Turns a code/config scan and/or a list of cryptographic assets into the evidence a
U.S. federal agency (or a contractor selling to one) needs right now:

* a prioritized migration list with the federal deadline that applies to each asset,
* the nine elements OMB M-26-15 asks a PQC migration plan to cover, marked as
  "evidence in this package" or "gap: agency must supply",
* a machine-readable Cryptographic Bill of Materials (CycloneDX 1.6, which defines
  cryptographic-asset components), and
* for contractors, the EO 14409 FAR items that are coming (proposed rules).

Federal sources (checked October 2026; confirm against the official texts):
  EO 14409 (June 22, 2026); OMB M-26-15 "Execution of the Migration to Post-Quantum
  Cryptography" (June 24, 2026); NIST IR 8547 initial public draft (Nov 2024);
  NSA CNSA 2.0 (2022, FAQ v2.1); FIPS 203/204/205; NIST SP 800-208.
This module is pure Python (stdlib only) so it can run anywhere, including offline.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import date, datetime, timezone
from typing import Any

# ---------------------------------------------------------------- federal timeline

KEY_ESTABLISHMENT_DEADLINE = "2030-12-31"   # EO 14409 / M-26-15 Phase 3 (HVAs, high-impact, highly sensitive)
SIGNATURE_DEADLINE = "2031-12-31"           # EO 14409 / M-26-15 Phase 4
REMAINING_SYSTEMS_YEAR = "2035"             # M-26-15 Phase 5; NIST IR 8547 draft disallows after 2035
TLS13_DEADLINE = "2030-01-02"               # M-26-15: TLS 1.3 (or successor) no later than this date
PLAN_DUE = "2026-10-22"                     # M-26-15: plan due 120 days after the memo

TIMELINE: list[dict[str, str]] = [
    {"date": "2026-06-22", "source": "EO 14409", "item": "Executive order accelerating the federal move to post-quantum cryptography signed."},
    {"date": "2026-06-24", "source": "OMB M-26-15", "item": "Execution of the Migration to Post-Quantum Cryptography issued (excludes national security systems)."},
    {"date": PLAN_DUE, "source": "OMB M-26-15", "item": "Agency PQC Migration Plan due to OMB and ONCD (PQC@omb.eop.gov); a living document that matures with the inventory."},
    {"date": "2026-12-19", "source": "EO 14409", "item": "FAR Council proposed rule due: covered contractors to comply with NIST FIPS, including PQC algorithms, by Dec 31, 2030 (proposed)."},
    {"date": "2027-03-19", "source": "EO 14409", "item": "CISA/NIST guidance on minimum CBOM elements due; FAR proposed rule on contractor vulnerability disclosure covering cryptographic weaknesses due."},
    {"date": "2027-12-31", "source": "M-26-15 Phase 1", "item": "Phase 1 (2026-2027): strategy, planning, discovery; inventory HVAs and high-impact systems."},
    {"date": "2028-12-31", "source": "M-26-15 Phase 2", "item": "Phase 2 (2027-2028): pilots and early migration."},
    {"date": TLS13_DEADLINE, "source": "OMB M-26-15", "item": "Support TLS 1.3 or a successor version, no later than this date."},
    {"date": KEY_ESTABLISHMENT_DEADLINE, "source": "EO 14409 / M-26-15 Phase 3", "item": "Key establishment on HVAs, high-impact and highly sensitive systems migrated to PQC (Phase 3, 2028-2030)."},
    {"date": SIGNATURE_DEADLINE, "source": "EO 14409 / M-26-15 Phase 4", "item": "Digital signatures on HVAs, high-impact and highly sensitive systems migrated to PQC (Phase 4, 2031)."},
    {"date": "2030-12-31", "source": "NIST IR 8547 (draft)", "item": "Quantum-vulnerable public-key algorithms at 112-bit security (RSA-2048, P-256 and similar) deprecated after 2030 (draft)."},
    {"date": "2035-12-31", "source": "NIST IR 8547 (draft) / M-26-15 Phase 5", "item": "Quantum-vulnerable public-key algorithms disallowed after 2035 (draft); remaining systems migrated (Phase 5)."},
]

SOURCES = [
    {"name": "OMB M-26-15", "url": "https://www.whitehouse.gov/wp-content/uploads/2026/06/M-26-15-Execution-of-the-Migration-to-Post-Quantum-Cryptography.pdf"},
    {"name": "Executive Order 14409 (June 22, 2026)", "url": "https://www.federalregister.gov/"},
    {"name": "NIST IR 8547 initial public draft", "url": "https://csrc.nist.gov/pubs/ir/8547/ipd"},
    {"name": "NSA CNSA 2.0", "url": "https://media.defense.gov/2022/Sep/07/2003071834/-1/-1/0/CSA_CNSA_2.0_ALGORITHMS_.PDF"},
    {"name": "FIPS 203 / 204 / 205", "url": "https://csrc.nist.gov/projects/post-quantum-cryptography"},
]

# NSA CNSA 2.0: (support & prefer by, exclusively use by) per product category (national security systems / their vendors)
CNSA2 = {
    "software_signing": ("2025", "2030", "Software and firmware signing"),
    "web": ("2025", "2033", "Web browsers, servers and cloud services"),
    "networking": ("2026", "2030", "Traditional networking equipment (VPNs, routers)"),
    "os": ("2027", "2033", "Operating systems"),
    "niche": ("2030", "2033", "Niche equipment (constrained devices, large PKI)"),
    "custom": ("2033", "2033", "Custom applications and legacy equipment (update or replace)"),
}

# ---------------------------------------------------------------- algorithm classification

_PQC = [
    (r"ML[-_]?KEM[-_]?1024|Kyber[-_]?1024", "ML-KEM-1024", "kem", 5, "FIPS 203"),
    (r"ML[-_]?KEM[-_]?768|Kyber[-_]?768|mlkem768", "ML-KEM-768", "kem", 3, "FIPS 203"),
    (r"ML[-_]?KEM[-_]?512|Kyber[-_]?512", "ML-KEM-512", "kem", 1, "FIPS 203"),
    (r"ML[-_]?KEM|Kyber", "ML-KEM", "kem", 3, "FIPS 203"),
    (r"ML[-_]?DSA[-_]?87|Dilithium[-_]?5", "ML-DSA-87", "signature", 5, "FIPS 204"),
    (r"ML[-_]?DSA[-_]?65|Dilithium[-_]?3", "ML-DSA-65", "signature", 3, "FIPS 204"),
    (r"ML[-_]?DSA[-_]?44|Dilithium[-_]?2", "ML-DSA-44", "signature", 2, "FIPS 204"),
    (r"ML[-_]?DSA|Dilithium", "ML-DSA", "signature", 3, "FIPS 204"),
    (r"SLH[-_]?DSA|SPHINCS", "SLH-DSA", "signature", 1, "FIPS 205"),
    (r"\bLMS\b|\bXMSS\b|\bHSS\b", "LMS/XMSS", "signature", 5, "NIST SP 800-208"),
]
_L, _R = r"(?<![A-Za-z])", r"(?![a-z])"   # boundaries that also split on "_" and "-" (TLS_ECDHE_RSA_WITH_...)
_CLASSICAL = [
    (_L + r"ECDHE?" + _R + r"|X25519|X448", "ECDH", "key-agree"),
    (_L + r"RSA" + _R + r"|ssh-rsa|\bRS(256|384|512)\b|\bPS(256|384|512)\b", "RSA", "pke"),
    (_L + r"ECDSA" + _R + r"|\bES(256|384|512)\b|ecdsa-sha2", "ECDSA", "signature"),
    (r"Ed25519|Ed448|EdDSA", "EdDSA", "signature"),
    (_L + r"DHE?" + _R + r"|Diffie", "Diffie-Hellman", "key-agree"), (_L + r"DSA" + _R, "DSA", "signature"),
    (_L + r"P-?(256|384|521)" + _R + r"|secp\d+|prime256v1", "Elliptic curve", "pke"),
]
_SYMMETRIC = [(r"AES[-_ ]?256|AES256", "AES-256", "ae", 5), (r"AES[-_ ]?192", "AES-192", "ae", 3),
              (r"AES[-_ ]?128|AES128", "AES-128", "ae", 1), (r"ChaCha20", "ChaCha20-Poly1305", "ae", 5),
              (r"SHA[-_ ]?512|SHA3[-_ ]?512", "SHA-512", "hash", 5), (r"SHA[-_ ]?384|SHA3[-_ ]?384", "SHA-384", "hash", 5),
              (r"SHA[-_ ]?256|SHA3[-_ ]?256", "SHA-256", "hash", 2), (r"\bAES\b", "AES", "ae", 1),
              (r"HMAC", "HMAC", "mac", 2)]
_BROKEN = [(_L + r"MD5" + _R, "MD5"), (_L + r"SHA[-_ ]?1(?![0-9])", "SHA-1"), (_L + r"(3DES|TripleDES|DES-EDE3|DES)" + _R, "3DES/DES"), (_L + r"RC4" + _R, "RC4")]

PROFILES = ("agency", "contractor", "nss_vendor", "company")
USAGES = ("key_establishment", "signature", "encryption", "tls", "ssh", "vpn", "code_signing", "certificate", "hash", "other")
IMPACTS = ("high", "moderate", "low", "unknown")


def classify(algorithm: str) -> dict[str, Any]:
    """Classify an algorithm string (e.g. 'RSA-2048', 'X25519+ML-KEM-768', 'AES-256-GCM')."""
    a = (algorithm or "").strip()
    pq = [(n, p, lvl, std) for rx, n, p, lvl, std in _PQC if re.search(rx, a, re.I)]
    pq = pq[:1]
    rest = a
    for rx, *_ in _PQC:  # so "ML-DSA" is not also read as classical "DSA"
        rest = re.sub(rx, " ", rest, flags=re.I)
    cl = [(n, p) for rx, n, p in _CLASSICAL if re.search(rx, rest, re.I)][:1]
    if any(re.search(rx, a, re.I) for rx, _ in _BROKEN):
        name = next(n for rx, n in _BROKEN if re.search(rx, a, re.I))
        return {"algorithm": a, "class": "broken", "family": name, "primitive": "hash" if "SHA" in name or "MD5" in name else "ae",
                "quantum_vulnerable": True, "nist_quantum_security_level": 0,
                "note": "Already broken or deprecated classically; replace now regardless of quantum timelines"}
    if pq and cl:
        n, p, lvl, std = pq[0]
        return {"algorithm": a, "class": "hybrid", "family": f"{cl[0][0]} + {n}", "primitive": p, "standard": std,
                "quantum_vulnerable": False, "nist_quantum_security_level": lvl,
                "note": "Hybrid classical + post-quantum: acceptable during transition"}
    if pq:
        n, p, lvl, std = pq[0]
        return {"algorithm": a, "class": "post_quantum", "family": n, "primitive": p, "standard": std,
                "quantum_vulnerable": False, "nist_quantum_security_level": lvl}
    if cl:
        return {"algorithm": a, "class": "quantum_vulnerable", "family": cl[0][0], "primitive": cl[0][1],
                "quantum_vulnerable": True, "nist_quantum_security_level": 0,
                "note": "Public-key algorithm broken by Shor's algorithm on a cryptographically relevant quantum computer"}
    sym = next(((n, p, lvl) for rx, n, p, lvl in _SYMMETRIC if re.search(rx, a, re.I)), None)
    if sym:
        weak = sym[0] in ("AES-128", "AES")
        return {"algorithm": a, "class": "symmetric_weakened" if weak else "symmetric_ok", "family": sym[0], "primitive": sym[1],
                "quantum_vulnerable": False, "nist_quantum_security_level": sym[2],
                "note": "Grover's algorithm halves effective strength; use AES-256 for long-lived data" if weak else
                        "Symmetric/hash at a strength that remains acceptable (CNSA 2.0 uses AES-256, SHA-384/512)"}
    return {"algorithm": a, "class": "unknown", "family": a or "unspecified", "primitive": "unknown",
            "quantum_vulnerable": None, "nist_quantum_security_level": None,
            "note": "Not recognized: confirm the algorithm with the system owner"}


def tls_version(protocol: str) -> float | None:
    m = re.search(r"TLS\s*v?(1\.[0-3])", protocol or "", re.I)
    if m:
        return float(m.group(1))
    if re.search(r"\bSSL", protocol or "", re.I):
        return 0.0
    return None


def _replacement(c: dict, usage: str, profile: str) -> str:
    nss = profile == "nss_vendor"
    if c["class"] == "broken":
        return {"hash": "SHA-384 (or SHA-256 outside NSS)"}.get(c["primitive"], "AES-256-GCM")
    if c["class"] == "symmetric_weakened":
        return "AES-256-GCM"
    if usage in ("code_signing",):
        return "LMS/XMSS (SP 800-208) or ML-DSA-87" if nss else "ML-DSA-65 or LMS/XMSS (SP 800-208); hybrid with the current signature during transition"
    if c.get("primitive") == "signature" or usage in ("signature", "certificate"):
        return "ML-DSA-87 (FIPS 204)" if nss else "ML-DSA-65 (FIPS 204), hybrid with ECDSA/EdDSA during transition"
    if usage in ("tls", "ssh", "vpn", "key_establishment", "encryption") or c.get("primitive") in ("key-agree", "pke"):
        return "ML-KEM-1024 (FIPS 203)" if nss else "Hybrid X25519MLKEM768 (FIPS 203) key exchange"
    return "Confirm usage, then ML-KEM (key establishment) or ML-DSA (signatures)"


def assess_asset(asset: dict, profile: str = "agency", today: date | None = None) -> dict[str, Any]:
    """Classify one cryptographic asset and attach the deadline, priority and action that apply to it."""
    today = today or datetime.now(timezone.utc).date()
    alg = str(asset.get("algorithm") or "")
    usage = str(asset.get("usage") or "other").lower()
    usage = usage if usage in USAGES else "other"
    impact = str(asset.get("impact") or "unknown").lower()
    impact = impact if impact in IMPACTS else "unknown"
    hva = bool(asset.get("hva"))
    long_lived = bool(asset.get("sensitive_past_2030") or asset.get("long_term_sensitive"))
    c = classify(alg)
    priority_system = hva or impact == "high" or long_lived

    tls = tls_version(str(asset.get("protocol") or ""))
    findings: list[str] = []
    deadlines: list[dict[str, str]] = []
    if tls is not None and tls < 1.3:
        findings.append(f"Protocol is {'SSL' if tls == 0 else 'TLS ' + str(tls)}; M-26-15 requires TLS 1.3 or a successor")
        deadlines.append({"date": TLS13_DEADLINE, "rule": "OMB M-26-15: TLS 1.3 or successor"})

    if c["class"] == "broken":
        deadlines.append({"date": today.isoformat(), "rule": "Already broken or deprecated classically: replace now"})
    kind = "signature" if (c.get("primitive") == "signature" or usage in ("signature", "certificate", "code_signing")) else "key_establishment"
    if c["class"] in ("quantum_vulnerable", "broken"):
        if profile == "nss_vendor":
            cat = str(asset.get("cnsa_category") or ("software_signing" if usage == "code_signing" else
                                                     "web" if usage == "tls" else "networking" if usage == "vpn" else "custom"))
            pref, excl, label = CNSA2.get(cat, CNSA2["custom"])
            deadlines.append({"date": f"{excl}-12-31", "rule": f"NSA CNSA 2.0, {label}: support/prefer by {pref}, exclusively by {excl}"})
        elif profile == "company":
            deadlines.append({"date": "2030-12-31" if priority_system else "2035-12-31",
                              "rule": "NIST IR 8547 (draft): quantum-vulnerable public-key algorithms deprecated after 2030 "
                                      "(112-bit) and disallowed after 2035" if priority_system else
                                      "NIST IR 8547 (draft): quantum-vulnerable public-key algorithms disallowed after 2035"})
        elif priority_system:
            if kind == "signature":
                deadlines.append({"date": SIGNATURE_DEADLINE, "rule": "EO 14409 / M-26-15 Phase 4: PQC digital signatures on HVAs and high-impact systems"})
            else:
                deadlines.append({"date": KEY_ESTABLISHMENT_DEADLINE, "rule": "EO 14409 / M-26-15 Phase 3: PQC key establishment on HVAs and high-impact systems"})
        else:
            deadlines.append({"date": "2035-12-31", "rule": "M-26-15 Phase 5 (remaining systems); NIST IR 8547 draft disallows after 2035"})
        if c["class"] == "quantum_vulnerable" and profile not in ("nss_vendor", "company"):
            deadlines.append({"date": "2030-12-31", "rule": "NIST IR 8547 (draft): 112-bit quantum-vulnerable algorithms deprecated after 2030"})
        if profile == "contractor":
            deadlines.append({"date": "2030-12-31", "rule": "EO 14409 FAR rule (proposed): covered contractors comply with NIST FIPS incl. PQC"})
        findings.append(c.get("note", "Quantum-vulnerable"))
    elif c["class"] == "symmetric_weakened":
        findings.append(c["note"])
    elif c["class"] == "unknown":
        findings.append(c["note"])

    deadlines.sort(key=lambda d: d["date"])
    due = deadlines[0]["date"] if deadlines else None
    days_left = (date.fromisoformat(due) - today).days if due else None
    status = str(asset.get("status") or "not_started")

    if c["class"] in ("post_quantum", "hybrid", "symmetric_ok") and not (tls is not None and tls < 1.3):
        priority, action = "P4 done", "No migration needed for this asset; keep it in the CBOM and re-check on change"
    elif c["class"] == "broken":
        priority, action = "P1", f"Replace now with {_replacement(c, usage, profile)}"
    elif c["class"] == "quantum_vulnerable" and priority_system:
        priority, action = "P1", f"Migrate to {_replacement(c, usage, profile)}"
    elif c["class"] == "quantum_vulnerable" or (tls is not None and tls < 1.3):
        priority, action = "P2", f"Migrate to {_replacement(c, usage, profile)}" if c["class"] == "quantum_vulnerable" else "Enable TLS 1.3 with hybrid X25519MLKEM768"
    elif c["class"] == "symmetric_weakened":
        priority, action = "P3", "Move long-lived data to AES-256"
    else:
        priority, action = "P3", "Identify the algorithm with the system owner"

    if tls is not None and tls < 1.3 and "TLS 1.3" not in action:
        action += "; enable TLS 1.3 (hybrid X25519MLKEM768) by Jan 2, 2030"
    return {
        "system": str(asset.get("system") or "unspecified")[:120],
        "asset": str(asset.get("asset") or alg or "unspecified")[:160],
        "algorithm": alg[:120], "usage": usage, "protocol": str(asset.get("protocol") or "")[:60] or None,
        "impact": impact, "hva": hva, "sensitive_past_2030": long_lived, "status": status,
        "owner": str(asset.get("owner") or "")[:120] or None, "vendor": str(asset.get("vendor") or "")[:120] or None,
        "classification": c, "priority": priority, "action": action,
        "deadline": due, "days_left": days_left, "deadlines": deadlines, "findings": findings,
    }


def assets_from_scan(scan: dict, system: str, impact: str = "unknown", hva: bool = False) -> list[dict]:
    """Turn scanner findings into CBOM assets (one per rule per file)."""
    rule_alg = {"rsa": "RSA", "rsa-pem": "RSA private key", "ecdsa": "ECDSA", "curve": "ECDSA P-256", "ecdh": "ECDH X25519",
                "eddsa": "Ed25519", "dh": "Diffie-Hellman", "dsa": "DSA", "ssh": "ssh-rsa", "jwt-asym": "RS256 (RSA)",
                "aes128": "AES-128", "sha1": "SHA-1", "md5": "MD5", "3des": "3DES", "pqc-present": "ML-KEM/ML-DSA"}
    rule_usage = {"ssh": "ssh", "jwt-asym": "signature", "ecdsa": "signature", "eddsa": "signature", "dsa": "signature",
                  "ecdh": "key_establishment", "dh": "key_establishment", "rsa": "key_establishment", "rsa-pem": "key_establishment",
                  "curve": "signature", "sha1": "hash", "md5": "hash", "aes128": "encryption", "3des": "encryption",
                  "pqc-present": "key_establishment"}
    seen, out = set(), []
    for f in scan.get("findings", []):
        key = (f["rule"], f["path"])
        if key in seen:
            continue
        seen.add(key)
        out.append({"system": system, "asset": f"{f['path']}:{f['line']}", "algorithm": rule_alg.get(f["rule"], f["rule"]),
                    "usage": rule_usage.get(f["rule"], "other"), "impact": impact, "hva": hva,
                    "evidence": f["snippet"], "source": "Privi Quantum code scan"})
    return out


# ---------------------------------------------------------------- M-26-15 plan elements

def plan_elements(assessed: list[dict], org: dict, profile: str) -> list[dict[str, Any]]:
    vulnerable = [a for a in assessed if a["priority"] in ("P1", "P2")]
    has_tls = any(a["usage"] == "tls" or a["protocol"] for a in assessed)
    has_vendor = any(a["vendor"] for a in assessed)
    lead = (org.get("pqc_lead") or "").strip()

    def el(n, name, status, evidence, need):
        return {"element": n, "name": name, "status": status, "evidence_in_package": evidence, "agency_must_supply": need}

    return [
        el(1, "Governance", "evidence" if lead else "gap",
           f"PQC Migration Lead: {lead}" if lead else None,
           None if lead else "Name the PQC Migration Lead (EO 14409 required this within 30 days) and the CIO/CISO/program/procurement structure"),
        el(2, "Cryptographic inventory", "evidence" if assessed else "gap",
           f"{len(assessed)} cryptographic assets in a machine-readable CycloneDX 1.6 CBOM; methodology: automated code/config scan (Privi Quantum) plus owner-supplied asset list" if assessed else None,
           "Extend the inventory to SaaS, cloud, network and on-prem systems; keep it continuously updated (re-run this package on change)"),
        el(3, "Risk-based prioritization", "evidence" if assessed else "gap",
           f"{sum(a['priority']=='P1' for a in assessed)} P1 (HVA / high-impact / data sensitive past 2030), "
           f"{sum(a['priority']=='P2' for a in assessed)} P2, {sum(a['priority']=='P3' for a in assessed)} P3" if assessed else None,
           "Confirm FIPS 199 impact, HVA designation and data lifetime for each system" if assessed else "Provide systems with impact level"),
        el(4, "Phased milestones", "evidence" if vulnerable else "partial",
           "Per-asset deadlines mapped to M-26-15 Phases 3-5 and EO 14409 dates (see milestones)" if vulnerable else None,
           "Commit internal dates for Phase 1 discovery and Phase 2 pilots"),
        el(5, "TLS 1.3 milestones", "evidence" if has_tls else "gap",
           "TLS/protocol versions captured per asset; anything below TLS 1.3 is flagged for Jan 2, 2030" if has_tls else None,
           None if has_tls else "Record TLS versions for externally and internally facing services"),
        el(6, "Crypto-agility architecture", "partial",
           "Hybrid replacements recommended per asset so algorithms can be swapped without downtime",
           "Describe replaceable HSMs, KMS and libraries; confirm vendors can switch algorithms by configuration"),
        el(7, "Vendor and supply chain", "partial" if has_vendor else "gap",
           "Vendors recorded per asset" if has_vendor else None,
           "Add PQC-readiness language to procurements; collect vendor CBOMs" + (" (contractor: this package is your CBOM evidence)" if profile == "contractor" else "")),
        el(8, "Resource estimates", "gap", None, "Estimate funding and staff for P1/P2 migrations within IT modernization budgets"),
        el(9, "Transition risk management", "partial",
           "Hybrid (classical + PQC) recommended during transition; broken algorithms flagged for immediate replacement",
           "Define acceptable risk per phase and monitoring for hybrid environments"),
    ]


# ---------------------------------------------------------------- CycloneDX 1.6 CBOM

_PRIMITIVE_CDX = {"pke": "pke", "key-agree": "key-agree", "signature": "signature", "kem": "kem", "ae": "ae",
                  "hash": "hash", "mac": "mac", "unknown": "unknown"}


def cbom(assessed: list[dict], org_name: str, serial: str | None = None, generated_at: str | None = None) -> dict[str, Any]:
    comps = []
    for i, a in enumerate(assessed):
        c = a["classification"]
        comp = {
            "type": "cryptographic-asset", "bom-ref": f"crypto-{i + 1}",
            "name": c.get("family") or a["algorithm"] or "unknown",
            "description": f"{a['system']}: {a['asset']}",
            "cryptoProperties": {
                "assetType": "algorithm",
                "algorithmProperties": {"primitive": _PRIMITIVE_CDX.get(c.get("primitive", "unknown"), "other"),
                                        "cryptoFunctions": ["keygen", "encapsulate", "decapsulate"] if c.get("primitive") == "kem"
                                        else ["sign", "verify"] if c.get("primitive") == "signature" else ["other"],
                                        **({"nistQuantumSecurityLevel": c["nist_quantum_security_level"]}
                                           if c.get("nist_quantum_security_level") is not None else {})},
            },
            "properties": [{"name": "privi:usage", "value": a["usage"]}, {"name": "privi:priority", "value": a["priority"]},
                           {"name": "privi:class", "value": c["class"]}, {"name": "privi:impact", "value": a["impact"]},
                           {"name": "privi:hva", "value": str(a["hva"]).lower()},
                           *([{"name": "privi:deadline", "value": a["deadline"]}] if a["deadline"] else []),
                           *([{"name": "privi:protocol", "value": a["protocol"]}] if a["protocol"] else [])],
        }
        comps.append(comp)
    return {"bomFormat": "CycloneDX", "specVersion": "1.6", "serialNumber": serial or f"urn:uuid:{uuid.uuid4()}", "version": 1,
            "metadata": {"timestamp": generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
                         "tools": {"components": [{"type": "application", "name": "Privi Quantum", "publisher": "Privi World Co"}]},
                         "component": {"type": "application", "name": org_name or "Organization"}},
            "components": comps}


# ---------------------------------------------------------------- package

def build_package(org: dict, assets: list[dict], profile: str = "agency", scan: dict | None = None,
                  today: date | None = None) -> dict[str, Any]:
    profile = profile if profile in PROFILES else "agency"
    today = today or datetime.now(timezone.utc).date()
    assessed = [assess_asset(a, profile, today) for a in assets[:1000]]
    order = {"P1": 0, "P2": 1, "P3": 2, "P4 done": 3}
    assessed.sort(key=lambda a: (order.get(a["priority"], 9), a["deadline"] or "9999", a["system"]))
    counts = {p: sum(a["priority"] == p for a in assessed) for p in order}
    total = len(assessed)
    ready = counts["P4 done"]
    score = round(100 * ready / total) if total else None
    next_due = min((a["deadline"] for a in assessed if a["deadline"] and a["priority"] != "P4 done"), default=None)
    org_name = str(org.get("name") or "Organization")[:160]
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    bom = cbom(assessed, org_name, generated_at=generated_at)
    milestones = [t for t in TIMELINE if t["date"] >= today.isoformat() and (profile != "company" or "NIST" in t["source"])] \
        if profile != "nss_vendor" else \
        [{"date": f"{v[1]}-12-31", "source": "NSA CNSA 2.0", "item": f"{v[2]}: exclusively CNSA 2.0 (support and prefer by {v[0]})"}
         for v in CNSA2.values()]
    pkg: dict[str, Any] = {
        "package": "Privi Quantum post-quantum readiness package",
        "profile": profile,
        "organization": {"name": org_name, "pqc_lead": (org.get("pqc_lead") or None),
                         "agency_or_company": org.get("agency") or None},
        "generated_at": generated_at,
        "summary": {"assets": total, "by_priority": counts, "pqc_ready_percent": score,
                    "quantum_vulnerable": sum(1 for a in assessed if a["classification"]["class"] in ("quantum_vulnerable", "broken")),
                    "next_deadline": next_due,
                    "files_scanned": (scan or {}).get("files_scanned"), "code_scan_score": (scan or {}).get("readiness_score")},
        "assets": assessed,
        "plan_elements": plan_elements(assessed, org, profile) if profile == "agency" else None,
        "milestones": sorted(milestones, key=lambda m: m["date"]),
        "cbom": bom,
        "cbom_sha256": hashlib.sha256(json.dumps(bom, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "sources": SOURCES,
        "caveats": ["Deadlines follow EO 14409, OMB M-26-15, the NIST IR 8547 initial public draft and NSA CNSA 2.0 as of "
                    "October 2026; confirm against the official texts.",
                    "Code scanning is heuristic: it shows where to look, not proof of absence.",
                    "M-26-15 does not apply to national security systems (use profile nss_vendor for CNSA 2.0)." if profile != "company" else
                    "Profile company: deadlines follow NIST IR 8547 (draft); federal agency dates do not bind private companies "
                    "but customers, insurers and regulators increasingly ask for the same evidence."],
    }
    if profile == "contractor":
        pkg["contractor_readiness"] = [
            {"item": "FIPS-validated cryptography including PQC algorithms by Dec 31, 2030", "source": "EO 14409 FAR rule (proposed rule due Dec 19, 2026)",
             "status": "on_track" if counts["P1"] + counts["P2"] == 0 else "action_needed"},
            {"item": "Vulnerability disclosure program covering cryptographic weaknesses", "source": "EO 14409 FAR rule (proposed rule due Mar 19, 2027)",
             "status": "unknown", "evidence_needed": "Link to your VDP and confirm it covers cryptographic vulnerabilities"},
            {"item": "Machine-readable CBOM for the products you sell to agencies", "source": "M-26-15 (agencies collect vendor CBOMs); CISA/NIST minimum elements due Mar 19, 2027",
             "status": "evidence", "evidence": "CycloneDX 1.6 CBOM attached to this package"},
        ]
    return pkg


def deadlines_reference() -> dict[str, Any]:
    return {"timeline": TIMELINE, "cnsa_2_0": [{"category": v[2], "support_and_prefer_by": v[0], "exclusively_by": v[1]} for v in CNSA2.values()],
            "algorithms": {"key_establishment": "ML-KEM (FIPS 203); CNSA 2.0: ML-KEM-1024",
                           "signatures": "ML-DSA (FIPS 204), SLH-DSA (FIPS 205); CNSA 2.0: ML-DSA-87; firmware: LMS/XMSS (SP 800-208)",
                           "symmetric": "AES-256; hashes SHA-384/SHA-512"},
            "sources": SOURCES,
            "caveat": "As of October 2026; NIST IR 8547 is still a draft. Confirm against the official texts."}
