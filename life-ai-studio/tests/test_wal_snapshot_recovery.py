"""Regression: a LIFE SQLite WAL backup must capture committed state only.

Synthetic data only. This is a single-instance backup test, not proof of
off-host encryption, disaster recovery, or production durability.
"""
import importlib.util
import sqlite3
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "life_backup_verify_wal",
    Path(__file__).resolve().parents[1] / "tools" / "backup_verify.py",
)
backup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backup)


def test_wal_backup_excludes_uncommitted_writer_and_survives_later_commit(tmp_path):
    source = tmp_path / "life.sqlite3"
    with sqlite3.connect(source) as db:
        db.executescript(
            "CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL,"
            " pwdhash TEXT NOT NULL, wallet TEXT UNIQUE, member_since INTEGER NOT NULL,"
            " credits INTEGER NOT NULL DEFAULT 0);"
            "CREATE TABLE sessions (token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL,"
            " expires INTEGER NOT NULL);"
            "CREATE TABLE projects (id TEXT PRIMARY KEY, owner_id TEXT NOT NULL,"
            " title TEXT NOT NULL, kind TEXT NOT NULL, created INTEGER NOT NULL);"
            "CREATE TABLE files (project_id TEXT NOT NULL, path TEXT NOT NULL,"
            " content TEXT NOT NULL, version INTEGER NOT NULL,"
            " PRIMARY KEY(project_id,path));"
            "CREATE TABLE ledger (id TEXT PRIMARY KEY, user_id TEXT NOT NULL,"
            " kind TEXT NOT NULL, service TEXT NOT NULL, amount INTEGER NOT NULL,"
            " idempotency TEXT NOT NULL, created INTEGER NOT NULL,"
            " UNIQUE(user_id,idempotency));"
            "INSERT INTO users VALUES ('u1','synthetic@example.invalid',"
            "'synthetic-hash',NULL,1,7);"
        )

    # Keep the WAL writer open: a committed change is visible to SQLite
    # backup() even if it has not been checkpointed to the main DB file.
    with sqlite3.connect(source, isolation_level=None) as writer:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        writer.execute("UPDATE users SET credits=8 WHERE id='u1'")
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("UPDATE users SET credits=999 WHERE id='u1'")
        destination = tmp_path / "vault" / "snapshot.sqlite3"
        result = backup.backup_and_verify(source, destination)
        assert result["restore_drill"] == "passed"
        assert result["encrypted_off_host_copy"] == "NOT_VERIFIED"
        # The uncommitted update must not leak into the snapshot.
        with backup.readonly_connection(destination) as snapshot:
            assert snapshot.execute(
                "SELECT credits FROM users WHERE id='u1'"
            ).fetchone()[0] == 8
        writer.execute("COMMIT")
        with backup.readonly_connection(source) as live:
            assert live.execute(
                "SELECT credits FROM users WHERE id='u1'"
            ).fetchone()[0] == 999
        # Later source commits must not mutate the independently verified copy.
        with backup.readonly_connection(destination) as snapshot:
            assert snapshot.execute(
                "SELECT credits FROM users WHERE id='u1'"
            ).fetchone()[0] == 8
