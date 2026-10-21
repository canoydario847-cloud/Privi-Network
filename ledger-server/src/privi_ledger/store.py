"""Append-only, hash-chained action logs for AI agents.

An organization owns streams (usually one per agent). Each entry's SHA-256
fingerprint covers its contents and the previous entry's fingerprint in the
same stream, so editing, deleting or reordering history is detectable.
Organization API keys are stored only as SHA-256 hashes.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

GENESIS = "0" * 64
MAX_DETAILS_BYTES = 16_384
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")

ACTION_TYPES = (
    "tool_call",     # agent called a tool or API
    "data_access",   # read or exported data
    "data_change",   # created, updated or deleted data
    "payment",       # sent or received money
    "message",       # sent a message, email or post
    "decision",      # made or recommended a decision
    "approval",      # a human approved or rejected an agent action
    "error",         # something failed
    "other",
)
OUTCOMES = ("success", "failure", "pending", "blocked")

SCHEMA = """
CREATE TABLE IF NOT EXISTS orgs (
    org_id      TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    key_hash    TEXT NOT NULL UNIQUE,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS entries (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id        TEXT NOT NULL REFERENCES orgs(org_id),
    stream_id     TEXT NOT NULL,
    seq           INTEGER NOT NULL,
    recorded_at   TEXT NOT NULL,
    actor         TEXT NOT NULL,
    action_type   TEXT NOT NULL,
    summary       TEXT NOT NULL,
    resource      TEXT NOT NULL DEFAULT '',
    outcome       TEXT NOT NULL,
    details       TEXT NOT NULL DEFAULT '{}',
    prev_hash     TEXT NOT NULL,
    entry_hash    TEXT NOT NULL UNIQUE,
    UNIQUE (org_id, stream_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_entries_stream ON entries (org_id, stream_id, seq);
"""

HASHED_FIELDS = (
    "org_id", "stream_id", "seq", "recorded_at", "actor", "action_type",
    "summary", "resource", "outcome", "details", "prev_hash",
)


def fingerprint(fields: dict[str, Any]) -> str:
    canonical = json.dumps({k: fields[k] for k in HASHED_FIELDS}, sort_keys=True,
                           separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def hash_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def check_id(value: str, what: str) -> str:
    v = (value or "").strip()
    if not ID_RE.match(v):
        raise ValueError(f"{what} must be 1-128 characters: letters, digits, . _ : -")
    return v


def canonical_details(details: Any) -> str:
    if details in (None, ""):
        details = {}
    if isinstance(details, str):
        try:
            details = json.loads(details)
        except ValueError:
            details = {"text": details}
    if not isinstance(details, dict):
        raise ValueError("details must be a JSON object")
    s = json.dumps(details, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if len(s.encode()) > MAX_DETAILS_BYTES:
        raise ValueError(f"details must be under {MAX_DETAILS_BYTES} bytes")
    return s


@dataclass
class ChainCheck:
    valid: bool
    entry_count: int
    broken_at_seq: int | None = None
    reason: str | None = None


class Ledger:
    def __init__(self, path: str = "ledger.db"):
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)
        self._db.commit()
        self.on_record = None   # optional callback(org_id, entry) used by Privi Live; never allowed to break recording

    # ---- organizations ------------------------------------------------

    def create_org(self, name: str) -> dict[str, str]:
        name = (name or "").strip()
        if not name or len(name) > 200:
            raise ValueError("organization name must be 1-200 characters")
        org_id = "org_" + secrets.token_hex(8)
        api_key = "plk_" + secrets.token_urlsafe(32)
        with self._lock:
            self._db.execute(
                "INSERT INTO orgs (org_id, name, key_hash, created_at) VALUES (?,?,?,?)",
                (org_id, name, hash_key(api_key), _now()),
            )
            self._db.commit()
        return {"org_id": org_id, "name": name, "api_key": api_key}

    def ensure_org(self, name: str, api_key: str) -> dict[str, str]:
        """Create an organization with a given API key unless that key already has one (idempotent)."""
        if len(api_key or "") < 24:
            raise ValueError("bootstrap API key must be at least 24 characters")
        existing = self.org_for_key(api_key)
        if existing:
            return existing
        org_id = "org_" + secrets.token_hex(8)
        with self._lock:
            self._db.execute("INSERT INTO orgs (org_id, name, key_hash, created_at) VALUES (?,?,?,?)",
                             (org_id, name.strip(), hash_key(api_key), _now()))
            self._db.commit()
        return {"org_id": org_id, "name": name.strip()}

    def import_entries(self, org_id: str, stream_id: str, entries: list[dict]) -> int:
        """Append entries to a stream only if it is empty (idempotent import). Returns entries added."""
        if self.entries(org_id, stream_id, limit=1):
            return 0
        for e in entries:
            self.record(org_id, stream_id, e["actor"], e["action_type"], e["summary"],
                        e.get("resource", ""), e.get("outcome", "success"), e.get("details"))
        return len(entries)

    def org_for_key(self, api_key: str) -> dict | None:
        if not api_key:
            return None
        r = self._db.execute("SELECT org_id, name FROM orgs WHERE key_hash=?", (hash_key(api_key),)).fetchone()
        return dict(r) if r else None

    def org_exists(self, org_id: str) -> bool:
        return self._db.execute("SELECT 1 FROM orgs WHERE org_id=?", (org_id,)).fetchone() is not None

    # ---- entries ------------------------------------------------------

    def record(self, org_id: str, stream_id: str, actor: str, action_type: str, summary: str,
               resource: str = "", outcome: str = "success", details: Any = None) -> dict[str, Any]:
        stream_id = check_id(stream_id, "stream_id")
        if action_type not in ACTION_TYPES:
            raise ValueError(f"action_type must be one of: {', '.join(ACTION_TYPES)}")
        if outcome not in OUTCOMES:
            raise ValueError(f"outcome must be one of: {', '.join(OUTCOMES)}")
        actor, summary = (actor or "").strip(), (summary or "").strip()
        if not actor or not summary:
            raise ValueError("actor and summary are required")
        if len(summary) > 2000:
            raise ValueError("summary must be under 2000 characters")
        det = canonical_details(details)

        with self._lock:
            last = self._db.execute(
                "SELECT seq, entry_hash FROM entries WHERE org_id=? AND stream_id=? ORDER BY seq DESC LIMIT 1",
                (org_id, stream_id),
            ).fetchone()
            fields = {
                "org_id": org_id, "stream_id": stream_id,
                "seq": (last["seq"] + 1) if last else 1,
                "recorded_at": _now(), "actor": actor, "action_type": action_type,
                "summary": summary, "resource": (resource or "").strip(), "outcome": outcome,
                "details": det, "prev_hash": last["entry_hash"] if last else GENESIS,
            }
            fields["entry_hash"] = fingerprint(fields)
            self._db.execute(
                f"INSERT INTO entries ({', '.join(fields)}) VALUES ({', '.join('?' * len(fields))})",
                tuple(fields.values()),
            )
            self._db.commit()
        entry = _public(fields)
        if self.on_record:
            try:
                self.on_record(org_id, entry)
            except Exception:
                pass
        return entry

    def entries(self, org_id: str, stream_id: str, after_seq: int = 0, limit: int | None = None) -> list[dict]:
        stream_id = check_id(stream_id, "stream_id")
        sql = "SELECT * FROM entries WHERE org_id=? AND stream_id=? AND seq>? ORDER BY seq"
        args: list[Any] = [org_id, stream_id, after_seq]
        if limit:
            sql += " LIMIT ?"
            args.append(limit)
        return [{k: r[k] for k in r.keys() if k != "id"} for r in self._db.execute(sql, args).fetchall()]

    def streams(self, org_id: str) -> list[dict]:
        rows = self._db.execute(
            "SELECT stream_id, COUNT(*) AS entries, MAX(recorded_at) AS last_recorded_at "
            "FROM entries WHERE org_id=? GROUP BY stream_id ORDER BY stream_id", (org_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def find_entry(self, entry_hash: str) -> dict | None:
        h = (entry_hash or "").strip().lower().removeprefix("0x")
        if len(h) != 64 or any(c not in "0123456789abcdef" for c in h):
            raise ValueError("entry hash must be a 64-character hex SHA-256")
        r = self._db.execute(
            "SELECT org_id, stream_id, seq, recorded_at, action_type, outcome FROM entries WHERE entry_hash=?", (h,)
        ).fetchone()
        return dict(r) if r else None

    def heads(self) -> list[tuple[str, int, str]]:
        """(chain_key, seq, entry_hash) of the latest entry in every stream; chain_key = org_id/stream_id."""
        rows = self._db.execute(
            """SELECT e.org_id, e.stream_id, e.seq, e.entry_hash FROM entries e
               JOIN (SELECT org_id, stream_id, MAX(seq) AS s FROM entries GROUP BY org_id, stream_id) m
               ON e.org_id=m.org_id AND e.stream_id=m.stream_id AND e.seq=m.s""").fetchall()
        return [(f"{r['org_id']}/{r['stream_id']}", r["seq"], r["entry_hash"]) for r in rows]

    def hash_at(self, org_id: str, stream_id: str, seq: int) -> str | None:
        r = self._db.execute("SELECT entry_hash FROM entries WHERE org_id=? AND stream_id=? AND seq=?",
                             (org_id, stream_id, seq)).fetchone()
        return r["entry_hash"] if r else None

    @staticmethod
    def check_chain(entries: list[dict]) -> ChainCheck:
        prev = GENESIS
        for i, e in enumerate(entries, start=1):
            if e["seq"] != i:
                return ChainCheck(False, len(entries), e["seq"], "an entry is missing (sequence gap)")
            if e["prev_hash"] != prev:
                return ChainCheck(False, len(entries), e["seq"], "link to the previous entry does not match")
            if fingerprint(e) != e["entry_hash"]:
                return ChainCheck(False, len(entries), e["seq"], "entry contents were changed after recording")
            prev = e["entry_hash"]
        return ChainCheck(True, len(entries))

    def audit(self, org_id: str, stream_id: str) -> dict[str, Any] | None:
        evs = self.entries(org_id, stream_id)
        if not evs:
            return None
        c = self.check_chain(evs)
        counts: dict[str, int] = {}
        for e in evs:
            counts[e["action_type"]] = counts.get(e["action_type"], 0) + 1
        return {
            "org_id": org_id, "stream_id": evs[0]["stream_id"],
            "intact": c.valid, "broken_at_seq": c.broken_at_seq, "reason": c.reason,
            "entry_count": c.entry_count,
            "first_recorded_at": evs[0]["recorded_at"], "last_recorded_at": evs[-1]["recorded_at"],
            "head_hash": evs[-1]["entry_hash"],
            "action_counts": counts,
            "failures": sum(1 for e in evs if e["outcome"] == "failure"),
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _public(fields: dict) -> dict:
    out = dict(fields)
    out["details"] = json.loads(out["details"])
    return out
