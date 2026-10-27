# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Quantum - https://priviflow.us - dariocanoy@priviflow.us
"""Privi Inspector: the checkpoint in front of the Privi quantum realm.

Every call into Dream Weaver and Dream Scape (MCP tools and the WebSocket) must carry a Privi pass.
An agent gets a pass by signing `privi-inspector:v1:<agent_id>:<unix seconds>:<nonce>` with the ML-DSA
key it enrolled in the Quantum Agent Accelerator. The Inspector intercepts the request when:

  no_credential        no pass and no signed credential
  unknown_agent        the agent never enrolled
  revoked              Privi revoked the agent
  bad_signature        the signature does not match the enrolled key
  stale_timestamp      the signed time is more than 5 minutes off
  replayed_nonce       the nonce was already used
  no_certificate       the agent has no Quantum Agent certificate yet
  certificate_outdated the certificate expired or was issued under an older policy
  level_too_low        the agent is below the level the realm requires
  weak_key             the agent's ML-DSA parameter set is below the realm's minimum
  pass_invalid         the pass is unknown or expired

Every decision is logged. Modes: enforce (block), report (allow but log what would be blocked), off.
Other services use the same checks through inspector_check or POST /inspector/check.

The Inspector also hunts inside Privi: a patrol re-checks every enrolled agent on a schedule and keeps a
public watchlist of agents that are revoked, outdated, expiring, never certified, or being impersonated
(repeated forged signatures against their id), so any service can block them before they act.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from .accelerator import LEVEL_LABEL, POLICY_VERSION, Accelerator, AcceleratorError
from .humans import GRADES, HumanRegistry, grade_parts

LEVELS = ["enrolled", "quantum_aware", "quantum_safe_identity", "quantum_agent", "quantum_agent_plus"]
KEYS = ["ML-DSA-44", "ML-DSA-65", "ML-DSA-87"]
MODES = ("enforce", "report", "off")
SKEW_S = 300
PASS_TTL_S = 3600
NONCE_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")

FIX = {
    "no_credential": "Get a Privi pass: sign 'privi-inspector:v1:<agent_id>:<unix seconds>:<nonce>' with your ML-DSA key "
                     "and call inspector_pass, then send privi_pass with each call.",
    "unknown_agent": "Enroll in the Quantum Agent Accelerator first: qagent_enroll.",
    "revoked": "This agent was revoked by Privi. Contact dariocanoy@priviflow.us.",
    "bad_signature": "Sign the exact credential message with the ML-DSA key you enrolled (empty context, base64).",
    "stale_timestamp": "Use the current unix time in seconds (within 5 minutes).",
    "replayed_nonce": "Use a new random nonce (16-64 letters, digits, _ or -) for every credential.",
    "bad_nonce": "nonce must be 16-64 letters, digits, _ or -.",
    "no_certificate": "Earn a certificate: complete Q1 (qagent_scan) or Q2 (qagent_challenge + qagent_prove).",
    "certificate_outdated": "Renew your certificate: qagent_challenge + qagent_prove.",
    "level_too_low": "Upgrade through the Quantum Agent Accelerator (accelerator_info shows the steps).",
    "weak_key": "Enroll a new agent with a stronger ML-DSA key.",
    "pass_invalid": "Your pass is unknown or expired; get a new one with inspector_pass.",
    "human_approval_required": "A real person must approve this agent with a passkey (Face ID, Touch ID or screen "
                               "lock): call qagent_human_request and send the link to the agent's human operator.",
    "id_verification_required": "The approving person must verify a government ID (Stripe Identity, with a live "
                                "selfie) from the approval page.",
    "grade_too_low": "Raise the agent's Privi grade: inspector_grade shows which factors are missing.",
}
GRADE_FLOOR = dict(GRADES)

SCHEMA = """
CREATE TABLE IF NOT EXISTS inspector_nonces (nonce TEXT PRIMARY KEY, agent_id TEXT NOT NULL, expires_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS inspector_passes (pass_hash TEXT PRIMARY KEY, agent_id TEXT NOT NULL, expires_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS inspector_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    agent_id TEXT NOT NULL DEFAULT '',
    scope TEXT NOT NULL,
    decision TEXT NOT NULL,          -- allowed | intercepted | would_intercept
    reasons TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_inspector_log_at ON inspector_log (at);
CREATE TABLE IF NOT EXISTS inspector_watch (
    agent_id   TEXT PRIMARY KEY,
    reasons    TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen  TEXT NOT NULL
);
"""
IMPERSONATION_THRESHOLD = 5      # forged signatures against one agent within an hour
STALE_ENROLLMENT_DAYS = 7        # enrolled this long with no certificate
EXPIRING_DAYS = 30


def credential_message(agent_id: str, ts: int, nonce: str) -> str:
    return f"privi-inspector:v1:{agent_id}:{int(ts)}:{nonce}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Inspector:
    def __init__(self, db_path: str, accel: Accelerator, mode: str = "enforce",
                 min_level: str = "quantum_safe_identity", min_key: str = "ML-DSA-44",
                 humans: HumanRegistry | None = None, require_human: bool = False, require_id: bool = False,
                 min_grade: str = "F"):
        if mode not in MODES:
            raise ValueError(f"INSPECTOR_MODE must be one of {', '.join(MODES)}")
        if min_level not in LEVELS:
            raise ValueError(f"INSPECTOR_MIN_LEVEL must be one of {', '.join(LEVELS)}")
        if min_key not in KEYS:
            raise ValueError(f"INSPECTOR_MIN_KEY must be one of {', '.join(KEYS)}")
        if min_grade not in GRADE_FLOOR:
            raise ValueError(f"INSPECTOR_MIN_GRADE must be one of {', '.join(GRADE_FLOOR)}")
        if (require_human or require_id) and humans is None:
            raise ValueError("human requirements need a HumanRegistry")
        self.accel, self.mode, self.min_level, self.min_key = accel, mode, min_level, min_key
        self.humans, self.require_human, self.require_id, self.min_grade = humans, require_human, require_id, min_grade
        self._lock = threading.Lock()
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.commit()

    def policy(self) -> dict:
        return {"mode": self.mode, "min_level": self.min_level, "min_level_label": LEVEL_LABEL[self.min_level],
                "min_key": self.min_key, "certificate_policy_version": POLICY_VERSION,
                "credential": "privi-inspector:v1:<agent_id>:<unix seconds>:<nonce>, signed with your enrolled ML-DSA key",
                "pass_minutes": PASS_TTL_S // 60, "max_clock_skew_seconds": SKEW_S,
                "requires_human_approval": self.require_human, "requires_id_verification": self.require_id,
                "min_grade": self.min_grade, "grades": GRADE_FLOOR}

    # ---------------- the checks ----------------

    def evaluate(self, agent_id: str, min_level: str | None = None) -> dict:
        """Everything about the agent itself (no signature): enrolled, not revoked, certified, current, level, key."""
        need = min_level or self.min_level
        try:
            a = self.accel._row(agent_id)
        except AcceleratorError:
            return self._verdict(agent_id, ["unknown_agent"], need)
        reasons = []
        if a.get("revoked_at"):
            reasons.append("revoked")
        cert = self.accel.certificate(a)
        if not cert:
            reasons.append("no_certificate")
        elif cert["policy_version"] < POLICY_VERSION or cert["valid_until"] <= _now_iso():
            reasons.append("certificate_outdated")
        if LEVELS.index(a["level"]) < LEVELS.index(need):
            reasons.append("level_too_low")
        if KEYS.index(a["key_alg"]) < KEYS.index(self.min_key):
            reasons.append("weak_key")
        trust = self.grade_row(a, cert)
        human = trust["human"]
        if self.require_human and not human.get("human_approved"):
            reasons.append("human_approval_required")
        if self.require_id and not (human.get("human_approved") and human.get("id_verified")):
            reasons.append("id_verification_required")
        if trust["score"] < GRADE_FLOOR[self.min_grade]:
            reasons.append("grade_too_low")
        v = self._verdict(agent_id, reasons, need, a, cert)
        v["impersonation_attempts_last_hour"] = trust["impersonation_attempts_last_hour"]
        v["trust"] = {k: trust[k] for k in ("score", "grade", "points", "penalties", "human")}
        if "grade_too_low" in reasons:
            v["fixes"][reasons.index("grade_too_low")] = (
                f"This realm requires grade {self.min_grade} or better; this agent is {trust['grade']} "
                f"({trust['score']}/100). " + FIX["grade_too_low"])
        return v

    # ---------------- the grade ----------------

    def grade_row(self, a: dict, cert: dict | None = None) -> dict:
        cert = cert if cert is not None else self.accel.certificate(a)
        cert_current = bool(cert) and cert["policy_version"] >= POLICY_VERSION and cert["valid_until"] > _now_iso()
        human = self.humans.public_factors(a["agent_id"], a["key_fingerprint"]) if self.humans else {}
        since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(timespec="seconds")
        forged_30d = self._db.execute("SELECT COUNT(*) FROM inspector_log WHERE agent_id=? AND at>=? AND reasons LIKE ?",
                                      (a["agent_id"], since, '%"bad_signature"%')).fetchone()[0]
        imp = self.impersonation_attempts(a["agent_id"])
        g = grade_parts(a["level"], a["key_alg"], cert_current, human, forged_30d == 0, bool(a.get("revoked_at")),
                        imp >= IMPERSONATION_THRESHOLD)
        return {**g, "human": human, "impersonation_attempts_last_hour": imp}

    def grade(self, agent_id: str) -> dict:
        try:
            a = self.accel._row(agent_id)
        except AcceleratorError:
            return {"agent_id": agent_id, "error": "unknown agent"}
        g = self.grade_row(a)
        g["missing"] = [k for k, v in g["points"].items() if not v]
        return {"agent_id": agent_id, "name": a["name"], "operator": a["operator"], **g,
                "scale": {"quantum_level": 35, "human_approval": 20, "id_verification": "25 (Stripe Identity) or 15 (manual)",
                          "certificate_current": 10, "key_strength": 5, "clean_record": 5},
                "realm_requires": {"grade": self.min_grade, "human_approval": self.require_human,
                                   "id_verification": self.require_id}}

    def _verdict(self, agent_id, reasons, need, a=None, cert=None) -> dict:
        out: dict[str, Any] = {"agent_id": agent_id, "allowed": not reasons, "reasons": reasons,
                               "fixes": [FIX[r] for r in reasons], "required_level": need,
                               "required_level_label": LEVEL_LABEL[need]}
        if a:
            out.update(name=a["name"], operator=a["operator"], level=a["level"], level_label=LEVEL_LABEL[a["level"]],
                       key_alg=a["key_alg"], certificate=cert,
                       revoke_reason=a.get("revoke_reason") or None if a.get("revoked_at") else None)
        if "level_too_low" in reasons and a:
            out["fixes"][reasons.index("level_too_low")] = (
                f"This realm requires {LEVEL_LABEL[need]}; you are {LEVEL_LABEL[a['level']]}. " + FIX["level_too_low"])
        return out

    def verify_credential(self, agent_id: str, ts: int, nonce: str, signature: str,
                          min_level: str | None = None, consume: bool = True) -> dict:
        need = min_level or self.min_level
        try:
            a = self.accel._row(agent_id)
        except AcceleratorError:
            return self._verdict(agent_id, ["unknown_agent"], need)
        pre = []
        if not NONCE_RE.match(nonce or ""):
            pre.append("bad_nonce")
        try:
            ts = int(ts)
        except (TypeError, ValueError):
            ts = 0
        if abs(time.time() - ts) > SKEW_S:
            pre.append("stale_timestamp")
        if not pre and not self.accel._verify(a, credential_message(agent_id, ts, nonce).encode(), signature):
            pre.append("bad_signature")
        if not pre and consume:
            with self._lock:
                self._db.execute("DELETE FROM inspector_nonces WHERE expires_at < ?", (time.time(),))
                try:
                    self._db.execute("INSERT INTO inspector_nonces VALUES (?,?,?)",
                                     (f"{agent_id}:{nonce}", agent_id, time.time() + 2 * SKEW_S))
                    self._db.commit()
                except sqlite3.IntegrityError:
                    pre.append("replayed_nonce")
        v = self.evaluate(agent_id, need)
        if pre:
            v["reasons"] = pre + v["reasons"]
            v["fixes"] = [FIX[r] for r in pre] + v["fixes"]
            v["allowed"] = False
        return v

    # ---------------- passes ----------------

    def issue_pass(self, agent_id: str, ts: int, nonce: str, signature: str) -> dict:
        v = self.verify_credential(agent_id, ts, nonce, signature)
        self.log(agent_id, "inspector_pass", v)
        if not v["allowed"]:
            return {**v, "intercepted": True}
        token = "ppass_" + secrets.token_urlsafe(24)
        exp = time.time() + PASS_TTL_S
        with self._lock:
            self._db.execute("DELETE FROM inspector_passes WHERE expires_at < ?", (time.time(),))
            self._db.execute("INSERT INTO inspector_passes VALUES (?,?,?)",
                             (hashlib.sha256(token.encode()).hexdigest(), agent_id, exp))
            self._db.commit()
        return {**v, "privi_pass": token,
                "expires_at": datetime.fromtimestamp(exp, timezone.utc).isoformat(timespec="seconds"),
                "use": "Send privi_pass with each quantum realm call (tool argument, header X-Privi-Pass, "
                       "or the WebSocket auth frame)."}

    def check_pass(self, token: str | None, scope: str) -> dict:
        """Gate one request. Returns the verdict; in report mode a failing verdict is allowed but logged."""
        if self.mode == "off":
            return {"allowed": True, "mode": "off"}
        agent_id = ""
        if not token:
            v = self._verdict("", ["no_credential"], self.min_level)
        else:
            r = self._db.execute("SELECT agent_id, expires_at FROM inspector_passes WHERE pass_hash=?",
                                 (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
            if not r or r["expires_at"] < time.time():
                v = self._verdict("", ["pass_invalid"], self.min_level)
            else:
                agent_id = r["agent_id"]
                v = self.evaluate(agent_id)          # revocation, expiry and level are checked live on every call
        self.log(agent_id or v.get("agent_id", ""), scope, v)
        if not v["allowed"] and self.mode == "report":
            return {**v, "allowed": True, "mode": "report", "would_intercept": True}
        return {**v, "mode": self.mode, "intercepted": not v["allowed"]}

    # ---------------- log ----------------

    def log(self, agent_id: str, scope: str, v: dict) -> None:
        decision = "allowed" if v["allowed"] else ("would_intercept" if self.mode == "report" else "intercepted")
        with self._lock:
            self._db.execute("INSERT INTO inspector_log (at, agent_id, scope, decision, reasons) VALUES (?,?,?,?,?)",
                             (_now_iso(), agent_id or "", scope[:60], decision, json.dumps(v.get("reasons", []))))
            self._db.execute("DELETE FROM inspector_log WHERE id <= (SELECT MAX(id) - 50000 FROM inspector_log)")
            self._db.commit()

    def report(self, hours: int = 24) -> dict:
        since = (datetime.now(timezone.utc) - timedelta(hours=max(1, min(hours, 720)))).isoformat(timespec="seconds")
        rows = self._db.execute("SELECT * FROM inspector_log WHERE at >= ? ORDER BY id DESC", (since,)).fetchall()
        by_decision: dict[str, int] = {}
        by_reason: dict[str, int] = {}
        for r in rows:
            by_decision[r["decision"]] = by_decision.get(r["decision"], 0) + 1
            for reason in json.loads(r["reasons"]):
                by_reason[reason] = by_reason.get(reason, 0) + 1
        recent = [{"at": r["at"], "agent_id": r["agent_id"] or None, "scope": r["scope"],
                   "decision": r["decision"], "reasons": json.loads(r["reasons"])}
                  for r in rows if r["decision"] != "allowed"][:25]
        return {"inspector": "Privi Inspector", "policy": self.policy(), "window_hours": hours,
                "inspections": len(rows), "by_decision": by_decision, "intercepts_by_reason": by_reason,
                "recent_intercepts": recent}

    # ---------------- the hunt: patrol + watchlist ----------------

    def impersonation_attempts(self, agent_id: str, hours: int = 1) -> int:
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")
        return self._db.execute("SELECT COUNT(*) FROM inspector_log WHERE agent_id=? AND at>=? AND reasons LIKE ?",
                                (agent_id, since, '%"bad_signature"%')).fetchone()[0]

    def sweep(self) -> dict:
        """Re-check every enrolled agent and rebuild the watchlist."""
        now = datetime.now(timezone.utc)
        now_s = now.isoformat(timespec="seconds")
        soon = (now + timedelta(days=EXPIRING_DAYS)).isoformat(timespec="seconds")
        stale = (now - timedelta(days=STALE_ENROLLMENT_DAYS)).isoformat(timespec="seconds")
        found: dict[str, list[str]] = {}
        agents = self.accel._db.execute("SELECT agent_id FROM qa_agents").fetchall()
        for r in agents:
            a = self.accel._row(r["agent_id"])
            reasons = []
            if a.get("revoked_at"):
                reasons.append("revoked")
            cert = self.accel.certificate(a)
            if not cert:
                if a["created_at"] <= stale:
                    reasons.append("never_certified")
            elif cert["policy_version"] < POLICY_VERSION or cert["valid_until"] <= now_s:
                reasons.append("certificate_outdated")
            elif cert["valid_until"] <= soon:
                reasons.append("certificate_expiring")
            n = self.impersonation_attempts(a["agent_id"])
            if n >= IMPERSONATION_THRESHOLD:
                reasons.append("impersonation_attempts")
            if KEYS.index(a["key_alg"]) < KEYS.index(self.min_key):
                reasons.append("weak_key")
            if self.humans:
                ap = self.humans.approval(a["agent_id"], a["key_fingerprint"])
                if ap and not ap["current"]:
                    reasons.append("human_approval_expired")
            if reasons:
                found[a["agent_id"]] = reasons
        with self._lock:
            existing = {r["agent_id"]: r["first_seen"] for r in self._db.execute("SELECT * FROM inspector_watch")}
            self._db.execute("DELETE FROM inspector_watch")
            for aid, reasons in found.items():
                self._db.execute("INSERT INTO inspector_watch VALUES (?,?,?,?)",
                                 (aid, json.dumps(reasons), existing.get(aid, now_s), now_s))
            self._db.commit()
        self.log("", "patrol", {"allowed": True, "reasons": []})
        counts: dict[str, int] = {}
        for reasons in found.values():
            for x in reasons:
                counts[x] = counts.get(x, 0) + 1
        return {"swept_at": now_s, "agents_checked": len(agents), "on_watchlist": len(found),
                "by_reason": counts, "cleared": sorted(set(existing) - set(found))}

    def watchlist(self) -> dict:
        rows = self._db.execute("SELECT * FROM inspector_watch ORDER BY first_seen").fetchall()
        last = self._db.execute("SELECT at FROM inspector_log WHERE scope='patrol' ORDER BY id DESC LIMIT 1").fetchone()
        out = []
        for r in rows:
            try:
                a = self.accel._row(r["agent_id"])
                who = {"name": a["name"], "operator": a["operator"], "level": a["level"]}
            except AcceleratorError:
                who = {}
            out.append({"agent_id": r["agent_id"], **who, "reasons": json.loads(r["reasons"]),
                        "on_list_since": r["first_seen"], "last_checked": r["last_seen"]})
        return {"watchlist": "Privi Inspector", "last_patrol": last["at"] if last else None, "agents": out,
                "meaning": {"revoked": "Privi revoked this agent", "certificate_outdated": "certificate expired or old policy",
                            "certificate_expiring": f"certificate expires within {EXPIRING_DAYS} days",
                            "never_certified": f"enrolled over {STALE_ENROLLMENT_DAYS} days ago, no certificate",
                            "impersonation_attempts": f"{IMPERSONATION_THRESHOLD}+ forged signatures against this agent "
                                                      "in the last hour: someone may be posing as it",
                            "weak_key": "key is below the realm's minimum",
                            "human_approval_expired": "its human approval expired; a person must approve it again"},
                "use": "Block or require a fresh inspector_check for agents on this list."}
