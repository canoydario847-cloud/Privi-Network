"""Create a consistent, private SQLite LIFE snapshot and verify a restore drill.

This tool does not enable production readiness or publish backups. Operators must
store verified snapshots in separately encrypted, access-controlled off-host
storage, and periodically test actual disaster recovery procedures.
"""

import argparse
import hashlib
import hmac
import json
import re
import os
import sqlite3
import stat
import tempfile
from pathlib import Path


def readonly_connection(path: Path):
    # SQLite URI mode=ro prevents accidentally creating a missing DB.
    return sqlite3.connect(path.resolve(strict=True).as_uri() + "?mode=ro", uri=True)


def validate_database(conn):
    result = conn.execute("PRAGMA integrity_check").fetchone()
    if result is None or result[0] != "ok":
        raise ValueError("SQLite integrity_check failed")
    if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise ValueError("SQLite foreign_key_check failed")
    # Integrity alone is insufficient: an empty or unrelated SQLite file also
    # passes integrity_check and could be mistaken for a recoverable LIFE backup.
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    # Table names alone can be spoofed by an unrelated database. Verify the
    # minimum columns required to restore accounts, sessions, project files and
    # idempotent credit records. Extra columns are allowed for future migrations.
    required_columns = {
        "users": {"id", "email", "pwdhash", "wallet", "member_since", "credits"},
        "sessions": {"token_hash", "user_id", "expires"},
        "projects": {"id", "owner_id", "title", "kind", "created"},
        "files": {"project_id", "path", "content", "version"},
        "ledger": {"id", "user_id", "kind", "service", "amount", "idempotency", "created"},
    }
    missing = required_columns.keys() - tables
    if missing:
        raise ValueError("Not a LIFE database; missing core tables: " + ", ".join(sorted(missing)))
    for table, columns in required_columns.items():
        present = {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}
        absent = columns - present
        if absent:
            raise ValueError(
                f"Not a LIFE database; table {table} missing columns: "
                + ", ".join(sorted(absent))
            )
    # A lookalike schema with matching column names but no identity constraints
    # is not a safe account/session recovery target. Verify the core primary
    # keys that the live LIFE store depends on for unique identity.
    required_primary_keys = {
        "users": ("id",),
        "sessions": ("token_hash",),
        "projects": ("id",),
        "files": ("project_id", "path"),
        "ledger": ("id",),
    }
    for table, expected in required_primary_keys.items():
        columns = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
        actual = tuple(row[1] for row in sorted(columns, key=lambda row: row[5]) if row[5] > 0)
        if actual != expected:
            raise ValueError(f"Not a LIFE database; table {table} primary key mismatch")
    # SQLite rowid tables permit NULL values in non-INTEGER PRIMARY KEY
    # columns, even when the schema declares TEXT PRIMARY KEY. A snapshot
    # containing NULL account, session, project, file or ledger identities
    # cannot be safely restored for authentication and ownership lookups.
    # Check the data as well as the schema; do not expose private row values.
    for table, keys in required_primary_keys.items():
        null_predicate = " OR ".join(f'"{key}" IS NULL' for key in keys)
        if conn.execute(
            f'SELECT 1 FROM "{table}" WHERE {null_predicate} LIMIT 1'
        ).fetchone() is not None:
            raise ValueError(f"Not a LIFE database; {table} primary key contains NULL")
    # Restored account identity must retain the same uniqueness constraints as
    # the live store. Without these, two accounts could share an email or a
    # wallet and login / ownership lookups become ambiguous.
    user_columns = {row[1]: row for row in conn.execute('PRAGMA table_info("users")')}
    if not user_columns["email"][3]:
        raise ValueError("Not a LIFE database; users email must be NOT NULL")
    user_unique_indexes = conn.execute('PRAGMA index_list("users")').fetchall()
    required_user_uniques = {("email",), ("wallet",)}
    for index in user_unique_indexes:
        if not index[2] or (len(index) > 4 and index[4]):
            continue  # Non-unique and partial indexes cannot protect all accounts.
        name = index[1].replace('"', '""')
        columns = tuple(row[2] for row in conn.execute(f'PRAGMA index_info("{name}")'))
        required_user_uniques.discard(columns)
    if required_user_uniques:
        raise ValueError(
            "Not a LIFE database; users UNIQUE constraint missing: "
            + ", ".join(", ".join(columns) for columns in sorted(required_user_uniques))
        )
    # Idempotent LIFE credit charges rely on the composite uniqueness of
    # (user_id, idempotency). A restored database missing this constraint can
    # silently accept duplicate charges even when its columns and PKs match.
    ledger_columns = {
        row[1]: row for row in conn.execute('PRAGMA table_info("ledger")')
    }
    if not all(ledger_columns[name][3] for name in ("user_id", "idempotency")):
        raise ValueError("Not a LIFE database; ledger idempotency columns must be NOT NULL")
    unique_indexes = conn.execute('PRAGMA index_list("ledger")').fetchall()
    has_idempotency_guard = False
    for index in unique_indexes:
        # A partial index does not protect every ledger record.
        if not index[2] or (len(index) > 4 and index[4]):
            continue
        index_name = index[1].replace('"', '""')
        index_columns = tuple(row[2] for row in conn.execute(
            f'PRAGMA index_info("{index_name}")'
        ))
        if index_columns == ("user_id", "idempotency"):
            has_idempotency_guard = True
            break
    if not has_idempotency_guard:
        raise ValueError("Not a LIFE database; ledger idempotency UNIQUE constraint missing")
    # Wallet-link challenges are authentication state. Older snapshots may not
    # have this table, but a present table must preserve one-time nonce identity
    # and account ownership. The current LIFE schema has no foreign key here.
    if "challenges" in tables:
        info = conn.execute('PRAGMA table_info("challenges")').fetchall()
        auth_columns = {row[1]: row for row in info}
        required = {"nonce_hash", "user_id", "wallet", "message", "expires"}
        if required - auth_columns.keys():
            raise ValueError("Not a LIFE database; wallet challenge columns missing")
        primary_key = tuple(
            row[1] for row in sorted(info, key=lambda row: row[5]) if row[5] > 0
        )
        if primary_key != ("nonce_hash",):
            raise ValueError("Not a LIFE database; wallet challenge nonce primary key missing")
        if not all(auth_columns[name][3] for name in
                   ("user_id", "wallet", "message", "expires")):
            raise ValueError("Not a LIFE database; wallet challenge required fields nullable")
        orphan = conn.execute(
            'SELECT 1 FROM "challenges" c LEFT JOIN "users" u '
            'ON c.user_id = u.id WHERE u.id IS NULL OR c.nonce_hash IS NULL LIMIT 1'
        ).fetchone()
        if orphan is not None:
            # Never expose a member ID, wallet, signed challenge or nonce.
            raise ValueError("Not a LIFE database; invalid wallet challenge ownership")
        # Challenge nonces are persisted only as lowercase SHA-256 hashes.
        # SQLite's dynamic typing can admit malformed hashes and expiration
        # values; reject those before restoring wallet-link authentication.
        invalid_challenge = conn.execute(
            'SELECT 1 FROM "challenges" WHERE '
            "typeof(nonce_hash) != 'text' OR length(nonce_hash) != 64 "
            "OR nonce_hash GLOB '*[^0-9a-f]*' "
            "OR typeof(expires) != 'integer' OR expires < 0 LIMIT 1"
        ).fetchone()
        if invalid_challenge is not None:
            raise ValueError("Not a LIFE database; invalid wallet challenge state")
    # Failed-login throttle state is security-sensitive: a malformed restore
    # could silently drop lockouts or make future login attempts fail. Older
    # core-only snapshots may omit this table, but if present it must match
    # the current single-instance throttle contract. Never print key hashes.
    if "login_throttle" in tables:
        info = conn.execute('PRAGMA table_info("login_throttle")').fetchall()
        columns = {row[1]: row for row in info}
        required = {"key_hash", "failures", "window_started", "blocked_until"}
        if required - columns.keys():
            raise ValueError("Not a LIFE database; login throttle columns missing")
        primary_key = tuple(
            row[1] for row in sorted(info, key=lambda row: row[5]) if row[5] > 0
        )
        if primary_key != ("key_hash",):
            raise ValueError("Not a LIFE database; login throttle primary key missing")
        if not all(columns[name][3] for name in
                   ("failures", "window_started", "blocked_until")):
            raise ValueError("Not a LIFE database; login throttle required fields nullable")
        invalid = conn.execute(
            'SELECT 1 FROM "login_throttle" WHERE '
            'key_hash IS NULL OR length(key_hash) != 64 '
            "OR key_hash GLOB '*[^0-9a-f]*' "
            "OR typeof(failures) != 'integer' OR failures < 1 "
            "OR typeof(window_started) != 'integer' OR window_started < 0 "
            "OR typeof(blocked_until) != 'integer' OR blocked_until < 0 "
            "OR (blocked_until > 0 AND blocked_until < window_started) LIMIT 1"
        ).fetchone()
        if invalid is not None:
            raise ValueError("Not a LIFE database; invalid login throttle state")
    # Optional AI collaboration tables exist in current LIFE deployments but
    # may be absent from earlier, core-only snapshots. When present, their
    # ownership links must survive restore even without declared foreign keys.
    optional_ai_columns = {
        "runs": {"id", "project_id"},
        "proposals": {"run_id", "project_id"},
    }
    for table, required in optional_ai_columns.items():
        if table in tables:
            present = {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}
            if required - present:
                raise ValueError(f"Not a LIFE database; {table} ownership columns missing")
    if "proposals" in tables and "runs" not in tables:
        raise ValueError("Not a LIFE database; proposals present without runs")
    if "runs" in tables:
        orphan_run = conn.execute(
            'SELECT 1 FROM "runs" r LEFT JOIN "projects" p '
            'ON r.project_id = p.id WHERE p.id IS NULL LIMIT 1'
        ).fetchone()
        if orphan_run is not None:
            raise ValueError("Not a LIFE database; orphaned AI runs")
    if "proposals" in tables:
        orphan_proposal = conn.execute(
            'SELECT 1 FROM "proposals" q LEFT JOIN "runs" r ON q.run_id = r.id '
            'LEFT JOIN "projects" p ON q.project_id = p.id '
            'WHERE r.id IS NULL OR p.id IS NULL LIMIT 1'
        ).fetchone()
        if orphan_proposal is not None:
            raise ValueError("Not a LIFE database; orphaned AI proposals")
        mismatched_project = conn.execute(
            'SELECT 1 FROM "proposals" q JOIN "runs" r ON q.run_id = r.id '
            'WHERE q.project_id != r.project_id LIMIT 1'
        ).fetchone()
        if mismatched_project is not None:
            raise ValueError("Not a LIFE database; AI proposal project mismatch")
    # BNB PRIV redemption receipts are financial audit history. The current
    # SQLite schema has no foreign keys for quote/member links; restoring a
    # receipt against another member's quote would make reconciliation unsafe.
    # Older LIFE snapshots may omit these optional, disabled-payment tables.
    if "bnb_priv_redemptions" in tables and "bnb_priv_quotes" not in tables:
        raise ValueError("Not a LIFE database; BNB redemptions present without quotes")
    if "bnb_priv_quotes" in tables:
        columns = {row[1] for row in conn.execute('PRAGMA table_info("bnb_priv_quotes")')}
        if {"id", "user_id"} - columns:
            raise ValueError("Not a LIFE database; BNB quote ownership columns missing")
        orphan = conn.execute(
            'SELECT 1 FROM "bnb_priv_quotes" q LEFT JOIN "users" u '
            'ON q.user_id = u.id WHERE u.id IS NULL LIMIT 1'
        ).fetchone()
        if orphan is not None:
            raise ValueError("Not a LIFE database; orphaned BNB quotes")
    if "bnb_priv_redemptions" in tables:
        columns = {row[1] for row in conn.execute('PRAGMA table_info("bnb_priv_redemptions")')}
        if {"quote_id", "user_id"} - columns:
            raise ValueError("Not a LIFE database; BNB redemption ownership columns missing")
        invalid = conn.execute(
            'SELECT 1 FROM "bnb_priv_redemptions" r '
            'LEFT JOIN "bnb_priv_quotes" q ON r.quote_id = q.id '
            'LEFT JOIN "users" u ON r.user_id = u.id '
            'WHERE q.id IS NULL OR u.id IS NULL LIMIT 1'
        ).fetchone()
        if invalid is not None:
            raise ValueError("Not a LIFE database; orphaned BNB redemptions")
        mismatch = conn.execute(
            'SELECT 1 FROM "bnb_priv_redemptions" r '
            'JOIN "bnb_priv_quotes" q ON r.quote_id = q.id '
            'WHERE r.user_id != q.user_id LIMIT 1'
        ).fetchone()
        if mismatch is not None:
            raise ValueError("Not a LIFE database; BNB redemption member mismatch")
    # Stripe Checkout is disabled in staging, but a future restore must not
    # lose which member owns an order or whether its credits were fulfilled.
    # SQLite currently declares no foreign keys for checkout orders. Reject
    # orphaned, malformed or mismatched order/ledger history before publishing.
    if "stripe_checkout_sessions" in tables:
        info = conn.execute('PRAGMA table_info("stripe_checkout_sessions")').fetchall()
        cols = {row[1]: row for row in info}
        required = {"session_id", "user_id", "price_id", "credits",
                    "amount_cents", "created", "fulfilled_at"}
        if required - cols.keys():
            raise ValueError("Not a LIFE database; Stripe checkout columns missing")
        pk = tuple(row[1] for row in sorted(info, key=lambda row: row[5]) if row[5] > 0)
        if pk != ("session_id",):
            raise ValueError("Not a LIFE database; Stripe checkout session primary key missing")
        if not all(cols[name][3] for name in
                   ("user_id", "price_id", "credits", "amount_cents", "created")):
            raise ValueError("Not a LIFE database; Stripe checkout required fields nullable")
        malformed = conn.execute(
            'SELECT 1 FROM "stripe_checkout_sessions" s '
            'LEFT JOIN "users" u ON s.user_id = u.id '
            "WHERE u.id IS NULL OR s.session_id IS NULL "
            "OR typeof(s.session_id) != 'text' OR s.session_id NOT LIKE 'cs_%' "
            "OR typeof(s.price_id) != 'text' OR length(s.price_id) = 0 "
            "OR typeof(s.credits) != 'integer' OR s.credits != 100 "
            "OR typeof(s.amount_cents) != 'integer' OR s.amount_cents != 1000 "
            "OR typeof(s.created) != 'integer' OR s.created < 0 "
            "OR (s.fulfilled_at IS NOT NULL AND "
            "(typeof(s.fulfilled_at) != 'integer' OR s.fulfilled_at < s.created)) "
            "LIMIT 1"
        ).fetchone()
        if malformed is not None:
            raise ValueError("Not a LIFE database; invalid Stripe checkout order")
        # Each fulfilled order must have exactly one corresponding credit
        # ledger entry. Pending orders must not have issued credits.
        mismatch = conn.execute(
            'SELECT 1 FROM "stripe_checkout_sessions" s '
            "LEFT JOIN \"ledger\" l ON l.idempotency = 'stripe:' || s.session_id "
            'WHERE (s.fulfilled_at IS NULL AND l.id IS NOT NULL) '
            'OR (s.fulfilled_at IS NOT NULL AND '
            "(l.id IS NULL OR l.user_id != s.user_id OR l.amount != s.credits "
            "OR l.kind != 'credit' OR l.service != 'stripe_life_credits')) "
            'LIMIT 1'
        ).fetchone()
        if mismatch is not None:
            raise ValueError("Not a LIFE database; Stripe checkout ledger mismatch")
    # Verify the reverse relationship too: a Stripe credit ledger entry with
    # no matching Checkout order cannot be independently reconciled after a
    # restore. Earlier snapshots may lack the optional orders table, but they
    # must not contain orphaned Stripe credit entries.
    stripe_ledger = (
        "SELECT 1 FROM \"ledger\" WHERE "
        "service = 'stripe_life_credits' OR idempotency LIKE 'stripe:%' LIMIT 1"
    )
    if "stripe_checkout_sessions" not in tables:
        if conn.execute(stripe_ledger).fetchone() is not None:
            raise ValueError("Not a LIFE database; Stripe credit ledger without checkout orders")
    else:
        orphan_credit = conn.execute(
            'SELECT 1 FROM "ledger" l '
            'LEFT JOIN "stripe_checkout_sessions" s '
            "ON l.idempotency = 'stripe:' || s.session_id "
            "WHERE (l.service = 'stripe_life_credits' "
            "OR l.idempotency LIKE 'stripe:%') "
            'AND s.session_id IS NULL LIMIT 1'
        ).fetchone()
        if orphan_credit is not None:
            raise ValueError("Not a LIFE database; orphaned Stripe credit ledger entry")
    # Native PRVI payment tables are disabled in staging, but a recoverable
    # snapshot must preserve their customer-to-quote-to-redemption ownership.
    # The current schema has no declared foreign keys for these relationships.
    # Older snapshots may omit these optional tables entirely.
    if "redemptions" in tables and "quotes" not in tables:
        raise ValueError("Not a LIFE database; PRVI redemptions present without quotes")
    if "quotes" in tables:
        columns = {row[1] for row in conn.execute('PRAGMA table_info("quotes")')}
        if {"id", "user_id"} - columns:
            raise ValueError("Not a LIFE database; PRVI quote ownership columns missing")
        orphan = conn.execute(
            'SELECT 1 FROM "quotes" q LEFT JOIN "users" u '
            'ON q.user_id = u.id WHERE u.id IS NULL LIMIT 1'
        ).fetchone()
        if orphan is not None:
            raise ValueError("Not a LIFE database; orphaned PRVI quotes")
    if "redemptions" in tables:
        columns = {row[1] for row in conn.execute('PRAGMA table_info("redemptions")')}
        if {"quote_id", "user_id"} - columns:
            raise ValueError("Not a LIFE database; PRVI redemption ownership columns missing")
        orphan = conn.execute(
            'SELECT 1 FROM "redemptions" r '
            'LEFT JOIN "quotes" q ON r.quote_id = q.id '
            'LEFT JOIN "users" u ON r.user_id = u.id '
            'WHERE q.id IS NULL OR u.id IS NULL LIMIT 1'
        ).fetchone()
        if orphan is not None:
            raise ValueError("Not a LIFE database; orphaned PRVI redemptions")
        mismatch = conn.execute(
            'SELECT 1 FROM "redemptions" r JOIN "quotes" q ON r.quote_id = q.id '
            'WHERE r.user_id != q.user_id LIMIT 1'
        ).fetchone()
        if mismatch is not None:
            raise ValueError("Not a LIFE database; PRVI redemption member mismatch")
    # Cogvative provenance is private, owner-scoped project history. SQLite's
    # current schema does not declare foreign keys for these tables, so a
    # mechanically valid backup can otherwise restore unattached attestations.
    if "cog_lines" in tables and "cog_events" not in tables:
        raise ValueError("Not a LIFE database; Cogvative lines present without events")
    if "cog_events" in tables:
        columns = {row[1] for row in conn.execute('PRAGMA table_info("cog_events")')}
        if {"id", "owner_id", "project_id"} - columns:
            raise ValueError("Not a LIFE database; Cogvative event ownership columns missing")
        orphan = conn.execute(
            'SELECT 1 FROM "cog_events" e LEFT JOIN "projects" p '
            'ON e.project_id = p.id LEFT JOIN "users" u ON e.owner_id = u.id '
            'WHERE p.id IS NULL OR u.id IS NULL LIMIT 1'
        ).fetchone()
        if orphan is not None:
            raise ValueError("Not a LIFE database; orphaned Cogvative events")
        mismatch = conn.execute(
            'SELECT 1 FROM "cog_events" e JOIN "projects" p '
            'ON e.project_id = p.id WHERE e.owner_id != p.owner_id LIMIT 1'
        ).fetchone()
        if mismatch is not None:
            raise ValueError("Not a LIFE database; Cogvative event owner mismatch")
    if "cog_lines" in tables:
        columns = {row[1] for row in conn.execute('PRAGMA table_info("cog_lines")')}
        if "event_id" not in columns:
            raise ValueError("Not a LIFE database; Cogvative line event reference missing")
        orphan = conn.execute(
            'SELECT 1 FROM "cog_lines" l LEFT JOIN "cog_events" e '
            'ON l.event_id = e.id WHERE e.id IS NULL LIMIT 1'
        ).fetchone()
        if orphan is not None:
            raise ValueError("Not a LIFE database; orphaned Cogvative lines")
    # The current LIFE schema does not declare foreign keys for these
    # relationships, so PRAGMA foreign_key_check alone misses orphaned
    # sessions, projects, project files and credit history. Reject a snapshot
    # that cannot reliably reconnect private records to their owners.
    ownership_checks = (
        ("sessions", "users", "user_id", "id"),
        ("projects", "users", "owner_id", "id"),
        ("files", "projects", "project_id", "id"),
        ("ledger", "users", "user_id", "id"),
    )
    for child, parent, foreign_id, primary_id in ownership_checks:
        orphan = conn.execute(
            f'SELECT 1 FROM "{child}" AS c '
            f'LEFT JOIN "{parent}" AS p ON c."{foreign_id}" = p."{primary_id}" '
            f'WHERE p."{primary_id}" IS NULL LIMIT 1'
        ).fetchone()
        if orphan is not None:
            # Never print account IDs, file paths, session tokens or emails.
            raise ValueError(f"Not a LIFE database; orphaned {child} owner references")
    # Session tokens are stored as lowercase SHA-256 hashes, never plaintext.
    # A malformed token or expiry in a recovered database means session
    # authentication state cannot be trusted after restore. Check only shape;
    # do not print token hashes or account identifiers in error messages.
    bad_session = conn.execute(
        'SELECT 1 FROM "sessions" WHERE '
        'typeof("token_hash") != \'text\' OR length("token_hash") != 64 '
        'OR "token_hash" GLOB \'*[^0-9a-f]*\' '
        'OR typeof("expires") != \'integer\' OR "expires" < 0 LIMIT 1'
    ).fetchone()
    if bad_session is not None:
        raise ValueError("Not a LIFE database; invalid session authentication state")
    # File versions are optimistic-concurrency counters for private project
    # edits. SQLite's dynamic typing permits invalid values in older or
    # lookalike schemas; restoring them could bypass version conflict checks.
    # Never disclose private project IDs, filenames, or contents.
    invalid_file_version = conn.execute(
        'SELECT 1 FROM "files" WHERE typeof("version") != \'integer\' '
        'OR "version" < 1 LIMIT 1'
    ).fetchone()
    if invalid_file_version is not None:
        raise ValueError("Not a LIFE database; invalid project file version")
    # Credit balances are used for authorization to consume paid AI services.
    # SQLite's dynamic typing can admit NULL, text or negative balances even
    # if a lookalike schema contains the expected columns. Reject these before
    # treating a restored snapshot as safe; never print account details.
    invalid_balance = conn.execute(
        'SELECT 1 FROM "users" WHERE typeof("credits") != \'integer\' '
        'OR "credits" < 0 LIMIT 1'
    ).fetchone()
    if invalid_balance is not None:
        raise ValueError("Not a LIFE database; invalid member credit balance")
    # Credit and charge entries must retain integer amounts and the correct
    # sign after restore. A corrupt ledger can otherwise misstate customer
    # credit history even if the SQLite file itself passes integrity_check.
    # Zero-cost charges are currently allowed by store.charge; credits are
    # strictly positive. Never print financial or member row contents.
    invalid_ledger_amount = conn.execute(
        'SELECT 1 FROM "ledger" WHERE '
        'typeof("amount") != \'integer\' '
        'OR "kind" IS NULL OR "kind" NOT IN (\'credit\',\'charge\') '
        'OR ("kind" = \'credit\' AND "amount" <= 0) '
        'OR ("kind" = \'charge\' AND "amount" > 0) LIMIT 1'
    ).fetchone()
    if invalid_ledger_amount is not None:
        raise ValueError("Not a LIFE database; invalid credit ledger amount or kind")
    return len(tables)


def verify_restore_drill(snapshot: Path):
    """Prove that the snapshot can be restored to a new temporary database."""
    with tempfile.TemporaryDirectory(prefix="life-restore-drill-") as temp_dir:
        with readonly_connection(snapshot) as src:
            validate_database(src)
            with sqlite3.connect(str(Path(temp_dir) / "restored.sqlite3")) as restored:
                src.backup(restored)
                return validate_database(restored)


def backup_and_verify(source: Path, destination: Path):
    source = Path(source).expanduser().resolve(strict=True)
    destination = Path(destination).expanduser().absolute()
    if not source.is_file():
        raise ValueError("Source is not a regular database file")
    if source == destination or source == destination.resolve():
        raise ValueError("Cannot overwrite the source database")
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("Refusing to replace an existing backup")
    if "public" in destination.parts:
        raise ValueError("Refusing to write a backup within a public web directory")
    # A symlinked parent may disguise a web-served directory (e.g. vault -> public).
    # Check the resolved destination directory as well as the user-supplied path.
    resolved_parent = destination.parent.resolve()
    if "public" in resolved_parent.parts:
        raise ValueError("Refusing to write a backup within a public web directory")
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Reject symlinks anywhere in the directory chain, not only the vault
    # itself. An intermediate alias can otherwise bypass the parent lstat.
    # An existing directory is not made private by mkdir(mode=0700).
    # Refuse a symlink or group/world-accessible parent rather than exposing
    # backup names or allowing another local user to replace the output.
    parent_info = destination.parent.lstat()
    if not stat.S_ISDIR(parent_info.st_mode):
        raise ValueError("Backup directory must be a real private directory, not a symlink")
    if parent_info.st_mode & 0o077:
        raise ValueError("Backup directory must have mode 0700; chmod 700 the vault first")
    if any(part.is_symlink() for part in destination.parent.parents):
        raise ValueError("Backup directory path cannot traverse symlinks")
    tmp_path = None
    try:
        fd, raw_path = tempfile.mkstemp(prefix=".life-backup-", suffix=".sqlite3", dir=destination.parent)
        os.close(fd)
        tmp_path = Path(raw_path)
        with readonly_connection(source) as src:
            # The SQLite online backup API captures a consistent snapshot even
            # while the live source uses WAL and receives concurrent writes.
            with sqlite3.connect(str(tmp_path)) as output:
                src.backup(output)
        tables = verify_restore_drill(tmp_path)
        digest = hashlib.sha256()
        with tmp_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        os.chmod(tmp_path, 0o600)
        # A successful SQLite restore drill does not imply crash durability.
        # Sync the completed snapshot before publishing its name, then sync
        # the parent directory so the new hard link survives a host restart.
        with tmp_path.open("rb") as snapshot_file:
            os.fsync(snapshot_file.fileno())
        # Atomic, no-overwrite publication on the same volume.
        os.link(tmp_path, destination)
        try:
            parent_fd = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
        except BaseException:
            # Do not leave an unconfirmed snapshot at its final backup path.
            # A failed directory sync must allow a clean, no-overwrite retry.
            destination.unlink(missing_ok=True)
            raise
        return {"backup": str(destination), "sha256": digest.hexdigest(),
                "bytes": destination.stat().st_size, "tables_verified": tables,
                "restore_drill": "passed", "encrypted_off_host_copy": "NOT_VERIFIED"}
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)



def verify_existing_copy(snapshot: Path, expected_sha256: str):
    """Verify a restored off-host copy against a separately retained digest.

    Passing proves byte identity and SQLite recoverability, not off-host
    placement, encryption, access control, or retention.
    """
    if not isinstance(expected_sha256, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", expected_sha256):
        raise ValueError("Expected SHA-256 must be exactly 64 hexadecimal characters")
    # Operator restores can contain account, session and project secrets.
    # Refuse symlink indirection and copies exposed to other local users.
    # This checks the final path only; operators must also secure parent
    # directories and avoid concurrently writable/untrusted restore folders.
    snapshot = Path(snapshot).expanduser().absolute()
    # Restored copies contain private account and session data. A private file
    # in a shared directory still exposes its name and enables path swapping.
    # Require the same private, non-symlinked vault as backup creation.
    parent = snapshot.parent
    parent_metadata = parent.lstat()
    if not stat.S_ISDIR(parent_metadata.st_mode):
        raise ValueError("Restore directory must be a real private directory, not a symlink")
    if parent_metadata.st_mode & 0o077:
        raise ValueError("Restore directory must have mode 0700; chmod 700 the vault first")
    if any(part.is_symlink() for part in parent.parents):
        raise ValueError("Restore directory path cannot traverse symlinks")
    if "public" in snapshot.parts or "public" in parent.resolve().parts:
        raise ValueError("Refusing to verify a backup within a public web directory")
    metadata = snapshot.lstat()
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError("Backup copy must be a regular file, not a symlink")
    if metadata.st_mode & 0o077:
        raise ValueError("Backup copy is accessible to group/others; chmod 600 first")
    # A second hard-link name can grant access to the same mutable inode even
    # though this path is private and not a symlink. Require a standalone copy.
    if metadata.st_nlink != 1:
        raise ValueError("Backup copy has multiple hard links; restore to a standalone private file")
    # Pin the source inode using O_NOFOLLOW. Do not hash one path and later
    # reopen that path for the restore drill: a replaced/modified copy could
    # otherwise be accepted after its original bytes passed the digest check.
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(snapshot, flags), "rb") as source_file:
        opened = os.fstat(source_file.fileno())
        if not stat.S_ISREG(opened.st_mode):
            raise ValueError("Backup copy must be a regular file, not a symlink")
        if opened.st_mode & 0o077:
            raise ValueError("Backup copy is accessible to group/others; chmod 600 first")
        # Recheck the opened inode, not just the pathname metadata, to catch
        # a path swap between lstat() and open().
        if opened.st_nlink != 1:
            raise ValueError("Backup copy has multiple hard links; restore to a standalone private file")
        with tempfile.TemporaryDirectory(prefix="life-verify-copy-") as temp_dir:
            # Both digest and restore validation use this private, pinned copy,
            # not a potentially mutable operator-controlled restore path.
            frozen = Path(temp_dir) / "snapshot.sqlite3"
            digest = hashlib.sha256()
            with os.fdopen(os.open(frozen, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as output:
                for chunk in iter(lambda: source_file.read(1024 * 1024), b""):
                    digest.update(chunk)
                    output.write(chunk)
            actual = digest.hexdigest()
            if not hmac.compare_digest(actual, expected_sha256.lower()):
                raise ValueError("Backup SHA-256 mismatch; refusing restore verification")
            tables = verify_restore_drill(frozen)
            size = frozen.stat().st_size
    return {"backup": str(snapshot), "sha256": actual,
            "bytes": size, "tables_verified": tables,
            "restore_drill": "passed", "encrypted_off_host_copy": "NOT_VERIFIED"}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help="LIFE_DB_PATH SQLite database")
    parser.add_argument("--destination", type=Path, help="New private backup filepath (must not exist)")
    parser.add_argument("--verify-copy", type=Path, help="Restored copy to verify read-only")
    parser.add_argument("--expected-sha256", help="Trusted digest from the original backup report")
    args = parser.parse_args()
    if args.verify_copy is not None:
        if args.source is not None or args.destination is not None or args.expected_sha256 is None:
            parser.error("--verify-copy requires --expected-sha256 and cannot be combined with --source/--destination")
        action = lambda: verify_existing_copy(args.verify_copy, args.expected_sha256)
    else:
        if args.source is None or args.destination is None or args.expected_sha256 is not None:
            parser.error("Backup creation requires --source and --destination only")
        action = lambda: backup_and_verify(args.source, args.destination)
    try:
        print(json.dumps(action(), sort_keys=True))
    except (OSError, sqlite3.Error, ValueError) as exc:
        parser.exit(1, "LIFE snapshot NOT verified: " + str(exc) + "\n")

if __name__ == "__main__":
    main()
