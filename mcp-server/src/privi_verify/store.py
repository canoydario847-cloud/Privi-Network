"""Lot records with a per-lot hash chain.

Every event stores a SHA-256 fingerprint of its own contents plus the fingerprint
of the event before it in the same lot. Changing or deleting any past event
breaks every fingerprint after it, so tampering is detectable.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

GENESIS = "0" * 64

EVENT_TYPES = (
    "received",      # raw material or component arrived
    "produced",      # lot was made or transformed
    "inspected",     # quality check
    "shipped",       # left this site
    "transferred",   # changed custody without shipping (e.g. internal move)
    "recalled",      # flagged for recall
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    lot_code      TEXT NOT NULL,
    seq           INTEGER NOT NULL,
    event_type    TEXT NOT NULL,
    occurred_at   TEXT NOT NULL,
    location      TEXT NOT NULL,
    actor         TEXT NOT NULL,
    product       TEXT NOT NULL DEFAULT '',
    quantity      TEXT NOT NULL DEFAULT '',
    notes         TEXT NOT NULL DEFAULT '',
    prev_hash     TEXT NOT NULL,
    record_hash   TEXT NOT NULL UNIQUE,
    UNIQUE (lot_code, seq)
);
CREATE INDEX IF NOT EXISTS idx_events_lot ON events (lot_code, seq);
"""

HASHED_FIELDS = (
    "lot_code", "seq", "event_type", "occurred_at", "location",
    "actor", "product", "quantity", "notes", "prev_hash",
)


def fingerprint(fields: dict[str, Any]) -> str:
    """SHA-256 over a canonical JSON encoding of the hashed fields."""
    canonical = json.dumps(
        {k: fields[k] for k in HASHED_FIELDS},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def normalize_lot(lot_code: str) -> str:
    code = (lot_code or "").strip()
    if not code or len(code) > 128:
        raise ValueError("lot_code must be 1-128 characters")
    return code


@dataclass
class ChainCheck:
    valid: bool
    event_count: int
    broken_at_seq: int | None = None
    reason: str | None = None


class LotStore:
    def __init__(self, path: str = "privi.db"):
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)
        self._db.commit()

    # ---- writes -------------------------------------------------------

    def record_event(
        self,
        lot_code: str,
        event_type: str,
        location: str,
        actor: str,
        product: str = "",
        quantity: str = "",
        notes: str = "",
        occurred_at: str | None = None,
    ) -> dict[str, Any]:
        lot_code = normalize_lot(lot_code)
        if event_type not in EVENT_TYPES:
            raise ValueError(f"event_type must be one of: {', '.join(EVENT_TYPES)}")
        if not location.strip() or not actor.strip():
            raise ValueError("location and actor are required")
        occurred_at = occurred_at or datetime.now(timezone.utc).isoformat(timespec="seconds")

        with self._lock:
            last = self._db.execute(
                "SELECT seq, record_hash FROM events WHERE lot_code=? ORDER BY seq DESC LIMIT 1",
                (lot_code,),
            ).fetchone()
            seq = (last["seq"] + 1) if last else 1
            prev_hash = last["record_hash"] if last else GENESIS
            fields = {
                "lot_code": lot_code, "seq": seq, "event_type": event_type,
                "occurred_at": occurred_at, "location": location.strip(),
                "actor": actor.strip(), "product": product.strip(),
                "quantity": str(quantity).strip(), "notes": notes.strip(),
                "prev_hash": prev_hash,
            }
            fields["record_hash"] = fingerprint(fields)
            self._db.execute(
                f"INSERT INTO events ({', '.join(fields)}) VALUES ({', '.join('?' * len(fields))})",
                tuple(fields.values()),
            )
            self._db.commit()
        return fields

    # ---- reads --------------------------------------------------------

    def events(self, lot_code: str) -> list[dict[str, Any]]:
        lot_code = normalize_lot(lot_code)
        rows = self._db.execute(
            "SELECT * FROM events WHERE lot_code=? ORDER BY seq", (lot_code,)
        ).fetchall()
        return [{k: r[k] for k in r.keys() if k != "id"} for r in rows]

    def exists(self, lot_code: str) -> bool:
        lot_code = normalize_lot(lot_code)
        return self._db.execute(
            "SELECT 1 FROM events WHERE lot_code=? LIMIT 1", (lot_code,)
        ).fetchone() is not None

    def find_fingerprint(self, record_hash: str) -> dict[str, Any] | None:
        h = (record_hash or "").strip().lower().removeprefix("0x")
        if len(h) != 64 or any(c not in "0123456789abcdef" for c in h):
            raise ValueError("fingerprint must be a 64-character hex SHA-256")
        r = self._db.execute(
            "SELECT lot_code, seq, event_type, occurred_at FROM events WHERE record_hash=?", (h,)
        ).fetchone()
        return dict(r) if r else None

    @staticmethod
    def check_chain(events: list[dict[str, Any]]) -> ChainCheck:
        prev = GENESIS
        for i, ev in enumerate(events, start=1):
            if ev["seq"] != i:
                return ChainCheck(False, len(events), ev["seq"], "event sequence has a gap")
            if ev["prev_hash"] != prev:
                return ChainCheck(False, len(events), ev["seq"], "link to previous event does not match")
            if fingerprint(ev) != ev["record_hash"]:
                return ChainCheck(False, len(events), ev["seq"], "event contents were changed after recording")
            prev = ev["record_hash"]
        return ChainCheck(True, len(events))

    def summary(self, lot_code: str) -> dict[str, Any] | None:
        evs = self.events(lot_code)
        if not evs:
            return None
        check = self.check_chain(evs)
        first, last = evs[0], evs[-1]
        return {
            "lot_code": first["lot_code"],
            "product": next((e["product"] for e in reversed(evs) if e["product"]), ""),
            "event_count": len(evs),
            "first_event": {k: first[k] for k in ("event_type", "occurred_at", "location")},
            "latest_event": {k: last[k] for k in ("event_type", "occurred_at", "location", "actor")},
            "recalled": any(e["event_type"] == "recalled" for e in evs),
            "integrity": {
                "valid": check.valid,
                "broken_at_seq": check.broken_at_seq,
                "reason": check.reason,
                "head_fingerprint": last["record_hash"],
            },
        }
