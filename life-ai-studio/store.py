"""Single-instance SQLite MVP. Mount /data as a durable volume; use Postgres before horizontal scaling."""
import hashlib
import os
import secrets
import stat
import sqlite3
import time
import uuid
from contextlib import closing, contextmanager
from pathlib import Path

DB = os.getenv("LIFE_DB_PATH", "./data/life-studio.sqlite3")

def now():
    return int(time.time())

def uid(prefix):
    return prefix + "_" + uuid.uuid4().hex[:22]

def database_readable():
    """Non-mutating availability check, not a production launch assertion.

    Read-only SQLite URI mode prevents a missing database from being created
    by a monitoring probe. Require the minimum LIFE account, session, project,
    file and credit-ledger columns so an unrelated or partially restored SQLite
    file cannot make the readiness probe (or guarded startup) appear healthy.
    """
    try:
        location = Path(DB).expanduser().resolve(strict=True)
        if not location.is_file():
            return False
        uri = location.as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=2)) as conn:
            # LIMIT 0 checks the schema without loading private customer rows.
            # Keep this lightweight: full integrity and restore validation is
            # performed separately by the offline backup verifier.
            for query in (
                "SELECT id,email,pwdhash,member_since,credits FROM users LIMIT 0",
                "SELECT token_hash,user_id,expires FROM sessions LIMIT 0",
                "SELECT id,owner_id,title FROM projects LIMIT 0",
                "SELECT project_id,path,content,version FROM files LIMIT 0",
                "SELECT id,user_id,amount,idempotency FROM ledger LIMIT 0",
            ):
                conn.execute(query).fetchall()
        return True
    except (OSError, sqlite3.Error):
        return False


@contextmanager
def transaction():
    # Never let a request silently create a fresh, empty SQLite database if
    # the mounted LIFE volume disappears. init() is the only creation path.
    # URI mode=rw opens an existing file for writes but refuses to create one.
    uri = Path(DB).absolute().as_uri() + "?mode=rw"
    conn = sqlite3.connect(uri, uri=True, timeout=30)
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
    # LIFE stores password verifiers, session hashes and private project files.
    # SQLite's default creation mode follows the process umask (often 0644).
    # Create a new database with owner-only permissions before SQLite opens it.
    # Never chmod an existing database: its access policy needs operator review.
    db_path = Path(DB)
    if os.getenv("LIFE_REQUIRE_EXISTING_DB") == "1":
        # Operator opt-in for durable deployments: never bootstrap an empty
        # customer database if a mounted volume is missing or uninitialized.
        # Do not create even the parent directory in this mode.
        try:
            regular = stat.S_ISREG(db_path.lstat().st_mode)
        except FileNotFoundError:
            regular = False
        if not regular or not database_readable():
            raise RuntimeError(
                "LIFE startup requires an existing initialized database; "
                "check the persistent volume and recovery procedure"
            )
        # transaction() uses SQLite mode=rw: if the file disappears after
        # this check, it still cannot be recreated by the startup process.
    else:
        # Disposable staging/local development may create a new private DB.
        db_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            fd = os.open(db_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            # Do not follow symlinks or open special files as member databases.
            if not stat.S_ISREG(db_path.lstat().st_mode):
                raise ValueError("LIFE database path must be an existing regular file")
        else:
            os.close(fd)
    with transaction() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
          id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, pwdhash TEXT NOT NULL,
          wallet TEXT UNIQUE, member_since INTEGER NOT NULL, credits INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS sessions (
          token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS login_throttle (
          key_hash TEXT PRIMARY KEY, failures INTEGER NOT NULL,
          window_started INTEGER NOT NULL, blocked_until INTEGER NOT NULL DEFAULT 0
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
        CREATE TABLE IF NOT EXISTS stripe_checkout_sessions (
          session_id TEXT PRIMARY KEY,
          user_id TEXT NOT NULL,
          price_id TEXT NOT NULL,
          credits INTEGER NOT NULL CHECK(credits=100),
          amount_cents INTEGER NOT NULL CHECK(amount_cents=1000),
          created INTEGER NOT NULL,
          fulfilled_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS bnb_priv_quotes (
          id TEXT PRIMARY KEY,
          user_id TEXT NOT NULL,
          wallet TEXT NOT NULL,
          credits INTEGER NOT NULL,
          amount_units TEXT NOT NULL,
          contract TEXT NOT NULL,
          treasury TEXT NOT NULL,
          code_sha256 TEXT NOT NULL,
          decimals INTEGER NOT NULL,
          created INTEGER NOT NULL,
          expires INTEGER NOT NULL,
          used_tx TEXT UNIQUE
        );
        CREATE TABLE IF NOT EXISTS bnb_priv_redemptions (
          tx_hash TEXT PRIMARY KEY,
          quote_id TEXT NOT NULL UNIQUE,
          user_id TEXT NOT NULL,
          amount_units TEXT NOT NULL,
          credits INTEGER NOT NULL,
          created INTEGER NOT NULL
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


# A persistent throttle shared by all requests to the single-instance LIFE SQLite DB.
# Keys are hashed before storage; no email addresses or IP strings are logged here.
LOGIN_WINDOW_SECONDS = 900
LOGIN_MAX_FAILURES = 5

def _login_key(email, client_host):
    if not isinstance(client_host, str):
        client_host = ""
    return sha("life-login-v1:" + email.strip().lower() + "\\0" + client_host)

def _login_email_key(email):
    # An account-wide throttle closes the distributed-client bypass while
    # retaining the existing client-specific throttle for noisy origins.
    return sha("life-login-email-v1:" + email.strip().lower())


def _login_throttle_keys(email, client_host):
    return (_login_key(email, client_host), _login_email_key(email))


def login_blocked(email, client_host):
    client_key, email_key = _login_throttle_keys(email, client_host)
    with transaction() as db:
        row = db.execute(
            "SELECT 1 FROM login_throttle WHERE key_hash IN (?,?) AND blocked_until>? LIMIT 1",
            (client_key, email_key, now())
        ).fetchone()
        return row is not None


def login_failed(email, client_host):
    keys = _login_throttle_keys(email, client_host)
    stamp = now()
    # Update both scopes atomically: rotating IPs must not evade the
    # account-wide limit. Only opaque hashes are stored.
    with transaction() as db:
        for key in keys:
            row = db.execute(
                "SELECT failures,window_started FROM login_throttle WHERE key_hash=?",
                (key,)
            ).fetchone()
            if row and (stamp - row["window_started"]) < LOGIN_WINDOW_SECONDS:
                failures, started = row["failures"] + 1, row["window_started"]
            else:
                failures, started = 1, stamp
            blocked_until = stamp + LOGIN_WINDOW_SECONDS if failures >= LOGIN_MAX_FAILURES else 0
            db.execute(
                "INSERT INTO login_throttle(key_hash,failures,window_started,blocked_until) "
                "VALUES(?,?,?,?) ON CONFLICT(key_hash) DO UPDATE SET "
                "failures=excluded.failures,window_started=excluded.window_started,"
                "blocked_until=excluded.blocked_until",
                (key, failures, started, blocked_until)
            )


def login_succeeded(email, client_host):
    # A successful login resets both account and client-specific counters.
    with transaction() as db:
        db.execute("DELETE FROM login_throttle WHERE key_hash IN (?,?)",
                   _login_throttle_keys(email, client_host))

# Persistent signup-abuse throttle, scoped to the actual socket peer.
# Do not trust client-supplied X-Forwarded-For headers here. Reverse proxies
# must be configured and audited before non-staging signup is allowed.
SIGNUP_MAX_ATTEMPTS = 50
SIGNUP_WINDOW_SECONDS = 900


def signup_allowed(client_host):
    """Atomically count signup attempts across requests/restarts, not just successes.

    Uses the existing opaque-hash throttle table; no raw IP address is stored.
    A shared NAT/proxy address may affect multiple people, so review limits and
    trusted proxy handling before customer onboarding.
    """
    host = client_host if isinstance(client_host, str) and client_host else "unknown"
    key = sha("life-signup-v1:" + host)
    stamp = now()
    with transaction() as db:
        row = db.execute(
            "SELECT failures,window_started,blocked_until FROM login_throttle "
            "WHERE key_hash=?", (key,)
        ).fetchone()
        if row and row["blocked_until"] > stamp:
            return False
        if row and 0 <= stamp - row["window_started"] < SIGNUP_WINDOW_SECONDS:
            attempts, started = row["failures"] + 1, row["window_started"]
        else:
            attempts, started = 1, stamp
        blocked_until = stamp + SIGNUP_WINDOW_SECONDS if attempts > SIGNUP_MAX_ATTEMPTS else 0
        db.execute(
            "INSERT INTO login_throttle(key_hash,failures,window_started,blocked_until) "
            "VALUES(?,?,?,?) ON CONFLICT(key_hash) DO UPDATE SET "
            "failures=excluded.failures,window_started=excluded.window_started,"
            "blocked_until=excluded.blocked_until",
            (key, attempts, started, blocked_until)
        )
        return attempts <= SIGNUP_MAX_ATTEMPTS


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
    # Reject bool (an int subclass), fractional quantities and malformed keys
    # before opening a transaction. Charge retries must use stable text keys.
    if type(amount) is not int or amount < 0:
        raise ValueError("Invalid charge")
    if not isinstance(key, str) or not key.strip() or len(key) > 180:
        raise ValueError("Invalid charge idempotency key")
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
    # Validate idempotency keys before writes instead of relying on the
    # ledger's NOT NULL/UNIQUE constraints to reject invalid requests.
    # bool is an int subclass but is not a valid credit quantity.
    if type(amount) is not int or amount <= 0 or amount > 1000000:
        raise ValueError("Invalid credit")
    if not isinstance(key, str) or not key.strip() or len(key) > 180:
        raise ValueError("Invalid credit idempotency key")
    with transaction() as db:
        existing = db.execute("SELECT amount,service FROM ledger WHERE user_id=? AND idempotency=?",
                              (user_id, key)).fetchone()
        if existing:
            if existing["amount"] != amount or existing["service"] != service:
                raise ValueError("Conflicting idempotency key")
            return
        updated = db.execute("UPDATE users SET credits=credits+? WHERE id=?", (amount, user_id))
        if updated.rowcount != 1:
            # Do not create an orphan financial audit record when a member was
            # deleted or an upstream caller supplied an unknown account ID.
            # Raising rolls back the entire credit transaction.
            raise ValueError("Unknown LIFE member for credit")
        db.execute("INSERT INTO ledger VALUES (?,?,?,?,?,?,?,?)",
                   (uid("led"), user_id, "credit", service, amount, 0, key, now()))

def owns(project_id, user_id):
    with transaction() as db:
        return obj(db.execute("SELECT * FROM projects WHERE id=? AND owner_id=?",
                              (project_id, user_id)).fetchone())
