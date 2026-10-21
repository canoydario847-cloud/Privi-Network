"""Privi Guard service: metering, payment, signed receipts and their anchoring.

Every check returns a receipt: a signed statement that Privi inspected content with this SHA-256, in this
direction, at this time, with this verdict. Privi never stores the content itself. Receipts are batched every
few minutes into a Merkle tree whose root is written to the Privi Ledger transparency log (anchored on-chain),
so a company can later prove that its agent checked what it acted on, and when.

Billing per check (1 unit = up to 100,000 characters):
  1. organizations get GUARD_FREE_MONTHLY units free each month,
  2. then prepaid credits (guard_buy_credits, cheaper per check),
  3. otherwise 1 cent per check in USDC via x402 (no account needed; texts up to one unit).
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
import time
from datetime import datetime, timezone

from .guard_engine import ENGINE_VERSION, MAX_CHARS, inspect, units_for

GUARD_ORG_ID = "org_6a4d6a4d6a4d6a4d"
GUARD_STREAM = "guard-receipts"
FREE_MONTHLY = int(os.getenv("GUARD_FREE_MONTHLY", "1000"))
PRICE_PER_CHECK = os.getenv("GUARD_PRICE_PER_CHECK", "0.01")
PACKS = {"1k": (1_000, "7"), "10k": (10_000, "50"), "100k": (100_000, "300")}   # units, USDC
BATCH_MAX = 50_000

SCHEMA = """
CREATE TABLE IF NOT EXISTS guard_checks (
    check_id     TEXT PRIMARY KEY,
    at           TEXT NOT NULL,
    org_id       TEXT,
    direction    TEXT NOT NULL,
    verdict      TEXT NOT NULL,
    risk         INTEGER NOT NULL,
    units        INTEGER NOT NULL,
    paid_by      TEXT NOT NULL,
    receipt      TEXT NOT NULL,
    receipt_hash TEXT NOT NULL,
    signature    TEXT NOT NULL,
    batch_id     INTEGER
);
CREATE INDEX IF NOT EXISTS idx_guard_batch ON guard_checks (batch_id);
CREATE TABLE IF NOT EXISTS guard_usage (org_id TEXT NOT NULL, month TEXT NOT NULL, units INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (org_id, month));
CREATE TABLE IF NOT EXISTS guard_credits (org_id TEXT PRIMARY KEY, balance INTEGER NOT NULL DEFAULT 0,
    purchased INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS guard_purchases (id INTEGER PRIMARY KEY AUTOINCREMENT, org_id TEXT NOT NULL, pack TEXT NOT NULL,
    units INTEGER NOT NULL, usd TEXT NOT NULL, at TEXT NOT NULL, tx TEXT);
CREATE TABLE IF NOT EXISTS guard_batches (batch_id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, root TEXT NOT NULL,
    count INTEGER NOT NULL, ledger_seq INTEGER, ledger_hash TEXT);
CREATE TABLE IF NOT EXISTS guard_daily (day TEXT NOT NULL, direction TEXT NOT NULL, verdict TEXT NOT NULL, paid_by TEXT NOT NULL,
    n INTEGER NOT NULL DEFAULT 0, units INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (day, direction, verdict, paid_by));
"""


class GuardError(Exception):
    pass


class NeedPayment(Exception):
    def __init__(self, units: int, reason: str):
        super().__init__(reason)
        self.units = units


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime | None = None) -> str:
    return (d or _now()).isoformat(timespec="seconds")


def canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _pair(a: str, b: str) -> str:
    x, y = sorted((a, b))
    return hashlib.sha256(bytes.fromhex(x) + bytes.fromhex(y)).hexdigest()


def merkle_root_and_proof(leaves: list[str], index: int | None = None) -> tuple[str, list[str]]:
    """Sorted-pair SHA-256 Merkle tree (an odd node is carried up). Returns the root and, for `index`, its proof."""
    if not leaves:
        raise ValueError("no leaves")
    level, proof, i = list(leaves), [], index
    while len(level) > 1:
        nxt = []
        for j in range(0, len(level), 2):
            if j + 1 < len(level):
                if i is not None and j <= i <= j + 1:
                    proof.append(level[j + 1] if i == j else level[j])
                nxt.append(_pair(level[j], level[j + 1]))
            else:
                nxt.append(level[j])
        if i is not None:
            i //= 2
        level = nxt
    return level[0], proof


def verify_proof(leaf: str, proof: list[str], root: str) -> bool:
    h = leaf
    for p in proof:
        h = _pair(h, p)
    return h == root


class Guard:
    def __init__(self, ledger, passports, public_url: str):
        self.ledger, self.passports = ledger, passports
        self.db, self.lock = ledger._db, ledger._lock
        self.public_url = public_url.rstrip("/")
        with self.lock:
            self.db.executescript(SCHEMA)
            if not self.db.execute("SELECT 1 FROM orgs WHERE org_id=?", (GUARD_ORG_ID,)).fetchone():
                self.db.execute("INSERT INTO orgs (org_id, name, key_hash, created_at) VALUES (?,?,?,?)",
                                (GUARD_ORG_ID, "Privi Guard (receipt batches)", "!" + secrets.token_hex(32), _iso()))
            self.db.commit()

    # ---- billing --------------------------------------------------------

    @staticmethod
    def _month() -> str:
        return _now().strftime("%Y-%m")

    def bill(self, org_id: str | None, units: int) -> str:
        """Charge `units` to the organization's free allowance, then its credits. Raises NeedPayment otherwise."""
        if not org_id:
            raise NeedPayment(units, "no organization key: pay per check with x402, or get a free key with ledger_signup")
        m = self._month()
        with self.lock:
            r = self.db.execute("SELECT units FROM guard_usage WHERE org_id=? AND month=?", (org_id, m)).fetchone()
            used = r["units"] if r else 0
            if used + units <= FREE_MONTHLY:
                paid_by = "free"
            else:
                c = self.db.execute("SELECT balance FROM guard_credits WHERE org_id=?", (org_id,)).fetchone()
                if not c or c["balance"] < units:
                    raise NeedPayment(units, f"free allowance of {FREE_MONTHLY} checks this month is used and credits are "
                                             f"{c['balance'] if c else 0}; buy credits with guard_buy_credits or pay per check via x402")
                self.db.execute("UPDATE guard_credits SET balance = balance - ?, updated_at=? WHERE org_id=?",
                                (units, _iso(), org_id))
                paid_by = "credits"
            self.db.execute("INSERT INTO guard_usage (org_id, month, units) VALUES (?,?,?) ON CONFLICT(org_id, month) "
                            "DO UPDATE SET units = units + ?", (org_id, m, units, units))
            self.db.commit()
        return paid_by

    def add_credits(self, org_id: str, pack: str, tx: str | None = None) -> dict:
        if pack not in PACKS:
            raise GuardError(f"pack must be one of {', '.join(PACKS)}")
        units, usd = PACKS[pack]
        with self.lock:
            self.db.execute("INSERT INTO guard_credits (org_id, balance, purchased, updated_at) VALUES (?,?,?,?) "
                            "ON CONFLICT(org_id) DO UPDATE SET balance = balance + ?, purchased = purchased + ?, updated_at=?",
                            (org_id, units, units, _iso(), units, units, _iso()))
            self.db.execute("INSERT INTO guard_purchases (org_id, pack, units, usd, at, tx) VALUES (?,?,?,?,?,?)",
                            (org_id, pack, units, usd, _iso(), tx))
            self.db.commit()
        try:
            self.ledger.record(org_id, "privi-billing", "Privi Guard", "payment", f"Guard credits purchased: {units} checks, ${usd} USDC",
                               "guard_buy_credits", "success", {"pack": pack, "units": units, "tx": tx})
        except ValueError:
            pass
        return {"purchased_units": units, "paid_usdc": usd, **self.balance(org_id)}

    def balance(self, org_id: str) -> dict:
        with self.lock:
            r = self.db.execute("SELECT units FROM guard_usage WHERE org_id=? AND month=?", (org_id, self._month())).fetchone()
            c = self.db.execute("SELECT balance, purchased FROM guard_credits WHERE org_id=?", (org_id,)).fetchone()
        used = r["units"] if r else 0
        return {"free_monthly": FREE_MONTHLY, "used_this_month": used, "free_left_this_month": max(0, FREE_MONTHLY - used),
                "credits": c["balance"] if c else 0, "credits_purchased_total": c["purchased"] if c else 0}

    # ---- checks and receipts -------------------------------------------------

    def check(self, text: str, direction: str, source: str | None, org_id: str | None, paid_by: str) -> dict:
        if len(text) > MAX_CHARS:
            raise GuardError(f"text is over {MAX_CHARS} characters; split it")
        r = inspect(text, direction)
        cid = "gc_" + secrets.token_hex(10)
        body = {"type": "PriviGuardReceipt", "version": "1", "check_id": cid, "checked_at": _iso(),
                "direction": direction, "input_sha256": r["input_sha256"], "chars": r["chars"],
                "verdict": r["verdict"], "risk": r["risk"], "findings": sorted({f["code"] for f in r["findings"]}),
                "engine": ENGINE_VERSION, "org_id": org_id, "source": (source or "")[:300] or None}
        rh = sha(canon(body))
        sig = self.passports.sign(rh)
        with self.lock:
            self.db.execute("INSERT INTO guard_checks (check_id, at, org_id, direction, verdict, risk, units, paid_by, receipt, "
                            "receipt_hash, signature) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            (cid, body["checked_at"], org_id, direction, r["verdict"], r["risk"], r["units"], paid_by,
                             canon(body), rh, sig))
            self.db.execute("INSERT INTO guard_daily (day, direction, verdict, paid_by, n, units) VALUES (?,?,?,?,1,?) "
                            "ON CONFLICT(day, direction, verdict, paid_by) DO UPDATE SET n = n + 1, units = units + ?",
                            (body["checked_at"][:10], direction, r["verdict"], paid_by, r["units"], r["units"]))
            self.db.commit()
        out = {k: r[k] for k in ("verdict", "risk", "direction", "findings", "chars", "units", "engine")}
        if "redacted_text" in r:
            out["redacted_text"] = r["redacted_text"]
        out["advice"] = {"block": "Do not act on this content (inbound) or do not send it (outbound). Show the user the findings.",
                         "warn": "Proceed with care: confirm with the user before any irreversible action based on this content.",
                         "allow": "No known attack or leak patterns found."}[r["verdict"]]
        out["receipt"] = {"check_id": cid, "receipt_hash": rh, "signature_ed25519": sig, "body": body,
                          "verify": f"{self.public_url}/guard/v1/receipts/{cid}"}
        out["paid_by"] = paid_by
        return out

    def receipt(self, check_id: str) -> dict:
        with self.lock:
            r = self.db.execute("SELECT * FROM guard_checks WHERE check_id=?", ((check_id or "").strip(),)).fetchone()
        if not r:
            raise GuardError("no such receipt")
        body = json.loads(r["receipt"])
        out = {"receipt": body, "receipt_hash": r["receipt_hash"], "signature_ed25519": r["signature"],
               "hash_matches_body": sha(canon(body)) == r["receipt_hash"],
               "signature_valid": self.passports.signature_ok(r["receipt_hash"], r["signature"]),
               "issuer": self.passports.issuer(), "anchoring": {"status": "pending (batched every few minutes)"}}
        if r["batch_id"]:
            with self.lock:
                b = self.db.execute("SELECT * FROM guard_batches WHERE batch_id=?", (r["batch_id"],)).fetchone()
                leaves = [x["receipt_hash"] for x in self.db.execute(
                    "SELECT receipt_hash FROM guard_checks WHERE batch_id=? ORDER BY rowid", (r["batch_id"],)).fetchall()]
            root, proof = merkle_root_and_proof(leaves, leaves.index(r["receipt_hash"]))
            out["anchoring"] = {"status": "in the Privi Ledger transparency log", "batch_id": b["batch_id"], "batch_root": b["root"],
                                "merkle_proof": proof, "proof_valid": verify_proof(r["receipt_hash"], proof, b["root"]) and root == b["root"],
                                "merkle_rule": "sha256(min(a,b) || max(a,b)) over 32-byte hashes; an odd node is carried up",
                                "ledger_org_id": GUARD_ORG_ID, "ledger_stream_id": GUARD_STREAM, "ledger_seq": b["ledger_seq"],
                                "ledger_entry_hash": b["ledger_hash"],
                                "inclusion_proof": f"{self.public_url}/log/inclusion?hash={b['ledger_hash']}" if b["ledger_hash"] else None}
        return out

    def batch_once(self) -> int:
        with self.lock:
            rows = self.db.execute("SELECT rowid, receipt_hash FROM guard_checks WHERE batch_id IS NULL ORDER BY rowid LIMIT ?",
                                   (BATCH_MAX,)).fetchall()
        if not rows:
            return 0
        leaves = [r["receipt_hash"] for r in rows]
        root, _ = merkle_root_and_proof(leaves)
        with self.lock:
            cur = self.db.execute("INSERT INTO guard_batches (at, root, count) VALUES (?,?,?)", (_iso(), root, len(rows)))
            bid = cur.lastrowid
            self.db.executemany("UPDATE guard_checks SET batch_id=? WHERE rowid=?", [(bid, r["rowid"]) for r in rows])
            self.db.commit()
        try:
            e = self.ledger.record(GUARD_ORG_ID, GUARD_STREAM, "Privi Guard", "other",
                                   f"Guard receipt batch {bid}: {len(rows)} checks, Merkle root {root}", "", "success",
                                   {"batch_id": bid, "root": root, "count": len(rows)})
            with self.lock:
                self.db.execute("UPDATE guard_batches SET ledger_seq=?, ledger_hash=? WHERE batch_id=?", (e["seq"], e["entry_hash"], bid))
                self.db.commit()
        except ValueError as ex:
            print(f"privi-guard: could not log batch {bid}: {ex}", flush=True)
        return len(rows)

    def start(self, interval_s: float = 300.0) -> threading.Thread:
        def loop():
            time.sleep(20)
            while True:
                try:
                    n = self.batch_once()
                    if n:
                        print(f"privi-guard: batched {n} receipts", flush=True)
                except Exception as e:
                    print(f"privi-guard: batch failed: {e}", flush=True)
                time.sleep(interval_s)
        t = threading.Thread(target=loop, daemon=True, name="privi-guard-batches")
        t.start()
        return t

    # ---- numbers ---------------------------------------------------------------

    def stats(self) -> dict:
        today = _iso()[:10]
        since = (_now().date().toordinal() - 29)
        with self.lock:
            rows = self.db.execute("SELECT * FROM guard_daily").fetchall()
            batches = self.db.execute("SELECT COUNT(*) n, MAX(at) last FROM guard_batches").fetchone()
        d30 = [r for r in rows if datetime.fromisoformat(r["day"]).toordinal() >= since]
        tot = lambda rs, k="n": sum(r[k] for r in rs)
        return {"checks_total": tot(rows), "checks_today": tot([r for r in rows if r["day"] == today]),
                "checks_last_30_days": tot(d30), "units_last_30_days": tot(d30, "units"),
                "verdicts_last_30_days": {v: tot([r for r in d30 if r["verdict"] == v]) for v in ("allow", "warn", "block")},
                "blocked_total": tot([r for r in rows if r["verdict"] == "block"]),
                "receipt_batches": batches["n"], "last_batch_at": batches["last"], "engine": ENGINE_VERSION}

    def revenue(self) -> dict:
        with self.lock:
            x402 = self.db.execute("SELECT COALESCE(SUM(n),0) n FROM guard_daily WHERE paid_by='x402'").fetchone()["n"]
            buys = self.db.execute("SELECT pack, COUNT(*) n, SUM(CAST(usd AS REAL)) usd FROM guard_purchases GROUP BY pack").fetchall()
            credit_units = self.db.execute("SELECT COALESCE(SUM(units),0) u FROM guard_daily WHERE paid_by='credits'").fetchone()["u"]
        per = float(PRICE_PER_CHECK)
        packs = {r["pack"]: {"purchases": r["n"], "usdc": round(r["usd"] or 0, 2)} for r in buys}
        return {"per_check_x402": {"checks": x402, "usdc": round(x402 * per, 2)}, "credit_packs": packs,
                "credit_units_consumed": credit_units,
                "total_usdc": round(x402 * per + sum(p["usdc"] for p in packs.values()), 2),
                "note": "USDC settled on Base to the Privi pay-to wallet through the x402 facilitator"}

    def pricing(self) -> dict:
        return {"unit": "one check of up to 100,000 characters",
                "free": f"{FREE_MONTHLY} checks per month for every organization (free key: ledger_signup)",
                "pay_per_check": f"${PRICE_PER_CHECK} USDC per check via x402, no account (texts up to one unit)",
                "credit_packs": {k: {"checks": u, "usdc": p, "per_check": f"${float(p) / u:.4f}"} for k, (u, p) in PACKS.items()},
                "privacy": "Privi never stores the text it checks, only its SHA-256 in your receipt",
                "receipts": "every check returns an Ed25519-signed receipt, batched into the on-chain-anchored transparency log"}
