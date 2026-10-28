"""Synthetic-only recovery tests for the LIFE private file size contract."""
import importlib.util
import sqlite3
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "life_backup_file_limit",
    Path(__file__).resolve().parents[1] / "tools" / "backup_verify.py",
)
backup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backup)


@pytest.mark.parametrize("content,accepted", [
    ("", True),
    ("x" * 60000, True),
    ("🌌" * 60000, True),
    ("x" * 60001, False),
    ("🌌" * 60001, False),
])
def test_restored_private_file_content_size_limit(tmp_path, content, accepted):
    source = tmp_path / "life.sqlite3"
    with sqlite3.connect(source) as db:
        db.executescript(
            "CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, "
            "pwdhash TEXT NOT NULL, wallet TEXT UNIQUE, member_since INTEGER NOT NULL, "
            "credits INTEGER NOT NULL DEFAULT 0);"
            "CREATE TABLE sessions (token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, "
            "expires INTEGER NOT NULL);"
            "CREATE TABLE projects (id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, "
            "title TEXT NOT NULL, kind TEXT NOT NULL, created INTEGER NOT NULL);"
            "CREATE TABLE files (project_id TEXT NOT NULL, path TEXT NOT NULL, "
            "content TEXT NOT NULL, version INTEGER NOT NULL, PRIMARY KEY(project_id,path));"
            "CREATE TABLE ledger (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, "
            "kind TEXT NOT NULL, service TEXT NOT NULL, amount INTEGER NOT NULL, "
            "idempotency TEXT NOT NULL, created INTEGER NOT NULL, "
            "UNIQUE(user_id,idempotency));"
            "INSERT INTO users VALUES ('u1','synthetic@example.invalid','hash',NULL,1,0);"
            "INSERT INTO projects VALUES ('p1','u1','Synthetic','code',1);"
        )
        db.execute("INSERT INTO files VALUES ('p1','src/main.txt',?,1)", (content,))
    destination = tmp_path / "vault" / "snapshot.sqlite3"
    if accepted:
        assert backup.backup_and_verify(source, destination)["restore_drill"] == "passed"
    else:
        with pytest.raises(ValueError, match="invalid private project file text"):
            backup.backup_and_verify(source, destination)
        assert not destination.exists(), "Oversized private content must not publish a backup"
