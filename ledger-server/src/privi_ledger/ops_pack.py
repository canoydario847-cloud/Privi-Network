"""Privi Ops Pack: five everyday records a company has to keep, each written to its tamper-evident log.

- Trust Page      a public page a company shares with buyers: its claims (with evidence fingerprints) and live log health
- Incident Clock  an incident record with the notification deadlines that start running the moment you know
- Policy Sign-off who acknowledged which exact version of a policy
- Control Calendar recurring controls (backups tested, access reviewed) with evidence and what is overdue
- Release Seal    a software release's file fingerprints, sealed so customers can check what they downloaded

Privi stores fingerprints (SHA-256), never the documents or files themselves.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS ops_trust_pages (
    slug TEXT PRIMARY KEY, org_id TEXT NOT NULL UNIQUE, body TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ops_incidents (
    incident_id TEXT PRIMARY KEY, org_id TEXT NOT NULL, body TEXT NOT NULL, status TEXT NOT NULL,
    opened_at TEXT NOT NULL, closed_at TEXT, seal TEXT);
CREATE TABLE IF NOT EXISTS ops_policies (
    org_id TEXT NOT NULL, policy_id TEXT NOT NULL, version INTEGER NOT NULL, title TEXT NOT NULL,
    document_sha256 TEXT NOT NULL, published_at TEXT NOT NULL, PRIMARY KEY (org_id, policy_id, version));
CREATE TABLE IF NOT EXISTS ops_policy_acks (
    org_id TEXT NOT NULL, policy_id TEXT NOT NULL, version INTEGER NOT NULL, person TEXT NOT NULL,
    acked_at TEXT NOT NULL, entry_hash TEXT NOT NULL, PRIMARY KEY (org_id, policy_id, version, person));
CREATE TABLE IF NOT EXISTS ops_controls (
    org_id TEXT NOT NULL, control_id TEXT NOT NULL, title TEXT NOT NULL, every_days INTEGER NOT NULL,
    owner TEXT NOT NULL, reference TEXT NOT NULL, created_at TEXT NOT NULL, retired INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (org_id, control_id));
CREATE TABLE IF NOT EXISTS ops_control_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT, org_id TEXT NOT NULL, control_id TEXT NOT NULL, performed_by TEXT NOT NULL,
    document_sha256 TEXT NOT NULL, note TEXT NOT NULL, performed_at TEXT NOT NULL, entry_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ops_releases (
    release_hash TEXT PRIMARY KEY, org_id TEXT NOT NULL, product TEXT NOT NULL, version TEXT NOT NULL,
    body TEXT NOT NULL, attestation TEXT NOT NULL, sealed_at TEXT NOT NULL, UNIQUE (org_id, product, version));
CREATE TABLE IF NOT EXISTS ops_release_files (
    sha256 TEXT NOT NULL, release_hash TEXT NOT NULL, name TEXT NOT NULL, PRIMARY KEY (sha256, release_hash));
"""

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,39}$")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
SEVERITIES = ("low", "medium", "high", "critical")

# Notification clocks. "from" is the moment the clock starts: when you became aware of the incident, or (SEC) when
# you decided it was material. Hours are calendar hours unless business_days is set.
REGIMES: dict[str, dict[str, Any]] = {
    "gdpr": {"name": "EU GDPR Article 33 (personal data breach)", "from": "aware_at", "steps": [
        {"key": "authority_notification", "label": "Notify the supervisory authority", "hours": 72}]},
    "nis2": {"name": "EU NIS2 Article 23 (significant incident)", "from": "aware_at", "steps": [
        {"key": "early_warning", "label": "Early warning to the CSIRT or authority", "hours": 24},
        {"key": "incident_notification", "label": "Incident notification", "hours": 72},
        {"key": "final_report", "label": "Final report (one month after the incident notification)", "hours": 72 + 30 * 24}]},
    "sec_8k": {"name": "US SEC Form 8-K Item 1.05 (material cybersecurity incident)", "from": "material_at", "steps": [
        {"key": "form_8k", "label": "File Form 8-K Item 1.05", "business_days": 4}]},
}


class OpsError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).isoformat(timespec="seconds")


def _parse(value: str | None, what: str) -> datetime:
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        raise OpsError(f"{what} must be an ISO 8601 date-time, e.g. 2026-11-13T14:30:00Z") from None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _hex(value: Any, what: str) -> str:
    v = str(value or "").strip().lower()
    if not HEX64.match(v):
        raise OpsError(f"{what} must be a SHA-256 fingerprint (64 hex characters)")
    return v


def _text(value: Any, what: str, lo: int, hi: int) -> str:
    v = str(value or "").strip()
    if not lo <= len(v) <= hi:
        raise OpsError(f"{what} must be {lo}-{hi} characters")
    return v


def _ident(value: Any, what: str) -> str:
    v = str(value or "").strip()
    if not ID_RE.match(v):
        raise OpsError(f"{what} must be 1-64 letters, digits, dot, dash or underscore")
    return v


def add_business_days(start: datetime, days: int) -> datetime:
    """Weekends are skipped; public holidays are not known here and must be added by the filer."""
    d = start
    while days > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            days -= 1
    return d


class OpsPack:
    def __init__(self, ledger, public_url: str):
        self.ledger, self._db, self._lock, self.public_url = ledger, ledger._db, ledger._lock, public_url
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.commit()

    def _org_name(self, org_id: str) -> str:
        r = self._db.execute("SELECT name FROM orgs WHERE org_id=?", (org_id,)).fetchone()
        return r["name"] if r else ""

    def _log(self, org_id: str, stream: str, actor: str, kind: str, summary: str, resource: str, details: dict) -> str:
        e = self.ledger.record(org_id, stream, actor, kind, summary, resource, "success", details)
        return (e.get("entry_hash") if isinstance(e, dict) else getattr(e, "entry_hash", "")) or ""

    # ---- 1. Trust Page ---------------------------------------------------

    def trust_publish(self, org_id: str, slug: str, headline: str, claims: list[dict], contact: str = "") -> dict:
        slug = str(slug or "").strip().lower()
        if not SLUG_RE.match(slug):
            raise OpsError("slug must be 3-40 lowercase letters, digits or dashes, e.g. acme-tooling")
        headline = _text(headline, "headline", 3, 200)
        if not isinstance(claims, list) or len(claims) > 25:
            raise OpsError("claims must be a list of up to 25 items")
        clean = []
        for c in claims:
            if not isinstance(c, dict):
                raise OpsError('each claim must be like {"label": "ISO 9001 certified", "document_sha256": "<64 hex>"}')
            item = {"label": _text(c.get("label"), "claim label", 2, 160)}
            if c.get("document_sha256"):
                item["document_sha256"] = _hex(c["document_sha256"], "document_sha256")
            if c.get("valid_until"):
                item["valid_until"] = _iso(_parse(c["valid_until"], "valid_until"))
            clean.append(item)
        body = {"headline": headline, "claims": clean, "contact": str(contact or "").strip()[:200]}
        with self._lock:
            taken = self._db.execute("SELECT org_id FROM ops_trust_pages WHERE slug=?", (slug,)).fetchone()
            if taken and taken["org_id"] != org_id:
                raise OpsError("that slug is already used by another company")
            self._db.execute("DELETE FROM ops_trust_pages WHERE org_id=?", (org_id,))
            self._db.execute("INSERT INTO ops_trust_pages VALUES (?,?,?,?)", (slug, org_id, canon(body), _iso(_now())))
            self._db.commit()
        self._log(org_id, "trust-page", "Privi Ledger", "data_change", f"Published trust page /trust/{slug}", slug,
                  {"claims": len(clean), "page_hash": _sha(canon(body))})
        return self.trust_view(slug)

    def trust_view(self, slug: str) -> dict | None:
        r = self._db.execute("SELECT * FROM ops_trust_pages WHERE slug=?", (str(slug or "").lower(),)).fetchone()
        if not r:
            return None
        body, now, logs = json.loads(r["body"]), _now(), []
        for s in self.ledger.streams(r["org_id"]):
            sid = s["stream_id"]
            a = self.ledger.audit(r["org_id"], sid) or {}
            logs.append({"stream_id": sid, "entries": a.get("entry_count", 0), "intact": bool(a.get("intact"))})
        for c in body["claims"]:
            c["expired"] = bool(c.get("valid_until")) and _parse(c["valid_until"], "valid_until") < now
        return {"slug": r["slug"], "company": self._org_name(r["org_id"]), "org_id": r["org_id"], **body,
                "logs": {"streams": len(logs), "entries": sum(x["entries"] for x in logs),
                         "all_intact": all(x["intact"] for x in logs) if logs else None},
                "updated_at": r["updated_at"], "checked_at": _iso(now),
                "url": f"{self.public_url}/trust/{r['slug']}",
                "how_to_check": "Ask the company for a document, hash it with SHA-256 and compare it with the "
                                "fingerprint next to the claim. Log health is recomputed on every view."}

    # ---- 2. Incident Clock -----------------------------------------------

    def _clocks(self, body: dict, now: datetime) -> list[dict]:
        out = []
        for key in body["regimes"]:
            reg = REGIMES[key]
            start_raw = body.get(reg["from"])
            for step in reg["steps"]:
                row = {"regime": key, "rule": reg["name"], "step": step["key"], "label": step["label"]}
                done = body["done"].get(f"{key}.{step['key']}")
                if not start_raw:
                    row.update(status="not_started", reason=f"set {reg['from']} to start this clock")
                else:
                    start = _parse(start_raw, reg["from"])
                    due = (add_business_days(start, step["business_days"]) if "business_days" in step
                           else start + timedelta(hours=step["hours"]))
                    row["due_at"] = _iso(due)
                    if done:
                        row.update(status="done_late" if _parse(done["at"], "at") > due else "done", done=done)
                    else:
                        left = (due - now).total_seconds() / 3600
                        row.update(status="overdue" if left < 0 else "running", hours_left=round(left, 1))
                out.append(row)
        if body.get("contract_hours") and "contract.notify" not in body["done"]:
            due = _parse(body["aware_at"], "aware_at") + timedelta(hours=body["contract_hours"])
            left = (due - now).total_seconds() / 3600
            out.append({"regime": "contract", "rule": "Customer contract", "step": "notify", "label": "Notify customers",
                        "due_at": _iso(due), "status": "overdue" if left < 0 else "running", "hours_left": round(left, 1)})
        elif body.get("contract_hours"):
            due = _parse(body["aware_at"], "aware_at") + timedelta(hours=body["contract_hours"])
            d = body["done"]["contract.notify"]
            out.append({"regime": "contract", "rule": "Customer contract", "step": "notify", "label": "Notify customers",
                        "due_at": _iso(due), "status": "done_late" if _parse(d["at"], "at") > due else "done", "done": d})
        return out

    def incident_open(self, org_id: str, actor: str, title: str, severity: str, aware_at: str | None = None,
                      regimes: list[str] | None = None, material_at: str | None = None,
                      contract_hours: int | None = None) -> dict:
        title = _text(title, "title", 3, 200)
        if severity not in SEVERITIES:
            raise OpsError("severity must be one of: " + ", ".join(SEVERITIES))
        regimes = list(dict.fromkeys(regimes or []))
        if bad := [r for r in regimes if r not in REGIMES]:
            raise OpsError(f"unknown regime(s) {bad}; choose from: " + ", ".join(REGIMES))
        if contract_hours is not None and not (isinstance(contract_hours, int) and 1 <= contract_hours <= 8760):
            raise OpsError("contract_hours must be 1-8760")
        now = _now()
        body = {"title": title, "severity": severity, "aware_at": _iso(_parse(aware_at, "aware_at") if aware_at else now),
                "material_at": _iso(_parse(material_at, "material_at")) if material_at else None,
                "regimes": regimes, "contract_hours": contract_hours, "done": {}, "timeline": []}
        iid = "inc_" + secrets.token_hex(6)
        with self._lock:
            self._db.execute("INSERT INTO ops_incidents VALUES (?,?,?,?,?,NULL,NULL)",
                             (iid, org_id, canon(body), "open", _iso(now)))
            self._db.commit()
        self._log(org_id, "incidents", actor, "other", f"Incident {iid} opened: {title}", iid,
                  {"severity": severity, "regimes": regimes, "aware_at": body["aware_at"]})
        return self.incident(org_id, iid)

    def _incident_row(self, org_id: str, iid: str):
        r = self._db.execute("SELECT * FROM ops_incidents WHERE incident_id=? AND org_id=?", (iid, org_id)).fetchone()
        if not r:
            raise OpsError("no such incident in your organization")
        return r

    def incident(self, org_id: str, iid: str) -> dict:
        r = self._incident_row(org_id, iid)
        body = json.loads(r["body"])
        end = _parse(r["closed_at"], "closed_at") if r["closed_at"] else _now()
        clocks = self._clocks(body, end)
        return {"incident_id": iid, "status": r["status"], "opened_at": r["opened_at"], "closed_at": r["closed_at"],
                **{k: body[k] for k in ("title", "severity", "aware_at", "material_at", "timeline")},
                "clocks": clocks, "overdue": [c["step"] for c in clocks if c["status"] == "overdue"],
                "seal": json.loads(r["seal"]) if r["seal"] else None,
                "note": "Deadlines follow the rule text; business days skip weekends only. Confirm what applies to "
                        "you with counsel. This is a record-keeping tool, not legal advice."}

    def incident_update(self, org_id: str, iid: str, actor: str, note: str, completed_step: str | None = None,
                        material_at: str | None = None) -> dict:
        r = self._incident_row(org_id, iid)
        if r["status"] != "open":
            raise OpsError("incident is closed")
        body, now = json.loads(r["body"]), _iso(_now())
        note = _text(note, "note", 2, 2000)
        if material_at:
            body["material_at"] = _iso(_parse(material_at, "material_at"))
        if completed_step:
            valid = {f"{k}.{s['key']}" for k in body["regimes"] for s in REGIMES[k]["steps"]}
            if body.get("contract_hours"):
                valid.add("contract.notify")
            if completed_step not in valid:
                raise OpsError("completed_step must be one of: " + ", ".join(sorted(valid)))
            body["done"][completed_step] = {"at": now, "by": actor}
        h = self._log(org_id, "incidents", actor, "other", f"Incident {iid}: {note[:140]}", iid,
                      {"completed_step": completed_step, "material_at": body["material_at"]})
        body["timeline"].append({"at": now, "by": actor, "note": note, "completed_step": completed_step, "entry_hash": h})
        with self._lock:
            self._db.execute("UPDATE ops_incidents SET body=? WHERE incident_id=?", (canon(body), iid))
            self._db.commit()
        return self.incident(org_id, iid)

    def incident_close_doc(self, org_id: str, iid: str, actor: str, root_cause: str) -> tuple[dict, str]:
        r = self._incident_row(org_id, iid)
        if r["status"] != "open":
            raise OpsError("incident is already closed")
        now = _now()
        body = json.loads(r["body"])
        doc = {"incident_id": iid, "company": self._org_name(org_id), "org_id": org_id, "opened_at": r["opened_at"],
               "closed_at": _iso(now), "closed_by": actor, "root_cause": _text(root_cause, "root_cause", 3, 4000),
               **{k: body[k] for k in ("title", "severity", "aware_at", "material_at", "timeline")},
               "clocks": self._clocks(body, now)}
        return doc, _sha(canon(doc))

    def incident_store_close(self, org_id: str, doc: dict, doc_hash: str, attestation: dict) -> dict:
        seal = {"report_hash": doc_hash, "attestation": attestation}
        with self._lock:
            self._db.execute("UPDATE ops_incidents SET status='closed', closed_at=?, seal=? WHERE incident_id=?",
                             (doc["closed_at"], canon(seal), doc["incident_id"]))
            self._db.commit()
        self._log(org_id, "incidents", doc["closed_by"], "other", f"Incident {doc['incident_id']} closed and sealed",
                  doc["incident_id"], {"report_hash": doc_hash, "anchored": attestation.get("anchored")})
        return {"report_json": canon(doc), **seal, "incident": self.incident(org_id, doc["incident_id"])}

    def incidents(self, org_id: str) -> list[dict]:
        rows = self._db.execute("SELECT incident_id FROM ops_incidents WHERE org_id=? ORDER BY opened_at DESC LIMIT 100",
                                (org_id,)).fetchall()
        out = []
        for r in rows:
            i = self.incident(org_id, r["incident_id"])
            out.append({k: i[k] for k in ("incident_id", "title", "severity", "status", "opened_at", "overdue")})
        return out

    # ---- 3. Policy Sign-off ----------------------------------------------

    def policy_publish(self, org_id: str, actor: str, policy_id: str, title: str, document_sha256: str) -> dict:
        policy_id, title = _ident(policy_id, "policy_id"), _text(title, "title", 3, 200)
        sha = _hex(document_sha256, "document_sha256")
        with self._lock:
            last = self._db.execute("SELECT version, document_sha256 FROM ops_policies WHERE org_id=? AND policy_id=? "
                                    "ORDER BY version DESC LIMIT 1", (org_id, policy_id)).fetchone()
            if last and last["document_sha256"] == sha:
                raise OpsError(f"version {last['version']} already has this exact document")
            version = (last["version"] if last else 0) + 1
            self._db.execute("INSERT INTO ops_policies VALUES (?,?,?,?,?,?)",
                             (org_id, policy_id, version, title, sha, _iso(_now())))
            self._db.commit()
        self._log(org_id, "policies", actor, "data_change", f"Policy {policy_id} v{version} published: {title}",
                  policy_id, {"version": version, "document_sha256": sha})
        return {"policy_id": policy_id, "version": version, "title": title, "document_sha256": sha,
                "next": "Each person calls policy_acknowledge; earlier versions' sign-offs do not carry over."}

    def _policy(self, org_id: str, policy_id: str):
        r = self._db.execute("SELECT * FROM ops_policies WHERE org_id=? AND policy_id=? ORDER BY version DESC LIMIT 1",
                             (org_id, policy_id)).fetchone()
        if not r:
            raise OpsError("no such policy; publish it first with policy_publish")
        return r

    def policy_acknowledge(self, org_id: str, policy_id: str, person: str, document_sha256: str) -> dict:
        p, person = self._policy(org_id, policy_id), _text(person, "person", 2, 200)
        if _hex(document_sha256, "document_sha256") != p["document_sha256"]:
            raise OpsError(f"that fingerprint is not the current version (v{p['version']}); the person must read "
                           "and acknowledge the current document")
        if self._db.execute("SELECT 1 FROM ops_policy_acks WHERE org_id=? AND policy_id=? AND version=? AND person=?",
                            (org_id, policy_id, p["version"], person)).fetchone():
            raise OpsError(f"{person} already acknowledged v{p['version']}")
        h = self._log(org_id, "policies", person, "approval",
                      f"{person} acknowledged policy {policy_id} v{p['version']}", policy_id,
                      {"version": p["version"], "document_sha256": p["document_sha256"]})
        now = _iso(_now())
        with self._lock:
            self._db.execute("INSERT INTO ops_policy_acks VALUES (?,?,?,?,?,?)",
                             (org_id, policy_id, p["version"], person, now, h))
            self._db.commit()
        return {"policy_id": policy_id, "version": p["version"], "person": person, "acknowledged_at": now, "entry_hash": h}

    def policy_status(self, org_id: str, policy_id: str, required_people: list[str] | None = None) -> dict:
        p = self._policy(org_id, policy_id)
        acks = [dict(r) for r in self._db.execute(
            "SELECT person, acked_at, entry_hash FROM ops_policy_acks WHERE org_id=? AND policy_id=? AND version=? "
            "ORDER BY acked_at", (org_id, policy_id, p["version"]))]
        signed = {a["person"] for a in acks}
        need = [str(x).strip() for x in (required_people or []) if str(x).strip()]
        missing = [x for x in need if x not in signed]
        return {"policy_id": policy_id, "title": p["title"], "version": p["version"],
                "document_sha256": p["document_sha256"], "published_at": p["published_at"],
                "acknowledged": acks, "missing": missing, "complete": (not missing) if need else None}

    # ---- 4. Control Calendar ---------------------------------------------

    def control_save(self, org_id: str, actor: str, control_id: str, title: str, every_days: int, owner: str,
                     reference: str = "", retired: bool = False) -> dict:
        control_id, title = _ident(control_id, "control_id"), _text(title, "title", 3, 200)
        if not isinstance(every_days, int) or not 1 <= every_days <= 1100:
            raise OpsError("every_days must be 1-1100 (e.g. 90 for quarterly, 365 for yearly)")
        owner = _text(owner, "owner", 2, 200)
        with self._lock:
            old = self._db.execute("SELECT created_at FROM ops_controls WHERE org_id=? AND control_id=?",
                                   (org_id, control_id)).fetchone()
            self._db.execute("INSERT OR REPLACE INTO ops_controls VALUES (?,?,?,?,?,?,?,?)",
                             (org_id, control_id, title, every_days, owner, str(reference or "")[:200],
                              old["created_at"] if old else _iso(_now()), int(bool(retired))))
            self._db.commit()
        self._log(org_id, "controls", actor, "data_change", f"Control {control_id} saved: {title}", control_id,
                  {"every_days": every_days, "owner": owner, "retired": bool(retired)})
        return next(c for c in self.controls_due(org_id, include_retired=True)["controls"] if c["control_id"] == control_id)

    def control_evidence(self, org_id: str, control_id: str, performed_by: str, document_sha256: str,
                         note: str = "", performed_at: str | None = None) -> dict:
        control_id = _ident(control_id, "control_id")
        if not self._db.execute("SELECT 1 FROM ops_controls WHERE org_id=? AND control_id=?",
                                (org_id, control_id)).fetchone():
            raise OpsError("no such control; add it first with control_save")
        performed_by, sha = _text(performed_by, "performed_by", 2, 200), _hex(document_sha256, "document_sha256")
        when = _parse(performed_at, "performed_at") if performed_at else _now()
        if when > _now() + timedelta(minutes=5):
            raise OpsError("performed_at cannot be in the future")
        h = self._log(org_id, "controls", performed_by, "other", f"Control {control_id} performed", control_id,
                      {"document_sha256": sha, "performed_at": _iso(when), "note": str(note or "")[:500]})
        with self._lock:
            self._db.execute("INSERT INTO ops_control_evidence (org_id, control_id, performed_by, document_sha256, note,"
                             " performed_at, entry_hash) VALUES (?,?,?,?,?,?,?)",
                             (org_id, control_id, performed_by, sha, str(note or "")[:500], _iso(when), h))
            self._db.commit()
        return {"control_id": control_id, "performed_at": _iso(when), "performed_by": performed_by,
                "document_sha256": sha, "entry_hash": h}

    def controls_due(self, org_id: str, soon_days: int = 14, include_retired: bool = False) -> dict:
        now, out = _now(), []
        for c in self._db.execute("SELECT * FROM ops_controls WHERE org_id=? ORDER BY control_id", (org_id,)):
            if c["retired"] and not include_retired:
                continue
            last = self._db.execute("SELECT performed_at, performed_by, document_sha256, entry_hash FROM "
                                    "ops_control_evidence WHERE org_id=? AND control_id=? ORDER BY performed_at DESC "
                                    "LIMIT 1", (org_id, c["control_id"])).fetchone()
            base = _parse(last["performed_at"] if last else c["created_at"], "date")
            due = base + timedelta(days=c["every_days"] if last else 0)
            days = (due - now).total_seconds() / 86400
            status = ("retired" if c["retired"] else "never_done" if not last else "overdue" if days < 0
                      else "due_soon" if days <= soon_days else "ok")
            out.append({"control_id": c["control_id"], "title": c["title"], "owner": c["owner"],
                        "reference": c["reference"], "every_days": c["every_days"], "status": status,
                        "due_at": _iso(due), "last": dict(last) if last else None})
        counts = {s: sum(1 for c in out if c["status"] == s) for s in ("overdue", "never_done", "due_soon", "ok")}
        return {"as_of": _iso(now), "counts": counts, "all_current": counts["overdue"] + counts["never_done"] == 0,
                "controls": out}

    # ---- 5. Release Seal --------------------------------------------------

    def release_doc(self, org_id: str, actor: str, product: str, version: str, files: list[dict],
                    commit: str = "", sbom_sha256: str = "") -> tuple[dict, str]:
        product, version = _text(product, "product", 2, 100), _ident(version, "version")
        if not isinstance(files, list) or not 1 <= len(files) <= 200:
            raise OpsError("files must list 1-200 release files")
        clean, seen = [], set()
        for f in files:
            if not isinstance(f, dict):
                raise OpsError('each file must be like {"name": "app-1.2.0.zip", "sha256": "<64 hex>"}')
            name, sha = _text(f.get("name"), "file name", 1, 200), _hex(f.get("sha256"), "file sha256")
            if name in seen:
                raise OpsError(f"file name '{name}' is listed twice")
            seen.add(name)
            clean.append({"name": name, "sha256": sha})
        if self._db.execute("SELECT 1 FROM ops_releases WHERE org_id=? AND product=? AND version=?",
                            (org_id, product, version)).fetchone():
            raise OpsError(f"{product} {version} is already sealed; a sealed release cannot be changed, publish a new version")
        doc = {"company": self._org_name(org_id), "org_id": org_id, "product": product, "version": version,
               "files": sorted(clean, key=lambda x: x["name"]), "commit": str(commit or "").strip()[:80],
               "sbom_sha256": _hex(sbom_sha256, "sbom_sha256") if sbom_sha256 else "", "sealed_by": actor,
               "sealed_at": _iso(_now())}
        return doc, _sha(canon(doc))

    def release_store(self, doc: dict, release_hash: str, attestation: dict) -> dict:
        with self._lock:
            self._db.execute("INSERT INTO ops_releases VALUES (?,?,?,?,?,?,?)",
                             (release_hash, doc["org_id"], doc["product"], doc["version"], canon(doc),
                              canon(attestation), doc["sealed_at"]))
            self._db.executemany("INSERT OR IGNORE INTO ops_release_files VALUES (?,?,?)",
                                 [(f["sha256"], release_hash, f["name"]) for f in doc["files"]])
            self._db.commit()
        self._log(doc["org_id"], "releases", doc["sealed_by"], "data_change",
                  f"Release sealed: {doc['product']} {doc['version']}", release_hash,
                  {"files": len(doc["files"]), "anchored": attestation.get("anchored")})
        return {"release_hash": release_hash, "release": doc, "attestation": attestation,
                "verify_url": f"{self.public_url}/releases/check/<sha256 of any release file>"}

    def release_check(self, file_sha256: str) -> dict:
        sha = _hex(file_sha256, "file_sha256")
        rows = self._db.execute("SELECT f.name, r.* FROM ops_release_files f JOIN ops_releases r "
                                "ON r.release_hash=f.release_hash WHERE f.sha256=? ORDER BY r.sealed_at", (sha,)).fetchall()
        if not rows:
            return {"genuine": False, "file_sha256": sha,
                    "reason": "no sealed release contains a file with this fingerprint; it may be altered or unofficial"}
        return {"genuine": True, "file_sha256": sha, "releases": [
            {"file_name": r["name"], "release_hash": r["release_hash"], "sealed_at": r["sealed_at"],
             **{k: json.loads(r["body"])[k] for k in ("company", "product", "version", "commit")},
             "attestation": json.loads(r["attestation"])} for r in rows]}


def trust_html(page: dict) -> str:
    e = html.escape
    rows = "".join(
        f"<li><b>{e(c['label'])}</b>{' <em>(expired)</em>' if c.get('expired') else ''}"
        + (f"<br><code>{e(c['document_sha256'])}</code>" if c.get("document_sha256") else "") + "</li>"
        for c in page["claims"]) or "<li>No claims published yet.</li>"
    logs = page["logs"]
    health = ("No activity logs yet" if logs["all_intact"] is None else
              f"{logs['entries']} log entries in {logs['streams']} stream(s): "
              + ("all intact" if logs["all_intact"] else "INTEGRITY PROBLEM FOUND"))
    return (f"<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content='width=device-width,"
            f"initial-scale=1'><title>{e(page['company'])} trust page</title><style>body{{font:16px/1.5 system-ui,"
            f"sans-serif;max-width:680px;margin:40px auto;padding:0 16px;color:#111}}code{{font-size:12px;"
            f"word-break:break-all;color:#555}}li{{margin:10px 0}}footer{{margin-top:32px;color:#666;font-size:13px}}"
            f"</style><h1>{e(page['company'])}</h1><p>{e(page['headline'])}</p><h2>Claims</h2><ul>{rows}</ul>"
            f"<h2>Record keeping</h2><p>{e(health)} (checked {e(page['checked_at'])})</p>"
            + (f"<p>Contact: {e(page['contact'])}</p>" if page["contact"] else "")
            + f"<footer>{e(page['how_to_check'])} Published with Privi Ledger.</footer></html>")
