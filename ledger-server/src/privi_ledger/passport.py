"""Privi Passport: a signed, on-chain-anchored trust credential for an AI agent.

Nobody else can issue one, because the score is computed from evidence only Privi
Ledger holds: the agent's tamper-evident history, its on-chain checkpoints, its
sealed compliance reports and the handshakes other companies confirmed with it.

A passport is a JSON document, Ed25519-signed by this server and hash-anchored on
the Privi chain. Any agent can verify it for free (signature, anchor, expiry,
revocation) and re-score the subject live, so a passport that was honest when
issued cannot keep vouching for an agent whose log has since been tampered with.

Score (0-1000) is deterministic and fully itemised, so a counterparty can see
exactly why an agent scored what it did:

  history      300   how much verifiable history exists and for how long
  integrity    250   every stream's hash chain still verifies (all or nothing)
  anchoring    150   share of streams whose on-chain checkpoint matches the record
  reliability  100   1 - failure rate
  oversight     50   human approvals recorded on sensitive actions
  compliance   100   a sealed compliance report exists and is clean
  handshakes    50   deals other Privi organizations confirmed with this org

Grades: A >= 850, B >= 700, C >= 550, D >= 400, E below.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.exceptions import InvalidSignature

PASSPORT_VERSION = "1"
VALID_DAYS = 30
SENSITIVE = ("payment", "data_change", "message")
WEIGHTS = {"history": 300, "integrity": 250, "anchoring": 150, "reliability": 100,
           "oversight": 50, "compliance": 100, "handshakes": 50}
GRADES = (("A", 850), ("B", 700), ("C", 550), ("D", 400), ("E", 0))

SCHEMA = """
CREATE TABLE IF NOT EXISTS passports (
    passport_id   TEXT PRIMARY KEY,
    org_id        TEXT NOT NULL,
    stream_id     TEXT NOT NULL,            -- '*' = whole organization
    body          TEXT NOT NULL,            -- canonical JSON
    body_hash     TEXT NOT NULL UNIQUE,
    signature     TEXT NOT NULL,            -- hex Ed25519 over body_hash bytes
    attestation   TEXT NOT NULL,            -- anchor receipt JSON
    score         INTEGER NOT NULL,
    grade         TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    expires_at    TEXT NOT NULL,
    revoked_at    TEXT,
    revoke_reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_pp_org ON passports (org_id, created_at);
CREATE TABLE IF NOT EXISTS passport_keys (
    key_id      TEXT PRIMARY KEY,
    private_hex TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.isoformat(timespec="seconds")


def canonical(body: dict) -> str:
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def body_hash(body: dict) -> str:
    return hashlib.sha256(canonical(body).encode("utf-8")).hexdigest()


def grade_for(score: int) -> str:
    return next(g for g, floor in GRADES if score >= floor)


class PassportError(Exception):
    pass


class Passports:
    def __init__(self, ledger, db: sqlite3.Connection, lock: threading.Lock, reports, handshakes,
                 onchain: Callable[[str, str, dict], dict], issuer_url: str, signing_seed_hex: str = ""):
        self.ledger, self._db, self._lock = ledger, db, lock
        self.reports, self.handshakes, self.onchain, self.issuer_url = reports, handshakes, onchain, issuer_url
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.commit()
        self._key = self._load_key(signing_seed_hex)
        self.public_key_hex = self._key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
        self.key_id = "pk_" + hashlib.sha256(bytes.fromhex(self.public_key_hex)).hexdigest()[:16]

    # ---------------- keys ----------------

    def _load_key(self, seed_hex: str) -> Ed25519PrivateKey:
        if seed_hex:
            return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(seed_hex.strip()))
        with self._lock:
            row = self._db.execute("SELECT private_hex FROM passport_keys ORDER BY created_at LIMIT 1").fetchone()
            if row:
                return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(row["private_hex"]))
            key = Ed25519PrivateKey.generate()
            raw = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                    serialization.NoEncryption()).hex()
            self._db.execute("INSERT INTO passport_keys VALUES (?,?,?)", ("k1", raw, _iso(_now())))
            self._db.commit()
            return key

    def issuer(self) -> dict:
        return {"issuer": "Privi Ledger", "issuer_url": self.issuer_url, "key_id": self.key_id,
                "algorithm": "Ed25519 over sha256(canonical JSON body)", "public_key_hex": self.public_key_hex}

    def sign(self, h: str) -> str:
        return self._key.sign(bytes.fromhex(h)).hex()

    def signature_ok(self, h: str, sig_hex: str, public_key_hex: str | None = None) -> bool:
        try:
            pk = (Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))
                  if public_key_hex else self._key.public_key())
            pk.verify(bytes.fromhex(sig_hex), bytes.fromhex(h))
            return True
        except (InvalidSignature, ValueError):
            return False

    # ---------------- scoring ----------------

    def facts(self, org_id: str, stream_id: str | None) -> dict[str, Any]:
        """Everything the score is computed from, gathered live from the ledger."""
        streams = [s["stream_id"] for s in self.ledger.streams(org_id)]
        if stream_id:
            streams = [s for s in streams if s == stream_id]
        entries = 0
        failures = sensitive = approvals = 0
        first = last = None
        intact, anchored_ok, anchored_any = True, 0, 0
        heads: dict[str, str] = {}
        broken: list[str] = []
        for s in streams:
            evs = self.ledger.entries(org_id, s)
            c = self.ledger.check_chain(evs)
            chk: dict[str, Any] = {}
            info = self.onchain(org_id, s, chk)
            if not c.valid or chk.get("intact") is False:
                intact = False
                broken.append(s)
            if info.get("anchored"):
                anchored_any += 1
                if info.get("matches_current_record"):
                    anchored_ok += 1
            entries += len(evs)
            heads[s] = evs[-1]["entry_hash"]
            for e in evs:
                failures += e["outcome"] == "failure"
                sensitive += e["action_type"] in SENSITIVE
                approvals += e["action_type"] == "approval"
                first = e["recorded_at"] if first is None or e["recorded_at"] < first else first
                last = e["recorded_at"] if last is None or e["recorded_at"] > last else last
        days = 0
        if first and last:
            days = max(0, (datetime.fromisoformat(last) - datetime.fromisoformat(first)).days)
        rep = self._db.execute("SELECT report_id, body, attestation, created_at FROM reports WHERE org_id=? "
                               "ORDER BY created_at DESC LIMIT 1", (org_id,)).fetchone()
        latest_report = None
        if rep:
            b, a = json.loads(rep["body"]), json.loads(rep["attestation"])
            latest_report = {"report_id": rep["report_id"], "status": b.get("status"),
                             "issued_at": rep["created_at"], "anchored": bool(a.get("anchored"))}
        hs = self._db.execute("SELECT COUNT(*) FROM handshakes WHERE status='accepted' AND (from_org=? OR to_org=?)",
                              (org_id, org_id)).fetchone()[0]
        return {
            "streams": streams, "stream_count": len(streams), "entry_count": entries,
            "first_recorded_at": first, "last_recorded_at": last, "days_active": days,
            "failures": failures, "sensitive_actions": sensitive, "human_approvals": approvals,
            "all_streams_intact": intact, "broken_streams": broken,
            "streams_anchored": anchored_any, "streams_anchored_and_matching": anchored_ok,
            "latest_compliance_report": latest_report, "handshakes_accepted": hs,
            "head_hashes": heads,
        }

    @staticmethod
    def score(f: dict[str, Any]) -> dict[str, Any]:
        comp: dict[str, dict[str, Any]] = {}
        n = f["entry_count"]
        hist = round(min(n, 1000) / 1000 * 200 + min(f["days_active"], 180) / 180 * 100)
        comp["history"] = {"points": hist, "of": 300, "entries": n, "days_active": f["days_active"]}
        comp["integrity"] = {"points": 250 if f["all_streams_intact"] and n else 0, "of": 250,
                             "all_streams_intact": f["all_streams_intact"], "broken_streams": f["broken_streams"]}
        sc = f["stream_count"] or 1
        comp["anchoring"] = {"points": round(150 * f["streams_anchored_and_matching"] / sc), "of": 150,
                             "streams_anchored_and_matching": f["streams_anchored_and_matching"], "streams": f["stream_count"]}
        rate = (f["failures"] / n) if n else 1.0
        comp["reliability"] = {"points": round(100 * (1 - min(rate, 1.0))) if n else 0, "of": 100,
                               "failures": f["failures"], "failure_rate": round(rate, 4)}
        if f["sensitive_actions"]:
            cov = min(1.0, f["human_approvals"] / f["sensitive_actions"])
            ov = round(50 * cov)
        else:
            ov = 25 if n else 0  # nothing sensitive happened; half credit
        comp["oversight"] = {"points": ov, "of": 50, "human_approvals": f["human_approvals"],
                             "sensitive_actions": f["sensitive_actions"]}
        r = f["latest_compliance_report"]
        cp = 0 if not r else (100 if r["status"] == "clean" else 50)
        comp["compliance"] = {"points": cp, "of": 100, "latest_report": r}
        comp["handshakes"] = {"points": round(50 * min(f["handshakes_accepted"], 10) / 10), "of": 50,
                              "accepted": f["handshakes_accepted"]}
        total = sum(c["points"] for c in comp.values())
        return {"score": total, "of": 1000, "grade": grade_for(total), "components": comp}

    # ---------------- issue / lookup ----------------

    def build(self, org: dict, stream_id: str | None) -> dict[str, Any]:
        f = self.facts(org["org_id"], stream_id)
        if not f["entry_count"]:
            raise PassportError("no recorded history to issue a passport for" +
                                (f" (stream '{stream_id}')" if stream_id else ""))
        s = self.score(f)
        now = _now()
        return {
            "type": "PriviPassport", "version": PASSPORT_VERSION,
            "passport_id": "pp_" + secrets.token_hex(8),
            **{k: v for k, v in self.issuer().items() if k != "public_key_hex"},
            "subject": {"org_id": org["org_id"], "organization": org["name"], "stream_id": stream_id or "*",
                        "scope": "stream" if stream_id else "organization"},
            "issued_at": _iso(now), "expires_at": _iso(now + timedelta(days=VALID_DAYS)),
            "score": s["score"], "of": s["of"], "grade": s["grade"], "components": s["components"],
            "facts": f,
            "verify_with": {"server": self.issuer_url, "tool": "passport_verify", "free": True},
        }

    def save(self, body: dict, signature: str, attestation: dict) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO passports (passport_id, org_id, stream_id, body, body_hash, signature, attestation, "
                "score, grade, created_at, expires_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (body["passport_id"], body["subject"]["org_id"], body["subject"]["stream_id"], canonical(body),
                 body_hash(body), signature, json.dumps(attestation), body["score"], body["grade"],
                 body["issued_at"], body["expires_at"]))
            self._db.commit()

    def get(self, passport_id: str) -> dict | None:
        r = self._db.execute("SELECT * FROM passports WHERE passport_id=?", (passport_id.strip(),)).fetchone()
        return self._row(r) if r else None

    def by_hash(self, h: str) -> dict | None:
        r = self._db.execute("SELECT * FROM passports WHERE body_hash=?", (h,)).fetchone()
        return self._row(r) if r else None

    def list_for(self, org_id: str) -> list[dict]:
        rows = self._db.execute("SELECT passport_id, stream_id, score, grade, created_at, expires_at, revoked_at "
                                "FROM passports WHERE org_id=? ORDER BY created_at DESC LIMIT 50", (org_id,)).fetchall()
        return [dict(r) for r in rows]

    def revoke(self, passport_id: str, org_id: str, reason: str) -> dict:
        with self._lock:
            r = self._db.execute("SELECT org_id, revoked_at FROM passports WHERE passport_id=?", (passport_id,)).fetchone()
            if not r or r["org_id"] != org_id:
                raise PassportError("no such passport for this organization")
            if r["revoked_at"]:
                return {"passport_id": passport_id, "revoked": True, "revoked_at": r["revoked_at"]}
            now = _iso(_now())
            self._db.execute("UPDATE passports SET revoked_at=?, revoke_reason=? WHERE passport_id=?",
                             (now, reason[:500], passport_id))
            self._db.commit()
        return {"passport_id": passport_id, "revoked": True, "revoked_at": now}

    @staticmethod
    def _row(r) -> dict:
        return {"passport_id": r["passport_id"], "org_id": r["org_id"], "stream_id": r["stream_id"],
                "body": json.loads(r["body"]), "body_hash": r["body_hash"], "signature": r["signature"],
                "attestation": json.loads(r["attestation"]), "score": r["score"], "grade": r["grade"],
                "created_at": r["created_at"], "expires_at": r["expires_at"],
                "revoked_at": r["revoked_at"], "revoke_reason": r["revoke_reason"]}

    # ---------------- verification ----------------

    def check(self, rec: dict, live: bool = True) -> dict[str, Any]:
        """Offline checks plus a live re-score of the subject. Chain verification is added by the caller."""
        body = rec["body"]
        h = body_hash(body)
        out: dict[str, Any] = {
            "passport_id": body["passport_id"], "subject": body["subject"],
            "issued_at": body["issued_at"], "expires_at": body["expires_at"],
            "issued_score": body["score"], "issued_grade": body["grade"],
            "hash_matches_issued": h == rec["body_hash"],
            "signature_valid": self.signature_ok(h, rec["signature"]),
            "expired": body["expires_at"] < _iso(_now()),
            "revoked": bool(rec["revoked_at"]), "revoke_reason": rec["revoke_reason"],
            "anchored": bool(rec["attestation"].get("anchored")),
        }
        if live:
            org = self._db.execute("SELECT org_id, name FROM orgs WHERE org_id=?", (body["subject"]["org_id"],)).fetchone()
            sid = None if body["subject"]["stream_id"] == "*" else body["subject"]["stream_id"]
            if org:
                f = self.facts(org["org_id"], sid)
                s = self.score(f)
                out["live"] = {"score": s["score"], "grade": s["grade"], "all_streams_intact": f["all_streams_intact"],
                               "entry_count": f["entry_count"], "last_recorded_at": f["last_recorded_at"],
                               "drift": s["score"] - body["score"]}
                out["history_still_intact"] = f["all_streams_intact"]
            else:
                out["live"] = None
                out["history_still_intact"] = False
        ok = (out["hash_matches_issued"] and out["signature_valid"] and not out["expired"] and not out["revoked"]
              and out.get("history_still_intact", True))
        out["valid"] = ok
        return out

    @staticmethod
    def gate(v: dict, min_score: int, min_grade: str | None, require_intact: bool, require_anchored: bool) -> dict:
        reasons: list[str] = []
        if not v["valid"]:
            for k, msg in (("hash_matches_issued", "passport content does not match what was issued"),
                           ("signature_valid", "signature is not from Privi Ledger")):
                if not v[k]:
                    reasons.append(msg)
            if v["expired"]:
                reasons.append("passport expired")
            if v["revoked"]:
                reasons.append("passport revoked by its organization")
            if v.get("history_still_intact") is False:
                reasons.append("the agent's history no longer verifies (tampering detected since issue)")
        current = v["live"]["score"] if v.get("live") else v["issued_score"]
        grade = v["live"]["grade"] if v.get("live") else v["issued_grade"]
        if current < min_score:
            reasons.append(f"current score {current} is below the required {min_score}")
        order = [g for g, _ in GRADES]
        if min_grade and order.index(grade) > order.index(min_grade.upper()):
            reasons.append(f"current grade {grade} is below the required {min_grade.upper()}")
        if require_anchored and not v["anchored"]:
            reasons.append("passport is not anchored on the Privi chain")
        if require_intact and v.get("history_still_intact") is False:
            reasons.append("history integrity required")
        return {"allow": not reasons, "reasons": reasons, "current_score": current, "current_grade": grade}


def badge_svg(grade: str, score: int, revoked: bool = False, expired: bool = False) -> str:
    color = {"A": "#1a7f37", "B": "#2da44e", "C": "#bf8700", "D": "#d1242f", "E": "#6e7781"}[grade]
    label = "Privi Trust"
    value = "revoked" if revoked else ("expired" if expired else f"{grade} · {score}")
    if revoked or expired:
        color = "#6e7781"
    lw, vw = 78, 14 + 7 * len(value)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{lw + vw}" height="20" role="img" aria-label="{label}: {value}">'
            f'<linearGradient id="s" x2="0" y2="100%"><stop offset="0" stop-color="#bbb" stop-opacity=".1"/>'
            f'<stop offset="1" stop-opacity=".1"/></linearGradient>'
            f'<clipPath id="r"><rect width="{lw + vw}" height="20" rx="3" fill="#fff"/></clipPath>'
            f'<g clip-path="url(#r)"><rect width="{lw}" height="20" fill="#0b1f3a"/>'
            f'<rect x="{lw}" width="{vw}" height="20" fill="{color}"/><rect width="{lw + vw}" height="20" fill="url(#s)"/></g>'
            f'<g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11">'
            f'<text x="{lw / 2}" y="14">{label}</text><text x="{lw + vw / 2}" y="14">{value}</text></g></svg>')
