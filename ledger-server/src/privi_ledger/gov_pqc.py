"""Privi Quantum-Ready: post-quantum cryptography migration for federal systems.

Context (2026): EO 14409 (June 22, 2026) moves federal key establishment to
post-quantum cryptography by Dec 31, 2030 and digital signatures by
Dec 31, 2031. OMB M-26-15 asks agencies for a PQC migration plan built on a
cryptographic inventory (a cryptographic bill of materials, CBOM),
prioritizing High Value Assets, high-impact systems and data that must stay
sensitive past 2030, with TLS 1.3 (or successor) support by Jan 2, 2030.

This module keeps a versioned cryptographic inventory per system (every
change written to the agency's tamper-evident "pqc-inventory" log), classifies
algorithms, builds a prioritized migration plan with per-asset deadlines and
findings, and exports the CBOM + plan sealed on chain (Base).

The rules below follow public summaries of the order and memo; confirm
against the official texts and NIST IR 8547 before relying on them.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from typing import Any

KEY_ESTABLISHMENT_DEADLINE = "2030-12-31"
SIGNATURE_DEADLINE = "2031-12-31"
TLS13_DEADLINE = "2030-01-02"

KINDS = ("key_establishment", "signature", "encryption", "symmetric", "hash", "protocol", "certificate")
STATUSES = ("not_started", "planned", "in_progress", "hybrid", "migrated")

# quantum-vulnerable public-key families (M-26-15 Appendix A per public summaries, plus EdDSA/X25519 as EC-based)
VULNERABLE = [
    (r"\bRSA", "RSA"), (r"\bECDHE?\b|\bECDH[-_]", "ECDH"), (r"\bECDSA", "ECDSA"),
    (r"X25519|X448", "ECDH (Curve25519/448)"), (r"\bEd25519\b|\bEd448\b|\bEdDSA", "EdDSA"),
    (r"\bDHE?\b|\bDiffie", "Diffie-Hellman"), (r"\bMQV", "MQV"), (r"(?<![-A-Za-z])DSA\b", "DSA"),
    (r"\bP-?256\b|\bP-?384\b|\bP-?521\b|\bsecp\d+", "elliptic curve"),
]
PQC = [
    (r"ML-?KEM|Kyber", "ML-KEM (FIPS 203)"), (r"ML-?DSA|Dilithium", "ML-DSA (FIPS 204)"),
    (r"SLH-?DSA|SPHINCS", "SLH-DSA (FIPS 205)"), (r"LMS|XMSS", "stateful hash-based signature (SP 800-208)"),
]


def classify(algorithm: str) -> dict:
    a = (algorithm or "").strip()
    pqc = [name for rx, name in PQC if re.search(rx, a, re.I)]
    vul = [name for rx, name in VULNERABLE if re.search(rx, a, re.I)]
    if pqc and vul:
        return {"algorithm": a, "class": "hybrid", "pqc": pqc, "classical": vul, "quantum_vulnerable": False,
                "note": "Hybrid classical + post-quantum; acceptable during transition"}
    if pqc:
        return {"algorithm": a, "class": "post_quantum", "pqc": pqc, "quantum_vulnerable": False}
    if vul:
        return {"algorithm": a, "class": "quantum_vulnerable", "classical": vul, "quantum_vulnerable": True,
                "note": "Public-key algorithm breakable by a cryptographically relevant quantum computer"}
    if re.search(r"AES|ChaCha|SHA-?2|SHA-?3|SHA256|SHA384|SHA512|HMAC|Camellia", a, re.I):
        return {"algorithm": a, "class": "symmetric_or_hash", "quantum_vulnerable": False,
                "note": "Not in the public-key migration scope"}
    return {"algorithm": a, "class": "unknown", "quantum_vulnerable": None, "note": "Unrecognized; review manually"}


def tls_version(protocol: str) -> float | None:
    m = re.search(r"TLS\s*v?(1)\.(\d)", protocol or "", re.I)
    return float(f"{m.group(1)}.{m.group(2)}") if m else None


SYSTEM_FIELDS = {"system_id": str, "name": str, "bureau": str, "owner": str, "high_value_asset": bool,
                 "high_impact": bool, "sensitive_until_year": int, "fedramp_cloud": bool, "notes": str, "assets": list}
ASSET_FIELDS = {"asset_id": str, "kind": str, "algorithm": str, "key_size": str, "protocol": str,
                "location": str, "product": str, "vendor": str, "status": str, "target_date": str,
                "replacement": str, "evidence": str}
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS pqc_systems (
    org_id TEXT NOT NULL, system_id TEXT NOT NULL, version INTEGER NOT NULL,
    record TEXT NOT NULL, record_hash TEXT NOT NULL, saved_at TEXT NOT NULL,
    PRIMARY KEY (org_id, system_id, version)
);
CREATE TABLE IF NOT EXISTS pqc_exports (
    export_hash TEXT PRIMARY KEY, org_id TEXT NOT NULL, attestation TEXT NOT NULL, created_at TEXT NOT NULL
);
"""


def _canon(o: Any) -> str:
    return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _check(obj: dict, fields: dict, what: str) -> dict:
    if not isinstance(obj, dict):
        raise ValueError(f"{what} must be an object")
    bad = set(obj) - set(fields)
    if bad:
        raise ValueError(f"unknown {what} field(s): {', '.join(sorted(bad))}")
    out = {}
    for k, v in obj.items():
        if v is None:
            continue
        t = fields[k]
        if t is bool and not isinstance(v, bool) or t is int and (not isinstance(v, int) or isinstance(v, bool)) \
                or t is str and not isinstance(v, str) or t is list and not isinstance(v, list):
            raise ValueError(f"{what}.{k} has the wrong type")
        out[k] = v.strip() if isinstance(v, str) else v
    return out


def validate_system(s: dict) -> dict:
    out = _check(s, SYSTEM_FIELDS, "system")
    if not ID_RE.match(out.get("system_id", "")):
        raise ValueError("system_id is required: 1-64 letters, digits, . _ -")
    assets, seen = [], set()
    for a in out.get("assets", []):
        a = _check(a, ASSET_FIELDS, "asset")
        if not ID_RE.match(a.get("asset_id", "")) or a["asset_id"] in seen:
            raise ValueError("each asset needs a unique asset_id")
        seen.add(a["asset_id"])
        if a.get("kind") not in KINDS:
            raise ValueError(f"asset {a['asset_id']}: kind must be one of {', '.join(KINDS)}")
        if a.get("status", "not_started") not in STATUSES:
            raise ValueError(f"asset {a['asset_id']}: status must be one of {', '.join(STATUSES)}")
        if not a.get("algorithm") and a["kind"] != "protocol":
            raise ValueError(f"asset {a['asset_id']}: algorithm is required")
        if a.get("target_date"):
            date.fromisoformat(a["target_date"])
        assets.append(a)
    out["assets"] = assets
    if len(_canon(out)) > 64_000:
        raise ValueError("system record is too large")
    return out


class QuantumReady:
    def __init__(self, ledger):
        self.ledger, self._db, self._lock = ledger, ledger._db, ledger._lock
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.commit()

    def latest(self, org_id: str, system_id: str | None = None) -> list[dict]:
        sql = """SELECT s.* FROM pqc_systems s JOIN (SELECT system_id, MAX(version) v FROM pqc_systems
                 WHERE org_id=? GROUP BY system_id) m ON s.system_id=m.system_id AND s.version=m.v WHERE s.org_id=?"""
        args: list[Any] = [org_id, org_id]
        if system_id:
            sql += " AND s.system_id=?"; args.append(system_id)
        return [{"system_id": r["system_id"], "version": r["version"], "record_hash": r["record_hash"],
                 "saved_at": r["saved_at"], "record": json.loads(r["record"])}
                for r in self._db.execute(sql + " ORDER BY s.system_id", args).fetchall()]

    def save(self, org_id: str, actor: str, system: dict) -> dict:
        rec = validate_system(system)
        prev = self.latest(org_id, rec["system_id"])
        h = hashlib.sha256(_canon(rec).encode()).hexdigest()
        if prev and prev[0]["record_hash"] == h:
            return {"system_id": rec["system_id"], "version": prev[0]["version"], "changed": False, "record_hash": h}
        v = prev[0]["version"] + 1 if prev else 1
        with self._lock:
            self._db.execute("INSERT INTO pqc_systems VALUES (?,?,?,?,?,?)",
                             (org_id, rec["system_id"], v, _canon(rec), h, _now_iso()))
            self._db.commit()
        vul = sum(1 for a in rec["assets"] if classify(a.get("algorithm", "")).get("quantum_vulnerable"))
        e = self.ledger.record(org_id, "pqc-inventory", actor, "data_change",
                               f"{'Updated' if prev else 'Added'} cryptographic inventory for {rec['system_id']} (v{v})",
                               f"system:{rec['system_id']}", "success",
                               {"system_id": rec["system_id"], "version": v, "record_hash": h,
                                "assets": len(rec["assets"]), "quantum_vulnerable_assets": vul})
        return {"system_id": rec["system_id"], "version": v, "changed": True, "record_hash": h,
                "assets": len(rec["assets"]), "quantum_vulnerable_assets": vul, "log_entry_hash": e["entry_hash"]}

    def plan(self, org_id: str, today: date | None = None) -> dict:
        today = today or datetime.now(timezone.utc).date()
        items, findings = [], []
        metrics = {"systems": 0, "assets": 0, "quantum_vulnerable": 0, "migrated_or_pqc": 0, "hybrid": 0,
                   "unknown_algorithms": 0, "tls_below_1_3": 0}
        for s in self.latest(org_id):
            r = s["record"]; metrics["systems"] += 1
            sys_weight = (40 if r.get("high_value_asset") else 0) + (25 if r.get("high_impact") else 0) + \
                         (20 if (r.get("sensitive_until_year") or 0) >= 2030 else 0) + (5 if r.get("fedramp_cloud") else 0)
            if not r["assets"]:
                findings.append({"system_id": r["system_id"], "severity": "medium",
                                 "finding": "no cryptographic assets inventoried for this system"})
            for a in r["assets"]:
                metrics["assets"] += 1
                c = classify(a.get("algorithm", "")) if a.get("algorithm") else {"class": "n/a", "quantum_vulnerable": False}
                status = a.get("status", "not_started")
                tv = tls_version(a.get("protocol", ""))
                if tv is not None and tv < 1.3:
                    metrics["tls_below_1_3"] += 1
                    findings.append({"system_id": r["system_id"], "asset_id": a["asset_id"], "severity": "medium",
                                     "finding": f"uses TLS {tv}; TLS 1.3 or successor support needed by {TLS13_DEADLINE}"})
                if c["class"] == "unknown":
                    metrics["unknown_algorithms"] += 1
                    findings.append({"system_id": r["system_id"], "asset_id": a["asset_id"], "severity": "low",
                                     "finding": f"unrecognized algorithm '{a.get('algorithm')}'; classify manually"})
                if c["class"] in ("post_quantum",) or status == "migrated":
                    metrics["migrated_or_pqc"] += 1
                    continue
                if c["class"] == "hybrid" or status == "hybrid":
                    metrics["hybrid"] += 1
                    continue
                if not c.get("quantum_vulnerable"):
                    continue
                metrics["quantum_vulnerable"] += 1
                deadline = SIGNATURE_DEADLINE if a["kind"] in ("signature", "certificate") else KEY_ESTABLISHMENT_DEADLINE
                kind_weight = 20 if a["kind"] in ("key_establishment", "encryption", "protocol") else 10
                priority = sys_weight + kind_weight + (0 if status in ("in_progress", "planned") else 5)
                target = a.get("target_date")
                if target and target > deadline:
                    findings.append({"system_id": r["system_id"], "asset_id": a["asset_id"], "severity": "critical",
                                     "finding": f"target {target} is after the {deadline} deadline for {a['kind']}"})
                if not target and (r.get("high_value_asset") or r.get("high_impact")):
                    findings.append({"system_id": r["system_id"], "asset_id": a["asset_id"], "severity": "medium",
                                     "finding": "priority system with a quantum-vulnerable asset and no target date"})
                items.append({
                    "priority_score": priority, "system_id": r["system_id"], "system_name": r.get("name", ""),
                    "asset_id": a["asset_id"], "kind": a["kind"], "algorithm": a.get("algorithm", ""),
                    "vulnerable_family": c.get("classical"), "status": status, "deadline": deadline,
                    "target_date": target,
                    "recommended_replacement": a.get("replacement") or (
                        "ML-KEM (FIPS 203), hybrid during transition" if a["kind"] in ("key_establishment", "encryption", "protocol")
                        else "ML-DSA (FIPS 204) or SLH-DSA (FIPS 205)"),
                    "phase": "Phase 3 (2028-2030): key establishment" if deadline == KEY_ESTABLISHMENT_DEADLINE
                             else "Phase 4 (2031): digital signatures",
                    "why": ", ".join(x for x in [
                        "High Value Asset" if r.get("high_value_asset") else "",
                        "high-impact system" if r.get("high_impact") else "",
                        f"data sensitive until {r['sensitive_until_year']}" if (r.get("sensitive_until_year") or 0) >= 2030 else "",
                        "key establishment (harvest-now-decrypt-later risk)" if kind_weight == 20 else "signature",
                    ] if x),
                })
        items.sort(key=lambda x: (-x["priority_score"], x["deadline"], x["system_id"], x["asset_id"]))
        for i, it in enumerate(items, 1):
            it["rank"] = i
        done = metrics["migrated_or_pqc"] + metrics["hybrid"]
        considered = done + metrics["quantum_vulnerable"]
        counts = {s: sum(1 for f in findings if f["severity"] == s) for s in ("critical", "medium", "low")}
        return {
            "generated_on": today.isoformat(),
            "deadlines": {"key_establishment": KEY_ESTABLISHMENT_DEADLINE, "digital_signatures": SIGNATURE_DEADLINE,
                          "tls_1_3_support": TLS13_DEADLINE},
            "days_to_key_establishment_deadline": (date.fromisoformat(KEY_ESTABLISHMENT_DEADLINE) - today).days,
            "metrics": {**metrics, "migration_progress_pct": round(100 * done / considered, 1) if considered else None},
            "finding_counts": counts, "findings": findings, "migration_queue": items,
            "basis": "EO 14409 (June 2026) deadlines and OMB M-26-15 priorities as publicly summarized; confirm against official texts and NIST IR 8547",
        }

    def save_export(self, org_id: str, h: str, attestation: dict) -> None:
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO pqc_exports VALUES (?,?,?,?)", (h, org_id, json.dumps(attestation), _now_iso()))
            self._db.commit()

    def find_export(self, h: str) -> dict | None:
        r = self._db.execute("SELECT * FROM pqc_exports WHERE export_hash=?", (h,)).fetchone()
        return {"org_id": r["org_id"], "created_at": r["created_at"], "attestation": json.loads(r["attestation"])} if r else None


def canonical_json(obj: Any) -> str:
    return _canon(obj)
