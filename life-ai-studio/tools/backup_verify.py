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
        parent_fd = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
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
    metadata = snapshot.lstat()
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError("Backup copy must be a regular file, not a symlink")
    if metadata.st_mode & 0o077:
        raise ValueError("Backup copy is accessible to group/others; chmod 600 first")
    snapshot = snapshot.resolve(strict=True)
    digest = hashlib.sha256()
    with snapshot.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    if not hmac.compare_digest(actual, expected_sha256.lower()):
        raise ValueError("Backup SHA-256 mismatch; refusing restore verification")
    tables = verify_restore_drill(snapshot)
    return {"backup": str(snapshot), "sha256": actual,
            "bytes": snapshot.stat().st_size, "tables_verified": tables,
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
