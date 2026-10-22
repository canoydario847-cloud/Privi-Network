"""Privi Handshake: matched, two-sided records of dealings between organizations.

Company A's agent offers a handshake describing a dealing with company B (a
payment, a data transfer, a delivery, an agreement). A's log records the offer.
When B's agent accepts, B's log records the same terms, A's log records the
acceptance, and a pair hash binding the terms and both entries is anchored on
chain (Base, until the Privi chain mainnet). Neither side can later deny or rewrite the dealing alone: each
log holds the other side's entry hash, and the pair is fixed on chain.

Only works when both organizations use Privi Ledger.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS handshakes (
    handshake_id     TEXT PRIMARY KEY,
    from_org         TEXT NOT NULL,
    to_org           TEXT NOT NULL,
    from_stream      TEXT NOT NULL,
    to_stream        TEXT,
    terms            TEXT NOT NULL,
    terms_hash       TEXT NOT NULL,
    from_entry_hash  TEXT NOT NULL,
    to_entry_hash    TEXT,
    status           TEXT NOT NULL,     -- offered | accepted | rejected | expired
    reason           TEXT,
    pair_hash        TEXT,
    anchor           TEXT,
    created_at       TEXT NOT NULL,
    expires_at       TEXT NOT NULL,
    decided_at       TEXT
);
CREATE INDEX IF NOT EXISTS idx_hs_to ON handshakes (to_org, status);
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.isoformat(timespec="seconds")


def sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def pair_hash(terms_hash: str, from_entry: str, to_entry: str) -> str:
    return sha(f"privi-handshake:v1:{terms_hash}:{from_entry}:{to_entry}")


class HandshakeError(ValueError):
    pass


class Handshakes:
    def __init__(self, ledger, db: sqlite3.Connection, lock: threading.Lock):
        self.ledger, self._db, self._lock = ledger, db, lock
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.commit()

    def _get(self, hid: str) -> dict | None:
        r = self._db.execute("SELECT * FROM handshakes WHERE handshake_id=?", (hid,)).fetchone()
        return {k: r[k] for k in r.keys()} if r else None

    def _expire(self, h: dict) -> dict:
        if h["status"] == "offered" and h["expires_at"] < _iso(_now()):
            with self._lock:
                self._db.execute("UPDATE handshakes SET status='expired', decided_at=? WHERE handshake_id=?",
                                 (_iso(_now()), h["handshake_id"]))
                self._db.commit()
            h["status"] = "expired"
        return h

    def offer(self, from_org: str, to_org: str, stream_id: str, actor: str, action_type: str, summary: str,
              resource: str = "", details: Any = None, expires_hours: float = 72) -> dict:
        if from_org == to_org:
            raise HandshakeError("a handshake needs two different organizations")
        if not self.ledger.org_exists(to_org):
            raise HandshakeError("counterparty organization is not on Privi Ledger")
        if not 0 < expires_hours <= 24 * 30:
            raise HandshakeError("expires_hours must be between 0 and 720")
        hid = "hs_" + secrets.token_hex(10)
        created = _now()
        terms = {"handshake_id": hid, "from_org": from_org, "to_org": to_org, "action_type": action_type,
                 "summary": summary.strip(), "resource": (resource or "").strip(),
                 "details": details if isinstance(details, dict) else ({} if details in (None, "") else {"text": str(details)}),
                 "offered_at": _iso(created)}
        canonical = json.dumps(terms, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        th = sha(canonical)
        entry = self.ledger.record(
            from_org, stream_id, actor, action_type, f"[handshake offered] {terms['summary']}", terms["resource"],
            "pending", {"handshake": {"id": hid, "role": "initiator", "counterparty": to_org, "terms_hash": th},
                        "terms": terms["details"]})
        with self._lock:
            self._db.execute(
                "INSERT INTO handshakes (handshake_id, from_org, to_org, from_stream, terms, terms_hash, "
                "from_entry_hash, status, created_at, expires_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (hid, from_org, to_org, stream_id, canonical, th, entry["entry_hash"], "offered",
                 _iso(created), _iso(created + timedelta(hours=expires_hours))))
            self._db.commit()
        return {"handshake_id": hid, "status": "offered", "terms": terms, "terms_hash": th,
                "your_entry_hash": entry["entry_hash"], "expires_at": _iso(created + timedelta(hours=expires_hours))}

    def inbox(self, org_id: str) -> list[dict]:
        rows = self._db.execute(
            "SELECT * FROM handshakes WHERE (to_org=? OR from_org=?) ORDER BY created_at DESC LIMIT 100",
            (org_id, org_id)).fetchall()
        out = []
        for r in rows:
            h = self._expire({k: r[k] for k in r.keys()})
            out.append({"handshake_id": h["handshake_id"], "direction": "incoming" if h["to_org"] == org_id else "outgoing",
                        "counterparty": h["from_org"] if h["to_org"] == org_id else h["to_org"],
                        "status": h["status"], "terms": json.loads(h["terms"]), "terms_hash": h["terms_hash"],
                        "expires_at": h["expires_at"], "decided_at": h["decided_at"]})
        return out

    def _decide_checks(self, hid: str, org_id: str) -> dict:
        h = self._get(hid)
        if not h or h["to_org"] != org_id:
            raise HandshakeError("no handshake with this ID is addressed to your organization")
        h = self._expire(h)
        if h["status"] != "offered":
            raise HandshakeError(f"handshake is already {h['status']}")
        return h

    def accept(self, hid: str, org_id: str, stream_id: str, actor: str, anchor_client=None) -> dict:
        h = self._decide_checks(hid, org_id)
        terms = json.loads(h["terms"])
        mine = self.ledger.record(
            org_id, stream_id, actor, terms["action_type"], f"[handshake accepted] {terms['summary']}",
            terms["resource"], "success",
            {"handshake": {"id": hid, "role": "counterparty", "counterparty": h["from_org"],
                           "terms_hash": h["terms_hash"], "initiator_entry_hash": h["from_entry_hash"]},
             "terms": terms["details"]})
        ph = pair_hash(h["terms_hash"], h["from_entry_hash"], mine["entry_hash"])
        self.ledger.record(
            h["from_org"], h["from_stream"], "Privi Handshake", "approval",
            f"[handshake confirmed by counterparty] {terms['summary']}", terms["resource"], "success",
            {"handshake": {"id": hid, "counterparty": org_id, "terms_hash": h["terms_hash"],
                           "counterparty_entry_hash": mine["entry_hash"], "pair_hash": ph}})
        anchor: dict[str, Any] = {"anchored": False}
        if anchor_client:
            try:
                r = anchor_client.anchor([ph], f"handshake {hid}")
                rc = next(x for x in r["receipts"] if x["hash"] == ph)
                anchor = {"anchored": True, "tx_hash": r["tx_hash"], "proof": rc["proof"],
                          "block_number": r.get("block_number"), "chain_id": r.get("chain_id")}
            except Exception as e:  # logs are still checkpointed on chain by the regular loop
                anchor = {"anchored": False, "reason": f"anchoring failed: {e}"}
        with self._lock:
            self._db.execute(
                "UPDATE handshakes SET status='accepted', to_stream=?, to_entry_hash=?, pair_hash=?, anchor=?, "
                "decided_at=? WHERE handshake_id=?",
                (stream_id, mine["entry_hash"], ph, json.dumps(anchor), _iso(_now()), hid))
            self._db.commit()
        return {"handshake_id": hid, "status": "accepted", "terms_hash": h["terms_hash"],
                "initiator_entry_hash": h["from_entry_hash"], "your_entry_hash": mine["entry_hash"],
                "pair_hash": ph, "onchain": anchor}

    def reject(self, hid: str, org_id: str, reason: str) -> dict:
        h = self._decide_checks(hid, org_id)
        terms = json.loads(h["terms"])
        self.ledger.record(h["from_org"], h["from_stream"], "Privi Handshake", "approval",
                           f"[handshake rejected by counterparty] {terms['summary']}", terms["resource"], "blocked",
                           {"handshake": {"id": hid, "counterparty": org_id, "reason": (reason or "")[:500]}})
        with self._lock:
            self._db.execute("UPDATE handshakes SET status='rejected', reason=?, decided_at=? WHERE handshake_id=?",
                             ((reason or "")[:500], _iso(_now()), hid))
            self._db.commit()
        return {"handshake_id": hid, "status": "rejected"}

    def public_status(self, hid: str) -> dict | None:
        """What anyone may see: parties, status, hashes and the on-chain seal; never the terms."""
        h = self._get(hid)
        if not h:
            return None
        h = self._expire(h)
        out: dict[str, Any] = {"handshake_id": hid, "status": h["status"], "from_org": h["from_org"],
                               "to_org": h["to_org"], "terms_hash": h["terms_hash"],
                               "initiator_entry_hash": h["from_entry_hash"], "counterparty_entry_hash": h["to_entry_hash"],
                               "pair_hash": h["pair_hash"], "created_at": h["created_at"], "decided_at": h["decided_at"]}
        if h["status"] == "accepted":
            a = self.ledger.find_entry(h["from_entry_hash"])
            b = self.ledger.find_entry(h["to_entry_hash"])
            out["both_entries_present"] = bool(a and b and a["org_id"] == h["from_org"] and b["org_id"] == h["to_org"])
            out["pair_hash_valid"] = pair_hash(h["terms_hash"], h["from_entry_hash"], h["to_entry_hash"]) == h["pair_hash"]
            out["onchain"] = json.loads(h["anchor"] or "{}")
        return out
