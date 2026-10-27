# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Quantum - https://priviflow.us - dariocanoy@priviflow.us
"""Privi Quantum Agent Accelerator and the Quantum Agent Directory.

An AI agent upgrades itself to a quantum agent in four steps, each checked by Privi:

  Q1  Quantum-aware        scanned its own code or config for quantum-vulnerable cryptography
  Q2  Quantum-safe identity proved it holds an ML-DSA (FIPS 204) key by signing a Privi challenge
  Q3  Quantum-safe links   every public endpoint it runs negotiates hybrid post-quantum TLS (X25519MLKEM768)
  Q4  Quantum-capable      ran a quantum job Privi assigned to it through Dream Weaver and returned the signed result

Q1 + Q2 + Q4 earns "Quantum Agent"; all four earns "Quantum Agent+". Each level change issues a
certificate signed by Privi with Ed25519 + ML-DSA-87 and anchored on chain.

The Quantum Agent Directory is public and free: any agent can look up another agent's post-quantum
public key and level, verify a message it signed (qagent_verify), or check a certificate. That is
what makes it useful to every agent: a post-quantum identity check before trusting or paying a peer.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import sqlite3
import threading
import time
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import mldsa

from .attest import now_iso
from .dream import problem_sha

KEY_TYPES = {1312: ("ML-DSA-44", mldsa.MLDSA44PublicKey), 1952: ("ML-DSA-65", mldsa.MLDSA65PublicKey),
             2592: ("ML-DSA-87", mldsa.MLDSA87PublicKey)}
STEPS = {
    "q1_scan": "Quantum-aware: scanned its code for quantum-vulnerable cryptography",
    "q2_identity": "Quantum-safe identity: proved an ML-DSA (FIPS 204) key",
    "q3_transport": "Quantum-safe links: every endpoint uses hybrid post-quantum TLS",
    "q4_quantum": "Quantum-capable: completed an assigned quantum job through Dream Weaver",
}
CHALLENGE_TTL = 600
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._@/-]{1,79}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS qa_agents (
    agent_id   TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    operator   TEXT NOT NULL,
    homepage   TEXT NOT NULL DEFAULT '',
    key_alg    TEXT NOT NULL,
    public_key TEXT NOT NULL,
    key_fingerprint TEXT NOT NULL,
    token_hash TEXT NOT NULL,
    listed     INTEGER NOT NULL DEFAULT 1,
    steps      TEXT NOT NULL DEFAULT '{}',
    level      TEXT NOT NULL DEFAULT 'enrolled',
    certificate_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS qa_challenges (
    challenge_id TEXT PRIMARY KEY,
    agent_id     TEXT NOT NULL,
    message      TEXT NOT NULL,
    expires_at   REAL NOT NULL,
    used         INTEGER NOT NULL DEFAULT 0
);
"""


class AcceleratorError(ValueError):
    pass


def _h(token: str) -> str:
    return hashlib.sha256(("privi-qagent:" + token).encode()).hexdigest()


def load_key(public_key_b64: str):
    try:
        raw = base64.b64decode(public_key_b64, validate=True)
    except (ValueError, TypeError):
        raise AcceleratorError("public_key must be base64 of the raw ML-DSA public key")
    if len(raw) not in KEY_TYPES:
        raise AcceleratorError("public_key must be a raw ML-DSA-44, -65 or -87 public key (1312, 1952 or 2592 bytes)")
    alg, cls = KEY_TYPES[len(raw)]
    try:
        return alg, cls.from_public_bytes(raw), raw
    except ValueError:
        raise AcceleratorError("public_key is not a valid ML-DSA key")


def level_of(steps: dict) -> str:
    done = {k for k, v in steps.items() if v.get("passed")}
    if {"q1_scan", "q2_identity", "q4_quantum"} <= done:
        return "quantum_agent_plus" if "q3_transport" in done else "quantum_agent"
    if "q2_identity" in done:
        return "quantum_safe_identity"
    if "q1_scan" in done:
        return "quantum_aware"
    return "enrolled"


LEVEL_LABEL = {"enrolled": "Enrolled", "quantum_aware": "Quantum-aware (Q1)",
               "quantum_safe_identity": "Quantum-safe identity (Q2)", "quantum_agent": "Quantum Agent",
               "quantum_agent_plus": "Quantum Agent+"}


def quantum_task(agent_id: str) -> tuple[str, dict]:
    """A small balance_lines problem unique to this agent; its hash binds the quantum run to the agent."""
    seed = int(hashlib.sha256(("privi-qtask:" + agent_id).encode()).hexdigest(), 16)
    minutes = [(seed >> (8 * i)) % 50 + 5 for i in range(7)]
    return "balance_lines", {"jobs": [{"name": f"{agent_id[-6:]}-job{i}", "minutes": m} for i, m in enumerate(minutes)]}


class Accelerator:
    def __init__(self, db_path: str, attestor, public_url: str):
        self.attestor, self.public_url = attestor, public_url
        self._lock = threading.Lock()
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.commit()

    # ---------------- enrollment ----------------

    def enroll(self, name: str, operator: str, public_key: str, homepage: str = "", listed: bool = True) -> dict:
        if not NAME_RE.match(name or ""):
            raise AcceleratorError("name: 2-80 letters, digits, spaces, . _ @ / -")
        if not NAME_RE.match(operator or ""):
            raise AcceleratorError("operator (the company or person accountable for the agent): 2-80 characters")
        if homepage and not re.match(r"^https://[^\s]{4,300}$", homepage):
            raise AcceleratorError("homepage must be an https:// URL")
        alg, _, raw = load_key(public_key)
        fp = hashlib.sha256(raw).hexdigest()
        if self._db.execute("SELECT 1 FROM qa_agents WHERE key_fingerprint=?", (fp,)).fetchone():
            raise AcceleratorError("this public key is already enrolled; each agent needs its own key")
        agent_id, token = "qagent_" + secrets.token_hex(6), "qat_" + secrets.token_urlsafe(24)
        now = now_iso()
        with self._lock:
            self._db.execute("""INSERT INTO qa_agents (agent_id, name, operator, homepage, key_alg, public_key,
                                key_fingerprint, token_hash, listed, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                             (agent_id, name, operator, homepage, alg, public_key, fp, _h(token), int(listed), now, now))
            self._db.commit()
        return {"agent_id": agent_id, "agent_token": token, "key_alg": alg, "key_fingerprint": fp,
                "profile_url": f"{self.public_url}/quantum-agents/{agent_id}", "plan": self.plan(agent_id)}

    def _row(self, agent_id: str) -> dict:
        r = self._db.execute("SELECT * FROM qa_agents WHERE agent_id=?", (agent_id or "",)).fetchone()
        if not r:
            raise AcceleratorError("agent not found")
        d = dict(r)
        d["steps"] = json.loads(d["steps"])
        return d

    def auth(self, agent_id: str, token: str) -> dict:
        a = self._row(agent_id)
        if not token or not secrets.compare_digest(a["token_hash"], _h(token)):
            raise AcceleratorError("wrong agent_id or agent_token")
        return a

    def plan(self, agent_id: str) -> list[dict]:
        a = self._row(agent_id)
        tools = {"q1_scan": "qagent_scan (send your code or config)",
                 "q2_identity": "qagent_challenge, sign the message with your ML-DSA key, then qagent_prove",
                 "q3_transport": "qagent_scan with your public endpoints (all must use X25519MLKEM768)",
                 "q4_quantum": "qagent_quantum_task, run it with dreamweaver_run or dreamscape_submit, then qagent_quantum_proof"}
        return [{"step": k, "what": v, "how": tools[k], "passed": bool(a["steps"].get(k, {}).get("passed"))}
                for k, v in STEPS.items()]

    # ---------------- steps ----------------

    def _record(self, a: dict, step: str, passed: bool, evidence: dict) -> dict:
        steps = dict(a["steps"])
        prev = steps.get(step, {})
        if prev.get("passed") and not passed and step != "q3_transport":
            passed = True                                  # a later weaker attempt never removes an earned step
            evidence = prev.get("evidence", evidence)
        steps[step] = {"passed": passed, "at": now_iso(), "evidence": evidence}
        old_level, new_level = a["level"], level_of(steps)
        cert = a["certificate_id"]
        if new_level != old_level and new_level != "enrolled":
            cert = self._certify(a, steps, new_level)["id"]
        with self._lock:
            self._db.execute("UPDATE qa_agents SET steps=?, level=?, certificate_id=?, updated_at=? WHERE agent_id=?",
                             (json.dumps(steps), new_level, cert, now_iso(), a["agent_id"]))
            self._db.commit()
        return {"step": step, "passed": passed, "level": new_level, "level_label": LEVEL_LABEL[new_level],
                "level_changed": new_level != old_level, "certificate_id": cert, "plan": self.plan(a["agent_id"])}

    def _certify(self, a: dict, steps: dict, level: str) -> dict:
        body = {"agent_id": a["agent_id"], "name": a["name"], "operator": a["operator"], "level": level,
                "level_label": LEVEL_LABEL[level], "key_alg": a["key_alg"], "key_fingerprint": a["key_fingerprint"],
                "steps_passed": sorted(k for k, v in steps.items() if v.get("passed")),
                "profile_url": f"{self.public_url}/quantum-agents/{a['agent_id']}"}
        return self.attestor.issue("quantum_agent_certificate", body)

    def record_scan(self, agent_id: str, token: str, code_report: dict | None, endpoint_report: dict | None) -> dict:
        a = self.auth(agent_id, token)
        out: dict[str, Any] = {}
        if code_report is not None:
            ev = {"readiness_score": code_report["readiness_score"], "counts": code_report["counts"],
                  "files_scanned": code_report["files_scanned"]}
            out["q1_scan"] = self._record(a, "q1_scan", True, ev)
            a = self._row(agent_id)
        if endpoint_report is not None:
            res = endpoint_report.get("results", [])
            checked = [r for r in res if r.get("status") not in ("invalid", "blocked", "unreachable")]
            passed = bool(checked) and len(checked) == len(res) and all(r["status"] == "pq_hybrid" for r in checked)
            ev = {"endpoints": [{"target": r.get("target"), "status": r.get("status")} for r in res]}
            out["q3_transport"] = self._record(a, "q3_transport", passed, ev)
        last = out.get("q3_transport") or out.get("q1_scan")
        return {"agent_id": agent_id, **{k: {kk: v[kk] for kk in ("passed",)} for k, v in out.items()},
                "level": last["level"], "level_label": last["level_label"], "certificate_id": last["certificate_id"],
                "plan": last["plan"]}

    def challenge(self, agent_id: str, token: str) -> dict:
        self.auth(agent_id, token)
        cid = "qch_" + secrets.token_hex(8)
        message = f"privi-quantum-agent:{agent_id}:{cid}:{secrets.token_hex(16)}"
        with self._lock:
            self._db.execute("INSERT INTO qa_challenges VALUES (?,?,?,?,0)",
                             (cid, agent_id, message, time.time() + CHALLENGE_TTL))
            self._db.commit()
        return {"challenge_id": cid, "message": message, "expires_in_seconds": CHALLENGE_TTL,
                "sign": "ML-DSA signature over the UTF-8 bytes of message, empty context, base64 encoded"}

    def prove(self, agent_id: str, token: str, challenge_id: str, signature_b64: str) -> dict:
        a = self.auth(agent_id, token)
        r = self._db.execute("SELECT * FROM qa_challenges WHERE challenge_id=? AND agent_id=?",
                             (challenge_id, agent_id)).fetchone()
        if not r or r["used"] or r["expires_at"] < time.time():
            raise AcceleratorError("challenge not found, already used or expired; ask for a new one")
        with self._lock:
            self._db.execute("UPDATE qa_challenges SET used=1 WHERE challenge_id=?", (challenge_id,))
            self._db.commit()
        if not self._verify(a, r["message"].encode(), signature_b64):
            raise AcceleratorError("signature does not verify with your enrolled ML-DSA public key")
        return self._record(a, "q2_identity", True, {"challenge_id": challenge_id, "key_alg": a["key_alg"]})

    def task(self, agent_id: str, token: str) -> dict:
        self.auth(agent_id, token)
        problem, data = quantum_task(agent_id)
        return {"problem": problem, "data": data, "problem_sha256": problem_sha(problem, data),
                "do": "Run exactly this with dreamweaver_run (or dreamscape_submit), then send its attestation id "
                      "to qagent_quantum_proof."}

    def quantum_proof(self, agent_id: str, token: str, attestation_id: str) -> dict:
        a = self.auth(agent_id, token)
        problem, data = quantum_task(agent_id)
        att = self.attestor.get(attestation_id or "")
        if not att or att["body"].get("kind") != "dreamweaver_result":
            raise AcceleratorError("give the attestation id of a Dream Weaver result issued by this server")
        b = att["body"]
        if b.get("problem_sha256") != problem_sha(problem, data):
            raise AcceleratorError("that result is for a different problem; run the task from qagent_quantum_task exactly")
        if b.get("issued_at", "") < a["created_at"]:
            raise AcceleratorError("that result was issued before this agent enrolled")
        return self._record(a, "q4_quantum", True, {"attestation_id": attestation_id, "winner_realm": b.get("winner_realm"),
                                                    "found_optimum": b.get("found_optimum")})

    # ---------------- public directory ----------------

    def _verify(self, a: dict, message: bytes, signature_b64: str) -> bool:
        try:
            sig = base64.b64decode(signature_b64, validate=True)
            _, key, _ = load_key(a["public_key"])
            key.verify(sig, message)
            return True
        except (InvalidSignature, ValueError, TypeError, AcceleratorError):
            return False

    def verify_message(self, agent_id: str, message: str, signature_b64: str) -> dict:
        a = self._row(agent_id)
        ok = self._verify(a, message.encode(), signature_b64)
        return {"agent_id": agent_id, "valid": ok, "name": a["name"], "operator": a["operator"],
                "level": a["level"], "level_label": LEVEL_LABEL[a["level"]], "key_alg": a["key_alg"],
                "key_fingerprint": a["key_fingerprint"],
                "meaning": ("The message was signed with this agent's enrolled post-quantum key." if ok else
                            "The signature does not match this agent's enrolled key.")}

    def public(self, agent_id: str, include_key: bool = True) -> dict:
        a = self._row(agent_id)
        out = {"agent_id": a["agent_id"], "name": a["name"], "operator": a["operator"], "homepage": a["homepage"] or None,
               "level": a["level"], "level_label": LEVEL_LABEL[a["level"]], "key_alg": a["key_alg"],
               "key_fingerprint": a["key_fingerprint"],
               "steps": {k: {"passed": bool(v.get("passed")), "at": v.get("at")} for k, v in a["steps"].items()},
               "certificate_id": a["certificate_id"],
               "certificate_url": f"{self.public_url}/attestations/{a['certificate_id']}" if a["certificate_id"] else None,
               "badge": f"{self.public_url}/quantum-agents/{a['agent_id']}/badge.svg",
               "enrolled_at": a["created_at"], "updated_at": a["updated_at"]}
        if include_key:
            out["public_key"] = a["public_key"]
        return out

    def directory(self, level: str | None = None, query: str = "", limit: int = 100) -> dict:
        sql, args = "SELECT agent_id FROM qa_agents WHERE listed=1", []
        if level:
            sql += " AND level=?"
            args.append(level)
        if query:
            sql += " AND (name LIKE ? OR operator LIKE ?)"
            args += [f"%{query[:60]}%"] * 2
        order = ("CASE level WHEN 'quantum_agent_plus' THEN 0 WHEN 'quantum_agent' THEN 1 WHEN 'quantum_safe_identity' "
                 "THEN 2 WHEN 'quantum_aware' THEN 3 ELSE 4 END, updated_at DESC")
        rows = self._db.execute(f"{sql} ORDER BY {order} LIMIT ?", (*args, max(1, min(limit, 500)))).fetchall()
        counts = {r["level"]: r["n"] for r in self._db.execute(
            "SELECT level, COUNT(*) n FROM qa_agents WHERE listed=1 GROUP BY level").fetchall()}
        return {"directory": "Privi Quantum Agent Directory", "counts": counts,
                "agents": [self.public(r["agent_id"], include_key=False) for r in rows],
                "lookup": f"{self.public_url}/quantum-agents/{{agent_id}}",
                "verify": "qagent_verify (MCP) checks a message an agent signed with its post-quantum key; free",
                "join": f"{self.public_url}/accelerator"}


def badge_svg(label: str, level: str) -> str:
    color = {"quantum_agent_plus": "#6d28d9", "quantum_agent": "#7c3aed", "quantum_safe_identity": "#2563eb",
             "quantum_aware": "#0891b2"}.get(level, "#6b7280")
    w = 64 + 7 * len(label)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w + 92}" height="20" role="img" aria-label="Privi {label}">'
            f'<rect width="92" height="20" fill="#1f2937"/><rect x="92" width="{w}" height="20" fill="{color}"/>'
            f'<g fill="#fff" font-family="Verdana,sans-serif" font-size="11"><text x="8" y="14">Privi Quantum</text>'
            f'<text x="100" y="14">{label}</text></g></svg>')
