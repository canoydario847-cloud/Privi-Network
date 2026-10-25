"""Zero-customer-data integration tests for the SQLite snapshot/restore drill."""
import importlib.util
import hashlib
import os
import shutil
import subprocess
import sys
import sqlite3
import stat
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("life_backup_verify", Path(__file__).resolve().parents[1] / "tools" / "backup_verify.py")
backup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backup)


def make_database(path):
    with sqlite3.connect(str(path)) as db:
        db.executescript(
            "CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT, pwdhash TEXT,"
            " wallet TEXT, member_since INTEGER, credits INTEGER);"
            "CREATE TABLE sessions (token_hash TEXT PRIMARY KEY, user_id TEXT, expires INTEGER);"
            "CREATE TABLE projects (id TEXT PRIMARY KEY, owner_id TEXT, title TEXT,"
            " kind TEXT, created INTEGER);"
            "CREATE TABLE files (project_id TEXT, path TEXT, content TEXT, version INTEGER,"
            " PRIMARY KEY(project_id,path));"
            "CREATE TABLE ledger (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, kind TEXT,"
            " service TEXT, amount INTEGER, idempotency TEXT NOT NULL, created INTEGER,"
            " UNIQUE(user_id,idempotency));"
            "CREATE TABLE settings (name TEXT PRIMARY KEY, value TEXT NOT NULL);"
            "INSERT INTO settings VALUES ('device-theme', 'cosmic');"
        )


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


def test_backup_refuses_existing_group_accessible_vault(tmp_path):
    source = tmp_path / "life.sqlite3"
    make_database(source)
    vault = tmp_path / "shared-vault"
    vault.mkdir()
    os.chmod(vault, 0o750)
    destination = vault / "backup.sqlite3"
    with pytest.raises(ValueError, match="mode 0700"):
        backup.backup_and_verify(source, destination)
    assert not destination.exists()
    os.chmod(vault, 0o700)
    assert backup.backup_and_verify(source, destination)["restore_drill"] == "passed"


def test_backup_refuses_symlink_to_private_vault(tmp_path):
    source = tmp_path / "life.sqlite3"
    make_database(source)
    vault = tmp_path / "private-vault"
    vault.mkdir(mode=0o700)
    alias = tmp_path / "vault-alias"
    alias.symlink_to(vault, target_is_directory=True)
    destination = alias / "backup.sqlite3"
    with pytest.raises(ValueError, match="real private directory"):
        backup.backup_and_verify(source, destination)
    assert not (vault / "backup.sqlite3").exists()


def test_backup_rejects_symlinked_intermediate_directory(tmp_path):
    source = tmp_path / "life.sqlite3"
    make_database(source)
    vault = tmp_path / "private-vault"
    nested = vault / "snapshots"
    nested.mkdir(parents=True, mode=0o700)
    alias = tmp_path / "vault-alias"
    alias.symlink_to(vault, target_is_directory=True)
    destination = alias / "snapshots" / "backup.sqlite3"
    with pytest.raises(ValueError, match="cannot traverse symlinks"):
        backup.backup_and_verify(source, destination)
    assert not (nested / "backup.sqlite3").exists()


def test_unrelated_valid_sqlite_is_not_accepted_as_life_backup(tmp_path):
    source = tmp_path / "unrelated.sqlite3"
    with sqlite3.connect(str(source)) as db:
        db.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")
    dest = tmp_path / "vault" / "invalid-life-copy.sqlite3"
    with pytest.raises(ValueError, match="missing core tables"):
        backup.backup_and_verify(source, dest)
    assert not dest.exists()


def test_spoofed_life_table_names_are_rejected(tmp_path):
    source = tmp_path / "spoof.sqlite3"
    with sqlite3.connect(str(source)) as db:
        db.executescript(
            "CREATE TABLE users (id TEXT PRIMARY KEY);"
            "CREATE TABLE sessions (token_hash TEXT PRIMARY KEY);"
            "CREATE TABLE projects (id TEXT PRIMARY KEY);"
            "CREATE TABLE files (project_id TEXT, path TEXT);"
            "CREATE TABLE ledger (id TEXT PRIMARY KEY);"
        )
    destination = tmp_path / "vault" / "spoof-copy.sqlite3"
    with pytest.raises(ValueError, match="missing columns"):
        backup.backup_and_verify(source, destination)
    assert not destination.exists()


def test_matching_columns_without_session_primary_key_are_rejected(tmp_path):
    source = tmp_path / "missing-session-key.sqlite3"
    make_database(source)
    with sqlite3.connect(str(source)) as db:
        db.execute("DROP TABLE sessions")
        db.execute("CREATE TABLE sessions (token_hash TEXT, user_id TEXT, expires INTEGER)")
    destination = tmp_path / "vault" / "unsafe-copy.sqlite3"
    with pytest.raises(ValueError, match="sessions primary key mismatch"):
        backup.backup_and_verify(source, destination)
    assert not destination.exists()


def test_matching_file_columns_without_composite_key_are_rejected(tmp_path):
    source = tmp_path / "missing-file-key.sqlite3"
    make_database(source)
    with sqlite3.connect(str(source)) as db:
        db.execute("DROP TABLE files")
        db.execute("CREATE TABLE files (project_id TEXT, path TEXT, content TEXT, version INTEGER)")
    destination = tmp_path / "vault" / "unsafe-files-copy.sqlite3"
    with pytest.raises(ValueError, match="files primary key mismatch"):
        backup.backup_and_verify(source, destination)
    assert not destination.exists()


def test_matching_ledger_columns_without_unique_idempotency_are_rejected(tmp_path):
    source = tmp_path / "missing-ledger-unique.sqlite3"
    make_database(source)
    with sqlite3.connect(str(source)) as db:
        db.execute("DROP TABLE ledger")
        db.execute(
            "CREATE TABLE ledger (id TEXT PRIMARY KEY, user_id TEXT NOT NULL,"
            " kind TEXT, service TEXT, amount INTEGER, idempotency TEXT NOT NULL,"
            " created INTEGER)"
        )
    destination = tmp_path / "vault" / "unsafe-ledger-copy.sqlite3"
    with pytest.raises(ValueError, match="ledger idempotency UNIQUE constraint missing"):
        backup.backup_and_verify(source, destination)
    assert not destination.exists()


def test_partial_unique_ledger_index_does_not_satisfy_restore_guard(tmp_path):
    source = tmp_path / "partial-ledger-unique.sqlite3"
    make_database(source)
    with sqlite3.connect(str(source)) as db:
        db.execute("DROP TABLE ledger")
        db.execute(
            "CREATE TABLE ledger (id TEXT PRIMARY KEY, user_id TEXT NOT NULL,"
            " kind TEXT, service TEXT, amount INTEGER, idempotency TEXT NOT NULL,"
            " created INTEGER)"
        )
        db.execute(
            "CREATE UNIQUE INDEX ledger_partial ON ledger(user_id,idempotency)"
            " WHERE kind='charge'"
        )
    destination = tmp_path / "vault" / "partial-index-copy.sqlite3"
    with pytest.raises(ValueError, match="ledger idempotency UNIQUE constraint missing"):
        backup.backup_and_verify(source, destination)
    assert not destination.exists()


def test_missing_project_files_table_is_rejected(tmp_path):
    source = tmp_path / "no-files.sqlite3"
    make_database(source)
    with sqlite3.connect(str(source)) as db:
        db.execute("DROP TABLE files")
    destination = tmp_path / "vault" / "missing-files-copy.sqlite3"
    with pytest.raises(ValueError, match="missing core tables"):
        backup.backup_and_verify(source, destination)
    assert not destination.exists()


def test_empty_sqlite_is_not_accepted_as_life_backup(tmp_path):
    source = tmp_path / "empty.sqlite3"
    with sqlite3.connect(str(source)) as db:
        db.execute("PRAGMA user_version=1")
    dest = tmp_path / "vault" / "empty-copy.sqlite3"
    with pytest.raises(ValueError, match="missing core tables"):
        backup.backup_and_verify(source, dest)
    assert not dest.exists()


def test_backup_fsyncs_snapshot_before_directory(tmp_path, monkeypatch):
    source = tmp_path / "life.sqlite3"
    make_database(source)
    destination = tmp_path / "vault" / "snapshot.sqlite3"
    observed = []
    original_fsync = os.fsync

    def tracked_fsync(fd):
        kind = "directory" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file"
        observed.append(kind)
        return original_fsync(fd)

    monkeypatch.setattr(backup.os, "fsync", tracked_fsync)
    result = backup.backup_and_verify(source, destination)
    assert result["restore_drill"] == "passed"
    assert observed == ["file", "directory"]


def test_directory_fsync_failure_never_reports_success(tmp_path, monkeypatch):
    source = tmp_path / "life.sqlite3"
    make_database(source)
    destination = tmp_path / "vault" / "snapshot.sqlite3"
    original_fsync = os.fsync

    def fail_directory_fsync(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("simulated directory fsync failure")
        return original_fsync(fd)

    monkeypatch.setattr(backup.os, "fsync", fail_directory_fsync)
    with pytest.raises(OSError, match="directory fsync failure"):
        backup.backup_and_verify(source, destination)
    # A failed directory sync must not leave an unverified published backup.
    assert not destination.exists()
    monkeypatch.setattr(backup.os, "fsync", original_fsync)
    assert backup.backup_and_verify(source, destination)["restore_drill"] == "passed"


def test_independently_restored_copy_matches_trusted_digest_and_restores(tmp_path):
    source = tmp_path / "life.sqlite3"
    make_database(source)
    local = tmp_path / "vault" / "original.sqlite3"
    created = backup.backup_and_verify(source, local)
    restored_copy = tmp_path / "restored-from-other-host.sqlite3"
    shutil.copyfile(local, restored_copy)
    os.chmod(restored_copy, 0o600)
    verified = backup.verify_existing_copy(restored_copy, created["sha256"])
    assert verified["sha256"] == created["sha256"]
    assert verified["restore_drill"] == "passed"
    assert verified["encrypted_off_host_copy"] == "NOT_VERIFIED"


def test_modified_restored_copy_rejected_before_restore(tmp_path):
    source = tmp_path / "life.sqlite3"
    make_database(source)
    local = tmp_path / "vault" / "original.sqlite3"
    created = backup.backup_and_verify(source, local)
    altered = tmp_path / "altered.sqlite3"
    shutil.copyfile(local, altered)
    os.chmod(altered, 0o600)
    with altered.open("ab") as handle:
        handle.write(b"changed after original backup")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        backup.verify_existing_copy(altered, created["sha256"])


def test_existing_copy_requires_trusted_digest_and_real_life_schema(tmp_path):
    unrelated = tmp_path / "unrelated.sqlite3"
    with sqlite3.connect(str(unrelated)) as db:
        db.execute("CREATE TABLE unrelated (id INTEGER)")
    actual_hash = hashlib.sha256(unrelated.read_bytes()).hexdigest()
    os.chmod(unrelated, 0o600)
    with pytest.raises(ValueError, match="64 hexadecimal"):
        backup.verify_existing_copy(unrelated, "invalid")
    with pytest.raises(ValueError, match="missing core tables"):
        backup.verify_existing_copy(unrelated, actual_hash)


def test_verify_copy_cli_requires_digest_and_reports_failure(tmp_path):
    source = tmp_path / "life.sqlite3"
    make_database(source)
    os.chmod(source, 0o600)
    result = subprocess.run(
        [sys.executable, str(SPEC.origin), "--verify-copy", str(source),
         "--expected-sha256", "0" * 64],
        text=True, capture_output=True, check=False,
    )
    assert result.returncode != 0
    assert "SHA-256 mismatch" in result.stderr


def test_verify_copy_rejects_world_readable_file_before_digest(tmp_path):
    source = tmp_path / "life.sqlite3"
    make_database(source)
    os.chmod(source, 0o644)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="chmod 600"):
        backup.verify_existing_copy(source, digest)


def test_verify_copy_rejects_symlink_even_to_private_backup(tmp_path):
    source = tmp_path / "life.sqlite3"
    make_database(source)
    os.chmod(source, 0o600)
    alias = tmp_path / "link.sqlite3"
    alias.symlink_to(source)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="not a symlink"):
        backup.verify_existing_copy(alias, digest)


def test_verify_copy_rejects_hardlinked_backup_even_if_mode_is_private(tmp_path):
    source = tmp_path / "restored.sqlite3"
    make_database(source)
    os.chmod(source, 0o600)
    other_name = tmp_path / "second-name.sqlite3"
    os.link(source, other_name)
    assert os.stat(source).st_nlink == 2
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="multiple hard links"):
        backup.verify_existing_copy(source, digest)
    # A real standalone copy is still allowed after removing the alias.
    other_name.unlink()
    assert backup.verify_existing_copy(source, digest)["restore_drill"] == "passed"


def test_verify_copy_restores_the_exact_bytes_that_passed_checksum(tmp_path, monkeypatch):
    source = tmp_path / "restored.sqlite3"
    make_database(source)
    os.chmod(source, 0o600)
    expected = hashlib.sha256(source.read_bytes()).hexdigest()
    original_drill = backup.verify_restore_drill

    def mutate_original_before_restore(frozen_copy):
        # Simulate a changed/replaced operator restore file after checksum.
        # The restore must read only the private, checksum-pinned copy.
        assert Path(frozen_copy) != source
        source.write_bytes(b"replaced after checksum")
        return original_drill(frozen_copy)

    monkeypatch.setattr(backup, "verify_restore_drill", mutate_original_before_restore)
    result = backup.verify_existing_copy(source, expected)
    assert result["sha256"] == expected
    assert result["restore_drill"] == "passed"
    assert source.read_bytes() == b"replaced after checksum"


def test_verify_copy_rejects_group_accessible_restore_directory(tmp_path):
    vault = tmp_path / "shared-restore"
    vault.mkdir(mode=0o700)
    restored = vault / "life.sqlite3"
    make_database(restored)
    os.chmod(restored, 0o600)
    digest = hashlib.sha256(restored.read_bytes()).hexdigest()
    os.chmod(vault, 0o750)
    with pytest.raises(ValueError, match="mode 0700"):
        backup.verify_existing_copy(restored, digest)
    os.chmod(vault, 0o700)
    assert backup.verify_existing_copy(restored, digest)["restore_drill"] == "passed"


def test_verify_copy_rejects_symlinked_intermediate_directory(tmp_path):
    vault = tmp_path / "private-vault"
    nested = vault / "restored"
    nested.mkdir(parents=True, mode=0o700)
    restored = nested / "life.sqlite3"
    make_database(restored)
    os.chmod(restored, 0o600)
    digest = hashlib.sha256(restored.read_bytes()).hexdigest()
    alias = tmp_path / "vault-alias"
    alias.symlink_to(vault, target_is_directory=True)
    with pytest.raises(ValueError, match="cannot traverse symlinks"):
        backup.verify_existing_copy(alias / "restored" / "life.sqlite3", digest)
    assert backup.verify_existing_copy(restored, digest)["restore_drill"] == "passed"


def test_verify_copy_rejects_symlinked_restore_directory(tmp_path):
    vault = tmp_path / "private-restore"
    vault.mkdir(mode=0o700)
    restored = vault / "life.sqlite3"
    make_database(restored)
    os.chmod(restored, 0o600)
    digest = hashlib.sha256(restored.read_bytes()).hexdigest()
    alias = tmp_path / "restore-alias"
    alias.symlink_to(vault, target_is_directory=True)
    with pytest.raises(ValueError, match="not a symlink"):
        backup.verify_existing_copy(alias / "life.sqlite3", digest)
    assert backup.verify_existing_copy(restored, digest)["restore_drill"] == "passed"
