"""Privi Gov AI Inventory: federal AI use-case inventories (OMB M-25-21).

Agencies must keep an inventory of AI use cases with specific fields, publish
the releasable ones as a machine-readable file, and show minimum risk
management practices for high-impact AI (pre-deployment testing, impact
assessment, independent review, ongoing monitoring, operator training,
fail-safe, appeal process, public feedback). See the OMB "Guidance on 2025
Agency AI Reporting" under M-25-21.

Here every use case is versioned; each change is also written to the
organization's tamper-evident "ai-inventory" log; a gap check flags what an
OMB review would flag; and the public export is hashed and sealed on the
chain (Base, until the Privi chain mainnet) so the published file can be proven unaltered.

Field names follow the guidance's reporting fields. Confirm column names
against OMB's official template before submission.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

STAGES = ("pre_deployment", "pilot", "deployed", "retired")
SOURCING = ("in_house", "vendor", "both")

HIGH_IMPACT_PRACTICES = {
    "pre_deployment_testing": "Pre-deployment testing completed",
    "impact_assessment": "AI impact assessment completed",
    "independent_review": "Independent review completed",
    "ongoing_monitoring": "Ongoing monitoring of performance, security, privacy, civil rights and civil liberties",
    "operator_training": "Operators receive sufficient, periodic training",
    "fail_safe": "Appropriate fail-safe in place",
    "appeal_process": "Appeal process for affected individuals",
    "public_feedback": "Feedback gathered from end users and the public",
}

REQUIRED = ("name", "stage", "high_impact", "purpose", "outputs", "sourcing", "involves_pii", "custom_code")

FIELDS = {
    # identity
    "use_case_id": str, "name": str, "bureau": str, "contact_email": str,
    # status & classification
    "stage": str, "high_impact": bool, "topic_area": str, "ai_classification": str,
    "withhold_from_public": bool,
    # purpose
    "purpose": str, "expected_benefits": str, "outputs": str, "start_date": str,
    # sourcing
    "sourcing": str, "vendor_name": str, "ato_system_name": str,
    # data & privacy
    "data_description": str, "open_data_link": str, "involves_pii": bool, "pia_link": str,
    "demographic_features": str,
    # code
    "custom_code": bool, "code_link": str,
    # high-impact practices: each a dict {"done": bool, "evidence": str, "date": str}
    "practices": dict,
    # waiver of a practice (CAIO written determination)
    "waivers": list,
    # Privi Ledger stream(s) holding this system's activity log, used as monitoring evidence
    "monitoring_streams": list,
}

PUBLIC_COLUMNS = [
    "use_case_id", "name", "bureau", "stage", "high_impact", "topic_area", "ai_classification", "purpose",
    "expected_benefits", "outputs", "start_date", "sourcing", "vendor_name", "ato_system_name",
    "data_description", "open_data_link", "involves_pii", "pia_link", "demographic_features", "custom_code",
    "code_link",
] + [f"practice_{k}" for k in HIGH_IMPACT_PRACTICES]

SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_exports (
    export_hash  TEXT PRIMARY KEY,
    org_id       TEXT NOT NULL,
    rows         INTEGER NOT NULL,
    attestation  TEXT NOT NULL,
    created_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ai_use_cases (
    org_id       TEXT NOT NULL,
    use_case_id  TEXT NOT NULL,
    version      INTEGER NOT NULL,
    record       TEXT NOT NULL,
    record_hash  TEXT NOT NULL,
    saved_at     TEXT NOT NULL,
    PRIMARY KEY (org_id, use_case_id, version)
);
"""

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def validate(uc: dict) -> dict:
    if not isinstance(uc, dict):
        raise ValueError("use_case must be an object")
    unknown = set(uc) - set(FIELDS)
    if unknown:
        raise ValueError(f"unknown field(s): {', '.join(sorted(unknown))}")
    out: dict[str, Any] = {}
    for k, v in uc.items():
        typ = FIELDS[k]
        if v is None:
            continue
        if typ is bool and not isinstance(v, bool):
            raise ValueError(f"{k} must be true or false")
        if typ is str and not isinstance(v, str):
            raise ValueError(f"{k} must be text")
        if typ in (dict, list) and not isinstance(v, typ):
            raise ValueError(f"{k} must be a {'object' if typ is dict else 'list'}")
        out[k] = v.strip() if isinstance(v, str) else v
    if not ID_RE.match(out.get("use_case_id", "")):
        raise ValueError("use_case_id is required: 1-64 letters, digits, . _ -")
    if "stage" in out and out["stage"] not in STAGES:
        raise ValueError(f"stage must be one of {', '.join(STAGES)}")
    if "sourcing" in out and out["sourcing"] not in SOURCING:
        raise ValueError(f"sourcing must be one of {', '.join(SOURCING)}")
    for k, p in (out.get("practices") or {}).items():
        if k not in HIGH_IMPACT_PRACTICES:
            raise ValueError(f"unknown practice '{k}'; use: {', '.join(HIGH_IMPACT_PRACTICES)}")
        if not isinstance(p, dict) or not isinstance(p.get("done"), bool):
            raise ValueError(f"practice '{k}' must be like {{\"done\": true, \"evidence\": \"...\"}}")
    for w in out.get("waivers") or []:
        if not isinstance(w, dict) or w.get("practice") not in HIGH_IMPACT_PRACTICES or not w.get("justification"):
            raise ValueError("each waiver needs a practice name and a written justification")
    if len(_canon(out)) > 32_000:
        raise ValueError("use case record is too large")
    return out


class GovAIInventory:
    def __init__(self, ledger):
        self.ledger, self._db, self._lock = ledger, ledger._db, ledger._lock
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.commit()

    def latest(self, org_id: str, use_case_id: str | None = None) -> list[dict]:
        sql = """SELECT u.* FROM ai_use_cases u JOIN (SELECT use_case_id, MAX(version) v FROM ai_use_cases
                 WHERE org_id=? GROUP BY use_case_id) m ON u.use_case_id=m.use_case_id AND u.version=m.v
                 WHERE u.org_id=?"""
        args: list[Any] = [org_id, org_id]
        if use_case_id:
            sql += " AND u.use_case_id=?"
            args.append(use_case_id)
        rows = self._db.execute(sql + " ORDER BY u.use_case_id", args).fetchall()
        return [{"use_case_id": r["use_case_id"], "version": r["version"], "record_hash": r["record_hash"],
                 "saved_at": r["saved_at"], "record": json.loads(r["record"])} for r in rows]

    def upsert(self, org_id: str, actor: str, use_case: dict, merge: bool = True) -> dict:
        uc = validate(use_case)
        prev = self.latest(org_id, uc["use_case_id"])
        record = {**(prev[0]["record"] if prev and merge else {}), **uc}
        if merge and "practices" in uc and prev:
            record["practices"] = {**prev[0]["record"].get("practices", {}), **uc["practices"]}
        version = prev[0]["version"] + 1 if prev else 1
        h = hashlib.sha256(_canon(record).encode()).hexdigest()
        if prev and prev[0]["record_hash"] == h:
            return {"use_case_id": uc["use_case_id"], "version": prev[0]["version"], "changed": False, "record_hash": h}
        with self._lock:
            self._db.execute("INSERT INTO ai_use_cases VALUES (?,?,?,?,?,?)",
                             (org_id, uc["use_case_id"], version, _canon(record), h, _now().isoformat(timespec="seconds")))
            self._db.commit()
        changed = sorted(k for k in record if not prev or prev[0]["record"].get(k) != record.get(k))
        entry = self.ledger.record(org_id, "ai-inventory", actor, "data_change",
                                   f"{'Updated' if prev else 'Added'} AI use case {uc['use_case_id']} (v{version})",
                                   f"ai-use-case:{uc['use_case_id']}", "success",
                                   {"use_case_id": uc["use_case_id"], "version": version, "record_hash": h,
                                    "changed_fields": changed})
        return {"use_case_id": uc["use_case_id"], "version": version, "changed": True, "record_hash": h,
                "changed_fields": changed, "log_entry_hash": entry["entry_hash"]}

    def check(self, org_id: str) -> dict:
        findings: list[dict] = []
        cases = self.latest(org_id)
        since = (_now() - timedelta(days=30)).isoformat(timespec="seconds")
        for c in cases:
            r, uid = c["record"], c["use_case_id"]
            if r.get("stage") == "retired":
                continue
            for f in REQUIRED:
                if f not in r or r[f] in ("", None):
                    findings.append({"use_case_id": uid, "severity": "medium", "finding": f"missing required field '{f}'"})
            if r.get("sourcing") in ("vendor", "both") and not r.get("vendor_name"):
                findings.append({"use_case_id": uid, "severity": "low", "finding": "vendor-sourced but vendor_name is empty"})
            if r.get("involves_pii") and not r.get("pia_link"):
                findings.append({"use_case_id": uid, "severity": "medium",
                                 "finding": "uses PII but no Privacy Impact Assessment link"})
            if r.get("custom_code") and not r.get("code_link") and not r.get("withhold_from_public"):
                findings.append({"use_case_id": uid, "severity": "low", "finding": "custom code with no code link"})
            if r.get("high_impact") and r.get("stage") in ("pilot", "deployed"):
                waived = {w["practice"] for w in r.get("waivers") or []}
                for p, label in HIGH_IMPACT_PRACTICES.items():
                    pr = (r.get("practices") or {}).get(p)
                    if p in waived:
                        continue
                    if not pr or not pr.get("done"):
                        findings.append({"use_case_id": uid, "severity": "critical" if r["stage"] == "deployed" else "medium",
                                         "finding": f"high-impact practice not met: {label}"})
                    elif not pr.get("evidence"):
                        findings.append({"use_case_id": uid, "severity": "low",
                                         "finding": f"no evidence recorded for: {label}"})
                streams = r.get("monitoring_streams") or []
                if not streams:
                    findings.append({"use_case_id": uid, "severity": "medium",
                                     "finding": "no activity log linked (monitoring_streams) as monitoring evidence"})
                for s in streams:
                    n = self._db.execute("SELECT COUNT(*) FROM entries WHERE org_id=? AND stream_id=? AND recorded_at>=?",
                                         (org_id, s, since)).fetchone()[0]
                    if n == 0:
                        findings.append({"use_case_id": uid, "severity": "medium",
                                         "finding": f"linked log '{s}' has no activity in the last 30 days"})
        counts = {s: sum(1 for f in findings if f["severity"] == s) for s in ("critical", "medium", "low")}
        active = [c for c in cases if c["record"].get("stage") != "retired"]
        return {"use_cases": len(cases), "active": len(active),
                "high_impact_active": sum(1 for c in active if c["record"].get("high_impact")),
                "ready_for_submission": counts["critical"] == 0 and counts["medium"] == 0,
                "finding_counts": counts, "findings": findings}

    def export_csv(self, org_id: str, include_withheld: bool = False) -> tuple[str, int]:
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=PUBLIC_COLUMNS, lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        n = 0
        for c in self.latest(org_id):
            r = c["record"]
            if r.get("withhold_from_public") and not include_withheld:
                continue
            row = {k: r.get(k, "") for k in PUBLIC_COLUMNS if not k.startswith("practice_")}
            for k in ("high_impact", "involves_pii", "custom_code"):
                if k in r:
                    row[k] = "Yes" if r[k] else "No"
            if r.get("high_impact"):
                waived = {wv["practice"] for wv in r.get("waivers") or []}
                for p in HIGH_IMPACT_PRACTICES:
                    pr = (r.get("practices") or {}).get(p) or {}
                    row[f"practice_{p}"] = "Waived" if p in waived else ("Yes" if pr.get("done") else "No")
            w.writerow(row)
            n += 1
        return buf.getvalue(), n


    def save_export(self, org_id: str, export_hash: str, rows: int, attestation: dict) -> None:
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO ai_exports VALUES (?,?,?,?,?)",
                             (export_hash, org_id, rows, json.dumps(attestation), _now().isoformat(timespec="seconds")))
            self._db.commit()

    def find_export(self, export_hash: str) -> dict | None:
        r = self._db.execute("SELECT * FROM ai_exports WHERE export_hash=?", (export_hash,)).fetchone()
        if not r:
            return None
        return {"org_id": r["org_id"], "rows": r["rows"], "created_at": r["created_at"],
                "attestation": json.loads(r["attestation"])}
