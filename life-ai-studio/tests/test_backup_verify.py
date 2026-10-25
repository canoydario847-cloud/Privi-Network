"""Zero-customer-data integration tests for the SQLite snapshot/restore drill."""
import importlib.util
import os
import sqlite3
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("life_backup_verify", Path(__file__).resolve().parents[1] / "tools" / "backup_verify.py")
backup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backup)


def make_database(path):
    with sqlite3.connect(str(path)) as db:
        db.executescript("CREATE TABLE settings (name TEXT PRIMARY KEY, value TEXT NOT NULL);"
                         "INSERT INTO settings VALUES ('device-theme', 'cosmic');")


def test_creates_private_consistent_snapshot_and_restores(tmp_path):
    source = tmp_path / "life.sqlite3"
    make_database(source)
    dest = tmp_path / "vault" / "life-copy.sqlite3"
    result = backup.backup_and_verify(source, dest)
    assert result["restore_drill"] == "passed"
    assert result["encrypted_off_host_copy"] == "NOT_VERIFIED"
    assert len(result["sha256"]) == 64
    assert os.stat(dest).st_mode & 0o777 == 0o600
    with sqlite3.connect(str(source)) as db:
        db.execute("UPDATE settings SET value='changed'")
    with backup.readonly_connection(dest) as db:
        assert db.execute("SELECT value FROM settings").fetchone()[0] == "cosmic"


def test_existing_backup_is_not_overwritten(tmp_path):
    source, dest = tmp_path / "life.sqlite3", tmp_path / "existing.sqlite3"
    make_database(source)
    dest.write_bytes(b"KEEP THIS FILE")
    with pytest.raises(FileExistsError):
        backup.backup_and_verify(source, dest)
    assert dest.read_bytes() == b"KEEP THIS FILE"


def test_missing_source_does_not_create_blank_database(tmp_path):
    missing = tmp_path / "missing.sqlite3"
    with pytest.raises(FileNotFoundError):
        backup.backup_and_verify(missing, tmp_path / "out.sqlite3")
    assert not missing.exists()


def test_public_directory_and_self_overwrite_rejected(tmp_path):
    source = tmp_path / "life.sqlite3"
    make_database(source)
    with pytest.raises(ValueError):
        backup.backup_and_verify(source, source)
    with pytest.raises(ValueError, match="public"):
        backup.backup_and_verify(source, tmp_path / "public" / "backup.sqlite3")


def test_corrupt_database_restore_drill_fails(tmp_path):
    corrupted = tmp_path / "corrupt.sqlite3"
    corrupted.write_bytes(b"this is not sqlite data")
    with pytest.raises((ValueError, sqlite3.DatabaseError)):
        backup.backup_and_verify(corrupted, tmp_path / "vault" / "out.sqlite3")
    assert not (tmp_path / "vault" / "out.sqlite3").exists()


def test_symlinked_backup_parent_into_public_is_rejected(tmp_path):
    source = tmp_path / "life.sqlite3"
    make_database(source)
    web_root = tmp_path / "public"
    web_root.mkdir()
    alias = tmp_path / "private-looking-vault"
    alias.symlink_to(web_root, target_is_directory=True)
    with pytest.raises(ValueError, match="public"):
        backup.backup_and_verify(source, alias / "life-copy.sqlite3")
    assert not (web_root / "life-copy.sqlite3").exists()
