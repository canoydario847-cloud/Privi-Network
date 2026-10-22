"""Local index of anchors. The chain is the source of truth; this only remembers
which batch, transaction and Merkle proof belong to each hash so it can be found."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS batches (
    batch_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    root         TEXT NOT NULL,
    tx_hash      TEXT,
    status       TEXT NOT NULL,          -- sending | pending | confirmed | failed
    block_number INTEGER,
    block_time   INTEGER,
    label        TEXT NOT NULL DEFAULT '',
    client       TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    error        TEXT
);
CREATE TABLE IF NOT EXISTS leaves (
    leaf      TEXT NOT NULL,
    batch_id  INTEGER NOT NULL REFERENCES batches(batch_id),
    proof     TEXT NOT NULL,
    PRIMARY KEY (leaf, batch_id)
);
CREATE INDEX IF NOT EXISTS idx_leaves_leaf ON leaves (leaf);
"""


class AnchorStore:
    # Anchors made before Privi moved to Base were all on the Privi EVM Devnet.
    LEGACY_CHAIN_ID = 262144

    def __init__(self, path: str = "anchor.db", chain_id: int | None = None):
        self._lock = threading.Lock()
        self.chain_id = chain_id
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)
        cols = {r[1] for r in self._db.execute("PRAGMA table_info(batches)")}
        if "chain_id" not in cols:  # migrate: remember which chain each anchor lives on
            self._db.execute("ALTER TABLE batches ADD COLUMN chain_id INTEGER")
            self._db.execute("UPDATE batches SET chain_id=? WHERE chain_id IS NULL", (self.LEGACY_CHAIN_ID,))
        self._db.commit()

    def new_batch(self, root: str, proofs: dict[str, list[str]], label: str, client: str) -> int:
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO batches (root, status, label, client, created_at, chain_id) VALUES (?, 'sending', ?, ?, ?, ?)",
                (root, label, client, datetime.now(timezone.utc).isoformat(timespec="seconds"), self.chain_id),
            )
            bid = cur.lastrowid
            self._db.executemany("INSERT INTO leaves (leaf, batch_id, proof) VALUES (?,?,?)",
                                 [(leaf, bid, json.dumps(p)) for leaf, p in proofs.items()])
            self._db.commit()
            return bid

    def update_batch(self, batch_id: int, **fields) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        with self._lock:
            self._db.execute(f"UPDATE batches SET {cols} WHERE batch_id=?", (*fields.values(), batch_id))
            self._db.commit()

    def batch(self, batch_id: int) -> dict | None:
        r = self._db.execute("SELECT * FROM batches WHERE batch_id=?", (batch_id,)).fetchone()
        return dict(r) if r else None

    def find_leaf(self, leaf: str) -> dict | None:
        """Best record for a hash: one on the current chain first, then confirmed, then the oldest attempt."""
        r = self._db.execute(
            """SELECT l.leaf, l.proof, b.* FROM leaves l JOIN batches b USING (batch_id)
               WHERE l.leaf=? ORDER BY (b.chain_id IS ?) DESC, (b.status='confirmed') DESC, b.batch_id ASC LIMIT 1""",
            (leaf, self.chain_id),
        ).fetchone()
        if not r:
            return None
        d = dict(r)
        d["proof"] = json.loads(d["proof"])
        return d

    def sent_since(self, seconds: int) -> int:
        """Anchor transactions attempted on the current chain in the last `seconds` (gas budget)."""
        since = datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() - seconds, timezone.utc).isoformat(timespec="seconds")
        return self._db.execute("SELECT COUNT(*) FROM batches WHERE chain_id IS ? AND created_at >= ? AND status != 'failed'",
                                (self.chain_id, since)).fetchone()[0]

    def pending_on_current_chain(self, limit: int = 50) -> list[dict]:
        """Batches sent on the current chain whose receipt was not seen in time (oldest first)."""
        rows = self._db.execute("SELECT * FROM batches WHERE chain_id IS ? AND status='pending' AND tx_hash IS NOT NULL "
                                "ORDER BY batch_id ASC LIMIT ?", (self.chain_id, limit)).fetchall()
        return [dict(r) for r in rows]

    def confirmed_on_current_chain(self) -> int:
        return self._db.execute("SELECT COUNT(*) FROM batches WHERE chain_id IS ? AND status='confirmed'",
                                (self.chain_id,)).fetchone()[0]

    def stats(self) -> dict:
        r = self._db.execute(
            "SELECT COUNT(*) AS batches, SUM(status='confirmed') AS confirmed, "
            "MAX(CASE WHEN status='confirmed' THEN block_time END) AS last_time FROM batches WHERE chain_id IS ?",
            (self.chain_id,)).fetchone()
        n = self._db.execute("SELECT COUNT(*) FROM leaves JOIN batches USING (batch_id) WHERE chain_id IS ?",
                             (self.chain_id,)).fetchone()[0]
        return {"batches": r["batches"] or 0, "confirmed_batches": r["confirmed"] or 0, "hashes": n,
                "last_confirmed_block_time": r["last_time"]}
