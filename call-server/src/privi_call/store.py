# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Call - https://priviflow.us - dariocanoy@priviflow.us
"""Agent directory, call credits, and the sealed call log.

The call log is append-only and hash-chained: each record's hash covers its public fields
and the previous record's hash, so changing or deleting any past call breaks every hash
after it. The head hash is anchored on chain every few minutes (see anchoring.py).
Private details (lead transcripts, full phone numbers) are kept beside the record and are
covered by the hash only as a SHA-256, so the public log can be shown without them.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
import time
from typing import Any

GENESIS = "0" * 64
PUBLIC_FIELDS = ("seq", "id", "ts", "channel", "caller", "callee", "tool", "status", "latency_ms",
                 "price_usd", "cost_usd", "args_sha256", "result_sha256", "detail_sha256", "prev_hash")

SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
  number TEXT PRIMARY KEY, name TEXT NOT NULL, endpoint TEXT NOT NULL, description TEXT NOT NULL,
  tags TEXT NOT NULL DEFAULT '[]', official INTEGER NOT NULL DEFAULT 0, owner_contact TEXT NOT NULL DEFAULT '',
  secret_sha256 TEXT NOT NULL DEFAULT '', calls INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS calls (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, ts REAL NOT NULL, channel TEXT NOT NULL,
  caller TEXT NOT NULL, callee TEXT NOT NULL, tool TEXT NOT NULL, status TEXT NOT NULL, latency_ms REAL NOT NULL,
  price_usd TEXT NOT NULL, cost_usd TEXT NOT NULL, args_sha256 TEXT NOT NULL, result_sha256 TEXT NOT NULL,
  detail_sha256 TEXT NOT NULL, detail TEXT NOT NULL, prev_hash TEXT NOT NULL, hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS credits (
  key_sha256 TEXT PRIMARY KEY, remaining INTEGER NOT NULL, bought INTEGER NOT NULL, created_at REAL NOT NULL,
  last_tx TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS usage (who TEXT NOT NULL, day TEXT NOT NULL, n INTEGER NOT NULL, PRIMARY KEY (who, day));
CREATE TABLE IF NOT EXISTS checkpoints (
  seq INTEGER PRIMARY KEY, hash TEXT NOT NULL, tx_hash TEXT NOT NULL, chain_id INTEGER, network TEXT,
  block_number INTEGER, proof TEXT NOT NULL, anchored_at REAL NOT NULL);
"""


def sha(data: Any) -> str:
    if isinstance(data, (bytes, bytearray)):
        b = bytes(data)
    elif isinstance(data, str):
        b = data.encode()
    else:
        b = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(b).hexdigest()


def record_hash(rec: dict) -> str:
    return sha({k: rec[k] for k in PUBLIC_FIELDS})


def mask_phone(n: str) -> str:
    d = "".join(c for c in n if c.isdigit())
    return f"phone ***-{d[-4:]}" if len(d) >= 4 else "phone (hidden)"


class Store:
    def __init__(self, path: str):
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(SCHEMA)
        self._lock = threading.Lock()

    # ---------------- directory ----------------

    def seed_official(self, agents: list[dict]) -> None:
        with self._lock:
            for a in agents:
                self._db.execute(
                    "INSERT INTO agents (number,name,endpoint,description,tags,official,created_at) VALUES (?,?,?,?,?,1,?) "
                    "ON CONFLICT(number) DO UPDATE SET name=excluded.name, endpoint=excluded.endpoint, "
                    "description=excluded.description, tags=excluded.tags, official=1",
                    (a["number"], a["name"], a["endpoint"], a["description"], json.dumps(a.get("tags", [])), time.time()))

    def register(self, name: str, endpoint: str, description: str, tags: list[str], contact: str) -> tuple[dict, str]:
        secret = "pas_" + secrets.token_urlsafe(24)
        with self._lock:
            if self._db.execute("SELECT 1 FROM agents WHERE endpoint=?", (endpoint,)).fetchone():
                raise ValueError("this endpoint is already on the Privi Call network")
            row = self._db.execute("SELECT MAX(CAST(number AS INTEGER)) m FROM agents WHERE official=0").fetchone()
            number = str(max(2000, (row["m"] or 1999) + 1))
            self._db.execute(
                "INSERT INTO agents (number,name,endpoint,description,tags,official,owner_contact,secret_sha256,created_at) "
                "VALUES (?,?,?,?,?,0,?,?,?)",
                (number, name, endpoint, description, json.dumps(tags), contact, sha(secret), time.time()))
        return self.agent(number), secret

    def unregister(self, number: str, secret: str) -> bool:
        with self._lock:
            cur = self._db.execute("DELETE FROM agents WHERE number=? AND official=0 AND secret_sha256=?",
                                   (number, sha(secret)))
            return cur.rowcount == 1

    def agent(self, number: str) -> dict | None:
        r = self._db.execute("SELECT * FROM agents WHERE number=?", (str(number).strip(),)).fetchone()
        return self._agent(r) if r else None

    @staticmethod
    def _agent(r: sqlite3.Row) -> dict:
        return {"number": r["number"], "name": r["name"], "endpoint": r["endpoint"], "description": r["description"],
                "tags": json.loads(r["tags"]), "official": bool(r["official"]), "calls": r["calls"]}

    def directory(self, query: str = "") -> list[dict]:
        rows = self._db.execute("SELECT * FROM agents ORDER BY official DESC, calls DESC, CAST(number AS INTEGER)").fetchall()
        out = [self._agent(r) for r in rows]
        q = query.strip().lower()
        if q:
            out = [a for a in out if q in (a["name"] + " " + a["description"] + " " + " ".join(a["tags"])).lower()]
        return out

    def bump_agent(self, number: str) -> None:
        with self._lock:
            self._db.execute("UPDATE agents SET calls=calls+1 WHERE number=?", (number,))

    # ---------------- free tier and credits ----------------

    def use_free(self, who: str, limit: int) -> bool:
        day = time.strftime("%Y-%m-%d", time.gmtime())
        with self._lock:
            r = self._db.execute("SELECT n FROM usage WHERE who=? AND day=?", (who, day)).fetchone()
            if r and r["n"] >= limit:
                return False
            self._db.execute("INSERT INTO usage (who,day,n) VALUES (?,?,1) ON CONFLICT(who,day) DO UPDATE SET n=n+1",
                             (who, day))
            return True

    def free_left(self, who: str, limit: int) -> int:
        day = time.strftime("%Y-%m-%d", time.gmtime())
        r = self._db.execute("SELECT n FROM usage WHERE who=? AND day=?", (who, day)).fetchone()
        return max(0, limit - (r["n"] if r else 0))

    def new_credit_key(self, credits: int, tx: str) -> str:
        key = "pck_" + secrets.token_urlsafe(24)
        with self._lock:
            self._db.execute("INSERT INTO credits (key_sha256,remaining,bought,created_at,last_tx) VALUES (?,?,?,?,?)",
                             (sha(key), credits, credits, time.time(), tx))
        return key

    def top_up(self, key: str, credits: int, tx: str) -> int | None:
        with self._lock:
            cur = self._db.execute("UPDATE credits SET remaining=remaining+?, bought=bought+?, last_tx=? WHERE key_sha256=?",
                                   (credits, credits, tx, sha(key)))
            if cur.rowcount != 1:
                return None
        return self.balance(key)

    def spend_credit(self, key: str) -> bool:
        with self._lock:
            cur = self._db.execute("UPDATE credits SET remaining=remaining-1 WHERE key_sha256=? AND remaining>0", (sha(key),))
            return cur.rowcount == 1

    def refund_credit(self, key: str) -> None:
        with self._lock:
            self._db.execute("UPDATE credits SET remaining=remaining+1 WHERE key_sha256=?", (sha(key),))

    def balance(self, key: str) -> int | None:
        r = self._db.execute("SELECT remaining FROM credits WHERE key_sha256=?", (sha(key),)).fetchone()
        return r["remaining"] if r else None

    # ---------------- call log ----------------

    def log(self, *, channel: str, caller: str, callee: str, tool: str, status: str, latency_ms: float = 0.0,
            price_usd: str = "0", cost_usd: str = "0", args: Any = None, result: Any = None,
            detail: dict | None = None, call_id: str | None = None) -> dict:
        detail = detail or {}
        with self._lock:
            last = self._db.execute("SELECT seq, hash FROM calls ORDER BY seq DESC LIMIT 1").fetchone()
            rec = {"seq": (last["seq"] + 1) if last else 1,
                   "id": call_id or "call_" + secrets.token_hex(8),
                   "ts": round(time.time(), 3), "channel": channel, "caller": caller[:80], "callee": callee[:80],
                   "tool": tool[:80], "status": status[:40], "latency_ms": round(float(latency_ms), 1),
                   "price_usd": str(price_usd), "cost_usd": str(cost_usd),
                   "args_sha256": sha(args if args is not None else ""),
                   "result_sha256": sha(result if result is not None else ""),
                   "detail_sha256": sha(detail), "prev_hash": last["hash"] if last else GENESIS}
            rec["hash"] = record_hash(rec)
            if self._db.execute("SELECT 1 FROM calls WHERE id=?", (rec["id"],)).fetchone():
                rec["id"] = f"{rec['id']}.{rec['seq']}"   # same phone call, later turn
                rec["hash"] = record_hash(rec)
            self._db.execute(
                "INSERT INTO calls (seq,id,ts,channel,caller,callee,tool,status,latency_ms,price_usd,cost_usd,args_sha256,"
                "result_sha256,detail_sha256,detail,prev_hash,hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (rec["seq"], rec["id"], rec["ts"], rec["channel"], rec["caller"], rec["callee"], rec["tool"], rec["status"],
                 rec["latency_ms"], rec["price_usd"], rec["cost_usd"], rec["args_sha256"], rec["result_sha256"],
                 rec["detail_sha256"], json.dumps(detail), rec["prev_hash"], rec["hash"]))
        return rec

    @staticmethod
    def _public(r: sqlite3.Row) -> dict:
        return {k: r[k] for k in (*PUBLIC_FIELDS, "hash")}

    def calls(self, limit: int = 50, number: str = "", channel: str = "", private: bool = False,
              before_seq: int | None = None) -> list[dict]:
        sql, args = "SELECT * FROM calls WHERE 1=1", []
        if number:
            sql += " AND (callee=? OR caller=?)"
            args += [number, number]
        if channel:
            sql += " AND channel=?"
            args.append(channel)
        if before_seq:
            sql += " AND seq<?"
            args.append(before_seq)
        sql += " ORDER BY seq DESC LIMIT ?"
        args.append(max(1, min(int(limit), 500)))
        out = []
        for r in self._db.execute(sql, args).fetchall():
            d = self._public(r)
            if private:
                d["detail"] = json.loads(r["detail"])
            out.append(d)
        return out

    def call(self, call_id: str) -> dict | None:
        r = self._db.execute("SELECT * FROM calls WHERE id=?", (call_id,)).fetchone()
        return self._public(r) if r else None

    def head(self) -> dict | None:
        r = self._db.execute("SELECT seq, hash FROM calls ORDER BY seq DESC LIMIT 1").fetchone()
        return {"seq": r["seq"], "hash": r["hash"]} if r else None

    def verify_chain(self) -> dict:
        prev, n = GENESIS, 0
        for r in self._db.execute("SELECT * FROM calls ORDER BY seq"):
            rec = self._public(r)
            if rec["prev_hash"] != prev:
                return {"valid": False, "records": n, "broken_at_seq": rec["seq"], "reason": "prev_hash does not link"}
            if record_hash(rec) != rec["hash"]:
                return {"valid": False, "records": n, "broken_at_seq": rec["seq"], "reason": "record was altered"}
            if sha(json.loads(r["detail"])) != rec["detail_sha256"]:
                return {"valid": False, "records": n, "broken_at_seq": rec["seq"], "reason": "private detail was altered"}
            prev, n = rec["hash"], n + 1
        return {"valid": True, "records": n, "head_hash": prev}

    def stats(self) -> dict:
        now = time.time()
        q = lambda sql, *a: self._db.execute(sql, a).fetchone()[0]
        return {"calls_total": q("SELECT COUNT(*) FROM calls"),
                "calls_24h": q("SELECT COUNT(*) FROM calls WHERE ts>?", now - 86400),
                "agent_calls_24h": q("SELECT COUNT(*) FROM calls WHERE ts>? AND channel='agent'", now - 86400),
                "phone_calls_24h": q("SELECT COUNT(DISTINCT substr(id,1,instr(id||'.', '.')-1)) FROM calls WHERE ts>? AND channel='phone'", now - 86400),
                "median_latency_ms_24h": self._median(now - 86400),
                "agents_on_network": q("SELECT COUNT(*) FROM agents"),
                "credits_sold": q("SELECT COALESCE(SUM(bought),0) FROM credits")}

    def _median(self, since: float) -> float | None:
        v = [r[0] for r in self._db.execute(
            "SELECT latency_ms FROM calls WHERE ts>? AND channel='agent' AND latency_ms>0 ORDER BY latency_ms", (since,))]
        return v[len(v) // 2] if v else None

    # ---------------- on-chain checkpoints ----------------

    def last_checkpoint(self) -> dict | None:
        r = self._db.execute("SELECT * FROM checkpoints ORDER BY seq DESC LIMIT 1").fetchone()
        if not r:
            return None
        d = dict(r)
        d["proof"] = json.loads(d["proof"])
        return d

    def add_checkpoint(self, seq: int, hash_hex: str, receipt: dict) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO checkpoints (seq,hash,tx_hash,chain_id,network,block_number,proof,anchored_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (seq, hash_hex, receipt.get("tx_hash", ""), receipt.get("chain_id"), receipt.get("network"),
                 receipt.get("block_number"), json.dumps(receipt.get("proof", [])), time.time()))


def anchor_head(store: Store, client) -> dict | None:
    """Anchor the current head of the call log if it moved since the last checkpoint."""
    head = store.head()
    last = store.last_checkpoint()
    if not head or (last and last["seq"] >= head["seq"]):
        return None
    res = client.anchor([head["hash"]], f"Privi Call log head #{head['seq']}")
    proof = next((r.get("proof", []) for r in res.get("receipts", []) if r.get("hash") == head["hash"]), [])
    store.add_checkpoint(head["seq"], head["hash"], {**res, "proof": proof})
    return store.last_checkpoint()
