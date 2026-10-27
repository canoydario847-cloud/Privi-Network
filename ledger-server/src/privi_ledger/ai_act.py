"""Privi AI Act Pack: the EU AI Act register every company using AI needs.

Any company that builds (provider) or uses (deployer) AI in the EU market has to
know which tier each system falls in and prove which obligations it meets. Here
each AI system is screened against the Article 5 prohibited practices,
classified (prohibited / high-risk / transparency / general-purpose / minimal),
mapped to the obligations that apply to its role, and checked against evidence.
Every change is versioned and written to the organization's tamper-evident
"ai-act" log, and the exported register is hashed and sealed on chain, so a
company can prove to a customer, auditor or regulator what its register said
and when.

Application dates reflect Regulation (EU) 2024/1689 as amended by the Digital
Omnibus on AI (Regulation (EU) 2026/1744, in force 27 July 2026): Annex III
high-risk duties from 2 Dec 2027, Annex I (product-embedded) from 2 Aug 2028.
This is a compliance workflow tool, not legal advice; confirm dates and scope
with counsel.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

ROLES = ("provider", "deployer", "provider_and_deployer", "importer", "distributor")

ANNEX_III_AREAS = {
    "biometrics": "Remote biometric identification, biometric categorisation, emotion recognition",
    "critical_infrastructure": "Safety components of critical infrastructure (energy, water, traffic, digital)",
    "education": "Admissions, assessment, proctoring and steering in education and vocational training",
    "employment": "Recruitment, selection, promotion, termination, task allocation, worker monitoring",
    "essential_services": "Public benefits, creditworthiness, life/health insurance pricing, emergency dispatch",
    "law_enforcement": "Risk assessment, evidence evaluation, profiling by law enforcement",
    "migration": "Migration, asylum and border control",
    "justice_democracy": "Administration of justice and influencing elections or voting",
}

# Article 5: practices banned outright (true = the system does this)
PROHIBITED = {
    "harmful_manipulation": "Subliminal, manipulative or deceptive techniques that materially distort behaviour",
    "exploiting_vulnerabilities": "Exploiting vulnerabilities due to age, disability or social/economic situation",
    "social_scoring": "Social scoring leading to detrimental or disproportionate treatment",
    "predictive_policing_profiling": "Predicting criminal offences based solely on profiling or personality traits",
    "untargeted_face_scraping": "Untargeted scraping of facial images to build recognition databases",
    "workplace_school_emotion_recognition": "Emotion recognition in the workplace or education (non-medical/safety)",
    "biometric_categorisation_sensitive": "Biometric categorisation inferring race, politics, religion, sex life, etc.",
    "realtime_remote_biometric_id_public": "Real-time remote biometric identification in public for law enforcement",
    "non_consensual_intimate_imagery": "Generating non-consensual intimate imagery or child sexual abuse material",
}

D = date.fromisoformat
LITERACY, GPAI_DATE, TRANSPARENCY, MARKING = D("2025-02-02"), D("2025-08-02"), D("2026-08-02"), D("2026-12-02")
NEW_PROHIBITIONS = D("2026-12-02")
HIGH_RISK_ANNEX_III, HIGH_RISK_ANNEX_I = D("2027-12-02"), D("2028-08-02")

PROVIDER_ROLES = {"provider", "provider_and_deployer"}
DEPLOYER_ROLES = {"deployer", "provider_and_deployer"}


def _hr_date(r: dict) -> date:
    return HIGH_RISK_ANNEX_I if r.get("annex_i_product") and not r.get("annex_iii_area") else HIGH_RISK_ANNEX_III


def _prov(r):
    return r.get("role") in PROVIDER_ROLES


def _depl(r):
    return r.get("role") in DEPLOYER_ROLES


def _hr(r):
    return bool(r.get("annex_iii_area") or r.get("annex_i_product"))


# id: (article, title, applies(record) -> bool, application date(record) -> date)
OBLIGATIONS: dict[str, tuple[str, str, Any, Any]] = {
    "ai_literacy": ("Art. 4", "Staff operating the system have sufficient AI literacy", lambda r: True, lambda r: LITERACY),
    "disclose_ai_interaction": ("Art. 50(1)", "People are told they are interacting with an AI system",
                                lambda r: _prov(r) and r.get("interacts_with_people"), lambda r: TRANSPARENCY),
    "mark_synthetic_content": ("Art. 50(2)", "AI-generated audio, image, video or text is machine-readably marked",
                               lambda r: _prov(r) and r.get("generates_synthetic_content"), lambda r: MARKING),
    "inform_emotion_biometric": ("Art. 50(3)", "People exposed to emotion recognition / biometric categorisation are informed",
                                 lambda r: _depl(r) and r.get("emotion_or_biometric_categorisation"), lambda r: TRANSPARENCY),
    "disclose_deepfake": ("Art. 50(4)", "Deep fakes and AI text on matters of public interest are disclosed",
                          lambda r: _depl(r) and r.get("deepfake_or_public_interest_text"), lambda r: TRANSPARENCY),
    "gpai_technical_documentation": ("Art. 53(1)(a-b)", "GPAI model technical documentation for the AI Office and downstream providers",
                                     lambda r: _prov(r) and r.get("gpai_model"), lambda r: GPAI_DATE),
    "gpai_copyright_policy": ("Art. 53(1)(c)", "Policy to comply with EU copyright law, incl. text-and-data-mining opt-outs",
                              lambda r: _prov(r) and r.get("gpai_model"), lambda r: GPAI_DATE),
    "gpai_training_summary": ("Art. 53(1)(d)", "Public summary of the content used for training",
                              lambda r: _prov(r) and r.get("gpai_model"), lambda r: GPAI_DATE),
    # high-risk: providers
    "risk_management": ("Art. 9", "Risk management system across the lifecycle", lambda r: _hr(r) and _prov(r), _hr_date),
    "data_governance": ("Art. 10", "Training, validation and test data governance", lambda r: _hr(r) and _prov(r), _hr_date),
    "technical_documentation": ("Art. 11", "Technical documentation (Annex IV)", lambda r: _hr(r) and _prov(r), _hr_date),
    "automatic_logging": ("Art. 12", "Automatic recording of events (logs) over the system's lifetime",
                          lambda r: _hr(r) and _prov(r), _hr_date),
    "instructions_for_use": ("Art. 13", "Transparency and instructions for use to deployers", lambda r: _hr(r) and _prov(r), _hr_date),
    "human_oversight_design": ("Art. 14", "Designed for effective human oversight", lambda r: _hr(r) and _prov(r), _hr_date),
    "accuracy_robustness_security": ("Art. 15", "Accuracy, robustness and cybersecurity", lambda r: _hr(r) and _prov(r), _hr_date),
    "quality_management": ("Art. 17", "Quality management system", lambda r: _hr(r) and _prov(r), _hr_date),
    "conformity_assessment": ("Art. 43", "Conformity assessment, EU declaration of conformity and CE marking",
                              lambda r: _hr(r) and _prov(r), _hr_date),
    "eu_database_registration": ("Art. 49", "Registered in the EU database", lambda r: _hr(r) and _prov(r), _hr_date),
    "post_market_monitoring": ("Art. 72", "Post-market monitoring plan", lambda r: _hr(r) and _prov(r), _hr_date),
    # high-risk: deployers
    "use_per_instructions": ("Art. 26(1)", "Used according to the provider's instructions", lambda r: _hr(r) and _depl(r), _hr_date),
    "human_oversight_assigned": ("Art. 26(2)", "Competent, trained people assigned to human oversight",
                                 lambda r: _hr(r) and _depl(r), _hr_date),
    "monitor_and_report": ("Art. 26(5)", "Operation monitored; serious incidents reported", lambda r: _hr(r) and _depl(r), _hr_date),
    "keep_logs_6_months": ("Art. 26(6)", "Automatically generated logs kept at least six months",
                           lambda r: _hr(r) and _depl(r), _hr_date),
    "inform_workers": ("Art. 26(7)", "Workers' representatives and affected workers informed before workplace use",
                       lambda r: _hr(r) and _depl(r) and r.get("annex_iii_area") == "employment", _hr_date),
    "inform_affected_persons": ("Art. 26(11)", "People subject to decisions are informed that high-risk AI is used",
                                lambda r: _hr(r) and _depl(r) and bool(r.get("annex_iii_area")), _hr_date),
    "fundamental_rights_impact_assessment": ("Art. 27", "Fundamental rights impact assessment before first use",
                                             lambda r: _hr(r) and _depl(r) and (r.get("public_body_or_public_service")
                                                                               or r.get("annex_iii_area") == "essential_services"),
                                             _hr_date),
}

FIELDS = {
    "system_id": str, "name": str, "owner": str, "description": str, "role": str, "vendor_name": str,
    "used_in_eu": bool, "intended_purpose": str,
    "annex_iii_area": str, "annex_i_product": bool, "gpai_model": bool, "public_body_or_public_service": bool,
    "interacts_with_people": bool, "generates_synthetic_content": bool, "emotion_or_biometric_categorisation": bool,
    "deepfake_or_public_interest_text": bool,
    "not_high_risk_justification": str,          # Art. 6(3) derogation, documented
    "prohibited_screen": dict,                   # {practice: bool}
    "controls": dict,                            # {obligation_id: {done, evidence, date}}
    "log_streams": list,                         # Privi Ledger streams holding the system's logs
    "retired": bool,
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_act_systems (
    org_id      TEXT NOT NULL,
    system_id   TEXT NOT NULL,
    version     INTEGER NOT NULL,
    record      TEXT NOT NULL,
    record_hash TEXT NOT NULL,
    saved_at    TEXT NOT NULL,
    PRIMARY KEY (org_id, system_id, version)
);
CREATE TABLE IF NOT EXISTS ai_act_exports (
    export_hash TEXT PRIMARY KEY,
    org_id      TEXT NOT NULL,
    systems     INTEGER NOT NULL,
    attestation TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
"""

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
DISCLAIMER = ("Workflow aid, not legal advice. Dates follow Regulation (EU) 2024/1689 as amended by the Digital "
              "Omnibus on AI (Regulation (EU) 2026/1744); confirm scope and dates with counsel.")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def validate(sys_: dict) -> dict:
    if not isinstance(sys_, dict):
        raise ValueError("system must be an object")
    unknown = set(sys_) - set(FIELDS)
    if unknown:
        raise ValueError(f"unknown field(s): {', '.join(sorted(unknown))}")
    out: dict[str, Any] = {}
    for k, v in sys_.items():
        if v is None:
            continue
        typ = FIELDS[k]
        if typ is bool and not isinstance(v, bool):
            raise ValueError(f"{k} must be true or false")
        if typ is str and not isinstance(v, str):
            raise ValueError(f"{k} must be text")
        if typ in (dict, list) and not isinstance(v, typ):
            raise ValueError(f"{k} must be a {'object' if typ is dict else 'list'}")
        out[k] = v.strip() if isinstance(v, str) else v
    if not ID_RE.match(out.get("system_id", "")):
        raise ValueError("system_id is required: 1-64 letters, digits, . _ -")
    if "role" in out and out["role"] not in ROLES:
        raise ValueError(f"role must be one of {', '.join(ROLES)}")
    if out.get("annex_iii_area") and out["annex_iii_area"] not in ANNEX_III_AREAS:
        raise ValueError(f"annex_iii_area must be one of {', '.join(ANNEX_III_AREAS)} (or empty)")
    for k, v in (out.get("prohibited_screen") or {}).items():
        if k not in PROHIBITED or not isinstance(v, bool):
            raise ValueError(f"prohibited_screen keys must be from {', '.join(PROHIBITED)} with true/false values")
    for k, c in (out.get("controls") or {}).items():
        if k not in OBLIGATIONS:
            raise ValueError(f"unknown control '{k}'; use: {', '.join(OBLIGATIONS)}")
        if not isinstance(c, dict) or not isinstance(c.get("done"), bool):
            raise ValueError(f"control '{k}' must be like {{\"done\": true, \"evidence\": \"...\"}}")
    if any(not isinstance(s, str) for s in out.get("log_streams") or []):
        raise ValueError("log_streams must be a list of stream IDs")
    if len(canon(out)) > 32_000:
        raise ValueError("system record is too large")
    return out


def classify(r: dict) -> dict:
    """Tier and the obligations that apply to this system, with dates."""
    screen = r.get("prohibited_screen") or {}
    banned = [k for k, v in screen.items() if v]
    if banned:
        tier = "prohibited"
    elif r.get("annex_iii_area") and r.get("not_high_risk_justification") and not r.get("annex_i_product"):
        tier = "annex_iii_not_high_risk"     # Art. 6(3) derogation: documented, still registered
    elif _hr(r):
        tier = "high_risk"
    elif r.get("gpai_model"):
        tier = "general_purpose"
    elif any(r.get(k) for k in ("interacts_with_people", "generates_synthetic_content",
                                "emotion_or_biometric_categorisation", "deepfake_or_public_interest_text")):
        tier = "transparency"
    else:
        tier = "minimal"
    rr = dict(r)
    if tier == "annex_iii_not_high_risk":
        rr["annex_iii_area"] = ""
    obligations = []
    for oid, (art, title, applies, when) in OBLIGATIONS.items():
        if applies(rr):
            obligations.append({"id": oid, "article": art, "title": title, "applies_from": when(rr).isoformat()})
    return {"tier": tier, "prohibited_practices": banned, "obligations": obligations}


class AIActRegister:
    def __init__(self, ledger):
        self.ledger, self._db, self._lock = ledger, ledger._db, ledger._lock
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.commit()

    def latest(self, org_id: str, system_id: str | None = None) -> list[dict]:
        sql = """SELECT s.* FROM ai_act_systems s JOIN (SELECT system_id, MAX(version) v FROM ai_act_systems
                 WHERE org_id=? GROUP BY system_id) m ON s.system_id=m.system_id AND s.version=m.v WHERE s.org_id=?"""
        args: list[Any] = [org_id, org_id]
        if system_id:
            sql += " AND s.system_id=?"
            args.append(system_id)
        rows = self._db.execute(sql + " ORDER BY s.system_id", args).fetchall()
        out = []
        for r in rows:
            rec = json.loads(r["record"])
            out.append({"system_id": r["system_id"], "version": r["version"], "record_hash": r["record_hash"],
                        "saved_at": r["saved_at"], "record": rec, "classification": classify(rec)})
        return out

    def upsert(self, org_id: str, actor: str, system: dict, merge: bool = True) -> dict:
        s = validate(system)
        prev = self.latest(org_id, s["system_id"])
        base = prev[0]["record"] if prev and merge else {}
        record = {**base, **s}
        for k in ("controls", "prohibited_screen"):
            if merge and k in s and k in base:
                record[k] = {**base[k], **s[k]}
        h = hashlib.sha256(canon(record).encode()).hexdigest()
        if prev and prev[0]["record_hash"] == h:
            return {"system_id": s["system_id"], "version": prev[0]["version"], "changed": False, "record_hash": h,
                    "classification": classify(record)}
        version = prev[0]["version"] + 1 if prev else 1
        with self._lock:
            self._db.execute("INSERT INTO ai_act_systems VALUES (?,?,?,?,?,?)",
                             (org_id, s["system_id"], version, canon(record), h, _now().isoformat(timespec="seconds")))
            self._db.commit()
        changed = sorted(k for k in record if not prev or prev[0]["record"].get(k) != record.get(k))
        cls = classify(record)
        entry = self.ledger.record(org_id, "ai-act", actor, "data_change",
                                   f"{'Updated' if prev else 'Registered'} AI system {s['system_id']} (v{version}, {cls['tier']})",
                                   f"ai-system:{s['system_id']}", "success",
                                   {"system_id": s["system_id"], "version": version, "record_hash": h,
                                    "tier": cls["tier"], "changed_fields": changed})
        return {"system_id": s["system_id"], "version": version, "changed": True, "record_hash": h,
                "changed_fields": changed, "classification": cls, "log_entry_hash": entry["entry_hash"]}

    def check(self, org_id: str, today: date | None = None) -> dict:
        today = today or _now().date()
        soon = today + timedelta(days=180)
        since = (_now() - timedelta(days=30)).isoformat(timespec="seconds")
        findings: list[dict] = []
        systems = [s for s in self.latest(org_id) if not s["record"].get("retired")]
        tiers: dict[str, int] = {}
        for s in systems:
            r, sid, cls = s["record"], s["system_id"], s["classification"]
            tiers[cls["tier"]] = tiers.get(cls["tier"], 0) + 1
            if not r.get("role"):
                findings.append({"system_id": sid, "severity": "medium", "finding": "role not set (provider or deployer)"})
            screen = r.get("prohibited_screen") or {}
            for p in cls["prohibited_practices"]:
                in_force = today >= (NEW_PROHIBITIONS if p == "non_consensual_intimate_imagery" else LITERACY)
                findings.append({"system_id": sid, "severity": "critical" if in_force else "medium",
                                 "finding": f"prohibited practice (Art. 5): {PROHIBITED[p]}"})
            missing = [p for p in PROHIBITED if p not in screen]
            if missing:
                findings.append({"system_id": sid, "severity": "medium",
                                 "finding": f"Article 5 screen incomplete ({len(missing)} practice(s) not answered)"})
            if cls["tier"] == "annex_iii_not_high_risk":
                findings.append({"system_id": sid, "severity": "low",
                                 "finding": "Art. 6(3) not-high-risk assessment documented; keep it and register as required"})
            controls = r.get("controls") or {}
            for ob in cls["obligations"]:
                c, starts = controls.get(ob["id"]), D(ob["applies_from"])
                label = f"{ob['article']} {ob['title']}"
                if c and c.get("done"):
                    if not c.get("evidence"):
                        findings.append({"system_id": sid, "severity": "low", "finding": f"no evidence recorded: {label}"})
                    continue
                if starts <= today:
                    findings.append({"system_id": sid, "severity": "critical", "finding": f"in force, not met: {label}"})
                elif starts <= soon:
                    findings.append({"system_id": sid, "severity": "medium",
                                     "finding": f"due {ob['applies_from']}, not met: {label}"})
                else:
                    findings.append({"system_id": sid, "severity": "upcoming",
                                     "finding": f"applies from {ob['applies_from']}: {label}"})
            if cls["tier"] == "high_risk":
                streams = r.get("log_streams") or []
                if not streams:
                    findings.append({"system_id": sid, "severity": "medium",
                                     "finding": "no Privi Ledger log linked (log_streams) for Art. 12 / 26(6) record-keeping"})
                for st in streams:
                    n = self._db.execute("SELECT COUNT(*) FROM entries WHERE org_id=? AND stream_id=? AND recorded_at>=?",
                                         (org_id, st, since)).fetchone()[0]
                    if n == 0:
                        findings.append({"system_id": sid, "severity": "medium",
                                         "finding": f"linked log '{st}' has no activity in the last 30 days"})
        counts = {k: sum(1 for f in findings if f["severity"] == k) for k in ("critical", "medium", "low", "upcoming")}
        return {"systems": len(systems), "tiers": tiers, "as_of": today.isoformat(),
                "compliant_today": counts["critical"] == 0,
                "ready_for_next_180_days": counts["critical"] == 0 and counts["medium"] == 0,
                "finding_counts": counts, "findings": findings, "disclaimer": DISCLAIMER}

    def register_doc(self, org_id: str, org_name: str) -> dict:
        systems = []
        for s in self.latest(org_id):
            if s["record"].get("retired"):
                continue
            r, cls = s["record"], s["classification"]
            controls = r.get("controls") or {}
            systems.append({
                "system_id": s["system_id"], "version": s["version"], "record_hash": s["record_hash"],
                "name": r.get("name", ""), "role": r.get("role", ""), "intended_purpose": r.get("intended_purpose", ""),
                "tier": cls["tier"], "annex_iii_area": r.get("annex_iii_area", ""),
                "obligations": [{**ob, "met": bool((controls.get(ob["id"]) or {}).get("done"))} for ob in cls["obligations"]],
            })
        return {"type": "privi.ai_act_register", "version": 1, "organization": {"org_id": org_id, "name": org_name},
                "regulation": "Regulation (EU) 2024/1689 as amended by Regulation (EU) 2026/1744",
                "systems": systems, "disclaimer": DISCLAIMER}

    def save_export(self, org_id: str, h: str, n: int, attestation: dict) -> None:
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO ai_act_exports VALUES (?,?,?,?,?)",
                             (h, org_id, n, json.dumps(attestation), _now().isoformat(timespec="seconds")))
            self._db.commit()

    def find_export(self, h: str) -> dict | None:
        r = self._db.execute("SELECT * FROM ai_act_exports WHERE export_hash=?", (h,)).fetchone()
        if not r:
            return None
        return {"org_id": r["org_id"], "systems": r["systems"], "created_at": r["created_at"],
                "attestation": json.loads(r["attestation"])}
