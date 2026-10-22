"""Single-instance SQLite MVP. Mount /data as a durable volume; use Postgres before horizontal scaling."""
import hashlib
import os
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

DB = os.getenv("LIFE_DB_PATH", "./data/life-studio.sqlite3")

def now():
    return int(time.time())

def uid(prefix):
    return prefix + "_" + uuid.uuid4().hex[:22]

@contextmanager
def transaction():
    conn = sqlite3.connect(DB, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def obj(row):
    return dict(row) if row is not None else None

def init():
    Path(DB).parent.mkdir(parents=True, exist_ok=True)
    with transaction() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
          id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, pwdhash TEXT NOT NULL,
          wallet TEXT UNIQUE, member_since INTEGER NOT NULL, credits INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS sessions (
          token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS challenges (
          nonce_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, wallet TEXT NOT NULL,
          message TEXT NOT NULL, expires INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS projects (
          id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, title TEXT NOT NULL, kind TEXT NOT NULL,
          created INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS files (
          project_id TEXT NOT NULL, path TEXT NOT NULL, content TEXT NOT NULL,
          version INTEGER NOT NULL DEFAULT 1, PRIMARY KEY(project_id,path)
        );
        CREATE TABLE IF NOT EXISTS runs (
          id TEXT PRIMARY KEY, project_id TEXT NOT NULL, agent TEXT NOT NULL,
          status TEXT NOT NULL, task TEXT NOT NULL, output TEXT NOT NULL DEFAULT '',
          error TEXT NOT NULL DEFAULT '', created INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS proposals (
          id TEXT PRIMARY KEY, run_id TEXT NOT NULL, project_id TEXT NOT NULL,
          summary TEXT NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending'
        );
        CREATE TABLE IF NOT EXISTS ledger (
          id TEXT PRIMARY KEY, user_id TEXT NOT NULL, kind TEXT NOT NULL,
          service TEXT NOT NULL, amount INTEGER NOT NULL, platform_fee_micros INTEGER NOT NULL DEFAULT 0,
          idempotency TEXT NOT NULL, created INTEGER NOT NULL, UNIQUE(user_id,idempotency)
        );
        CREATE TABLE IF NOT EXISTS quotes (
          id TEXT PRIMARY KEY, user_id TEXT NOT NULL, wallet TEXT NOT NULL,
          credits INTEGER NOT NULL, amount_wei TEXT NOT NULL, expires INTEGER NOT NULL, created INTEGER NOT NULL,
          used_tx TEXT
        );
        -- Attestations are append-only per project file version.
        CREATE TABLE IF NOT EXISTS cog_events (
          id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, project_id TEXT NOT NULL,
          path TEXT NOT NULL, version INTEGER NOT NULL, agent TEXT NOT NULL,
          source TEXT NOT NULL, run_id TEXT, stamp_utc TEXT NOT NULL,
          content_sha256 TEXT NOT NULL, prev_event_sha256 TEXT,
          line_manifest_sha256 TEXT NOT NULL, event_hash TEXT NOT NULL UNIQUE,
          signature_hex TEXT, pubkey_hex TEXT, credit_cost INTEGER,
          prvi_deploy_wei TEXT, rights_notice TEXT NOT NULL, payload_json TEXT NOT NULL,
          UNIQUE(project_id,path,version)
        );
        CREATE TABLE IF NOT EXISTS cog_lines (
          event_id TEXT NOT NULL, line_no INTEGER NOT NULL,
          line_text TEXT NOT NULL, line_sha256 TEXT NOT NULL,
          author_agent TEXT NOT NULL, author_time TEXT NOT NULL,
          origin_event TEXT NOT NULL,
          PRIMARY KEY(event_id,line_no)
        );
        CREATE TABLE IF NOT EXISTS cog_claim_challenges (
          user_id TEXT NOT NULL, project_id TEXT NOT NULL,
          agent TEXT NOT NULL, wallet TEXT NOT NULL,
          message TEXT NOT NULL, expires INTEGER NOT NULL,
          PRIMARY KEY(user_id,project_id,agent)
        );
        CREATE TABLE IF NOT EXISTS cog_wallets (
          user_id TEXT NOT NULL, project_id TEXT NOT NULL,
          agent TEXT NOT NULL, wallet TEXT NOT NULL,
          linked_at INTEGER NOT NULL, PRIMARY KEY(user_id,project_id,agent)
        );
        CREATE TABLE IF NOT EXISTS cog_proposal_signatures (
          proposal_id TEXT NOT NULL, path TEXT NOT NULL, agent TEXT NOT NULL,
          run_id TEXT NOT NULL, stamp_utc TEXT NOT NULL, event_hash TEXT NOT NULL,
          signature_hex TEXT, pubkey_hex TEXT, payload_json TEXT NOT NULL,
          PRIMARY KEY(proposal_id,path)
        );
        CREATE TABLE IF NOT EXISTS cog_deployments (
          tx_hash TEXT PRIMARY KEY, event_id TEXT NOT NULL UNIQUE,
          chain_id INTEGER NOT NULL, contract_address TEXT NOT NULL,
          verified_native_gas_wei TEXT NOT NULL, verified_at INTEGER NOT NULL,
          attribution TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS cog_royalty_calls (
          id TEXT PRIMARY KEY, user_id TEXT NOT NULL, project_id TEXT NOT NULL,
          event_id TEXT NOT NULL, idem TEXT NOT NULL, credits INTEGER NOT NULL,
          royalty_micros INTEGER NOT NULL, created INTEGER NOT NULL,
          UNIQUE(user_id,idem)
        );
        CREATE TABLE IF NOT EXISTS cog_royalties (
          call_id TEXT NOT NULL, agent TEXT NOT NULL, credited_wallet TEXT,
          line_count INTEGER NOT NULL, amount_micros INTEGER NOT NULL,
          status TEXT NOT NULL, PRIMARY KEY(call_id,agent)
        );
        CREATE TABLE IF NOT EXISTS redemptions (
          tx_hash TEXT PRIMARY KEY, quote_id TEXT NOT NULL UNIQUE, user_id TEXT NOT NULL,
          credits INTEGER NOT NULL, created INTEGER NOT NULL
        );
        """)
    return True

def sha(token):
    return hashlib.sha256(token.encode()).hexdigest()

def get_user(user_id):
    with transaction() as db:
        return obj(db.execute("SELECT id,email,wallet,member_since,credits FROM users WHERE id=?",
                              (user_id,)).fetchone())

def session_user(token):
    if not token:
        return None
    with transaction() as db:
        row = db.execute("SELECT u.id,u.email,u.wallet,u.member_since,u.credits FROM sessions s "
                         "JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires>?",
                         (sha(token), now())).fetchone()
        return obj(row)

def charge(user_id, service, amount, key, fee_bps=1000):
    """Atomic, idempotent debit. Returns bool; no partial charges."""
    if not isinstance(amount, int) or amount < 0 or not key or len(key) > 180:
        raise ValueError("Invalid charge")
    with transaction() as db:
        old = db.execute("SELECT amount,service FROM ledger WHERE user_id=? AND idempotency=?",
                         (user_id, key)).fetchone()
        if old:
            if old["amount"] != -amount or old["service"] != service:
                raise ValueError("Conflicting idempotency key")
            return True
        row = db.execute("SELECT credits,wallet FROM users WHERE id=?", (user_id,)).fetchone()
        if not row or not row["wallet"] or row["credits"] < amount:
            return False
        db.execute("UPDATE users SET credits=credits-? WHERE id=?", (amount, user_id))
        db.execute("INSERT INTO ledger VALUES (?,?,?,?,?,?,?,?)",
                   (uid("led"), user_id, "charge", service, -amount,
                    amount * fee_bps * 100, key, now()))
        return True

def credit(user_id, amount, service, key):
    if not isinstance(amount, int) or amount <= 0 or amount > 1000000:
        raise ValueError("Invalid credit")
    with transaction() as db:
        existing = db.execute("SELECT amount,service FROM ledger WHERE user_id=? AND idempotency=?",
                              (user_id, key)).fetchone()
        if existing:
            if existing["amount"] != amount or existing["service"] != service:
                raise ValueError("Conflicting idempotency key")
            return
        db.execute("UPDATE users SET credits=credits+? WHERE id=?", (amount, user_id))
        db.execute("INSERT INTO ledger VALUES (?,?,?,?,?,?,?,?)",
                   (uid("led"), user_id, "credit", service, amount, 0, key, now()))

def owns(project_id, user_id):
    with transaction() as db:
        return obj(db.execute("SELECT * FROM projects WHERE id=? AND owner_id=?",
                              (project_id, user_id)).fetchone())
