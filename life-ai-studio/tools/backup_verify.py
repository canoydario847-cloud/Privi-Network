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
