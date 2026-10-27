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
            "CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, pwdhash TEXT,"
            " wallet TEXT UNIQUE, member_since INTEGER, credits INTEGER);"
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


@pytest.mark.parametrize("password_hash, valid", [
    ("synthetic-hash", True),
    (None, False),
    ("", False),
    ("  \t  ", False),
    (b"binary-hash", False),
])
def test_restored_account_requires_nonblank_text_password_hash(tmp_path, password_hash, valid):
    source = tmp_path / "life.sqlite3"
    make_database(source)
    with sqlite3.connect(str(source)) as db:
        db.execute(
            "INSERT INTO users (id,email,pwdhash,wallet,member_since,credits) "
            "VALUES (?,?,?,?,?,?)",
            ("u1", "synthetic@example.invalid", password_hash, None, 1, 0),
        )
    destination = tmp_path / "vault" / "snapshot.sqlite3"
    if valid:
        assert backup.backup_and_verify(source, destination)["restore_drill"] == "passed"
    else:
        with pytest.raises(ValueError, match="invalid member password hash"):
            backup.backup_and_verify(source, destination)
        assert not destination.exists(), "Malformed authentication state must not publish a backup"


@pytest.mark.parametrize("balance, valid", [
    (0, True),
    (42, True),
    (None, False),
    (-1, False),
    ("invalid", False),
    (1.5, False),
])
def test_restored_member_credit_balance_is_nonnegative_integer(tmp_path, balance, valid):
    source = tmp_path / "life.sqlite3"
    make_database(source)
    with sqlite3.connect(str(source)) as db:
        db.execute(
            "INSERT INTO users (id,email,pwdhash,wallet,member_since,credits) "
            "VALUES (?,?,?,?,?,?)",
            ("u1", "member@example.test", "synthetic-hash", None, 1, balance),
        )
    destination = tmp_path / "vault" / "backup.sqlite3"
    if valid:
        assert backup.backup_and_verify(source, destination)["restore_drill"] == "passed"
    else:
        with pytest.raises(ValueError, match="invalid member credit balance"):
            backup.backup_and_verify(source, destination)
        assert not destination.exists(), "Invalid balances must not publish a backup"


@pytest.mark.parametrize("value, expected", [
    (1, None),
    (None, "invalid membership timestamp"),
    (-1, "invalid membership timestamp"),
    ("unknown", "invalid membership timestamp"),
    (1.5, "invalid membership timestamp"),
])
def test_restored_membership_timestamp_is_integer_nonnegative(tmp_path, value, expected):
    source = tmp_path / "life.sqlite3"
    make_database(source)
    with sqlite3.connect(str(source)) as db:
        db.execute(
            "INSERT INTO users (id,email,pwdhash,wallet,member_since,credits) "
            "VALUES (?,?,?,?,?,?)",
            ("u1", "member@example.test", "synthetic-hash", None, value, 0),
        )
    destination = tmp_path / "vault" / "backup.sqlite3"
    if expected is None:
        assert backup.backup_and_verify(source, destination)["restore_drill"] == "passed"
    else:
        with pytest.raises(ValueError, match=expected):
            backup.backup_and_verify(source, destination)
        assert not destination.exists(), "Invalid membership timestamps must not publish a backup"


@pytest.mark.parametrize("scenario, expected", [
    ("valid", None),
    ("orphan", "invalid wallet challenge ownership"),
    ("null_nonce", "invalid wallet challenge ownership"),
    ("missing_primary_key", "wallet challenge nonce primary key missing"),
    ("missing_message", "wallet challenge columns missing"),
    ("nullable_owner", "wallet challenge required fields nullable"),
    ("short_nonce", "invalid wallet challenge state"),
    ("uppercase_nonce", "invalid wallet challenge state"),
    ("text_expiry", "invalid wallet challenge state"),
    ("negative_expiry", "invalid wallet challenge state"),
])
def test_restored_wallet_challenge_ownership(tmp_path, scenario, expected):
    source = tmp_path / "life.sqlite3"
    make_database(source)
    with sqlite3.connect(str(source)) as db:
        db.execute(
            "INSERT INTO users VALUES ('u1','member@example.test','hash',NULL,1,0)"
        )
        columns = (
            "nonce_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, wallet TEXT NOT NULL, "
            "message TEXT NOT NULL, expires INTEGER NOT NULL"
        )
        if scenario == "missing_primary_key":
            columns = columns.replace("nonce_hash TEXT PRIMARY KEY", "nonce_hash TEXT")
        if scenario == "missing_message":
            columns = columns.replace("message TEXT NOT NULL, ", "")
        if scenario == "nullable_owner":
            columns = columns.replace("user_id TEXT NOT NULL", "user_id TEXT")
        db.execute("CREATE TABLE challenges (" + columns + ")")
        if scenario not in ("missing_primary_key", "missing_message", "nullable_owner"):
            db.execute(
                "INSERT INTO challenges VALUES (?,?,?,?,?)",
                (
                    (None if scenario == "null_nonce" else
                     "short" if scenario == "short_nonce" else
                     "A" * 64 if scenario == "uppercase_nonce" else "a" * 64),
                    "absent" if scenario == "orphan" else "u1",
                    "0x" + "a" * 40, "synthetic-test-challenge",
                    "tomorrow" if scenario == "text_expiry" else
                    -1 if scenario == "negative_expiry" else 123456,
                ),
            )
    destination = tmp_path / "vault" / "backup.sqlite3"
    if expected is None:
        assert backup.backup_and_verify(source, destination)["restore_drill"] == "passed"
    else:
        with pytest.raises(ValueError, match=expected):
            backup.backup_and_verify(source, destination)
        assert not destination.exists(), "Invalid authentication state must not publish a backup"


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


@pytest.mark.parametrize("scenario, expected", [
    ("valid", None),
    ("orphan_run", "orphaned AI runs"),
    ("missing_run", "orphaned AI proposals"),
    ("missing_project", "orphaned AI proposals"),
    ("wrong_project", "AI proposal project mismatch"),
])
def test_restored_ai_collaboration_references(tmp_path, scenario, expected):
    source = tmp_path / "life.sqlite3"
    make_database(source)
    with sqlite3.connect(str(source)) as db:
        db.executescript(
            "CREATE TABLE runs (id TEXT PRIMARY KEY, project_id TEXT NOT NULL);"
            "CREATE TABLE proposals (id TEXT PRIMARY KEY, run_id TEXT NOT NULL,"
            " project_id TEXT NOT NULL);"
            "INSERT INTO users VALUES ('u1','member@example.test','hash',NULL,1,0);"
            "INSERT INTO projects VALUES ('p1','u1','First','code',1);"
            "INSERT INTO projects VALUES ('p2','u1','Second','code',1);"
            "INSERT INTO runs VALUES ('r1','p1');"
        )
        if scenario == "orphan_run":
            db.execute("INSERT INTO runs VALUES ('r2','absent')")
        else:
            run = "absent" if scenario == "missing_run" else "r1"
            project = "absent" if scenario == "missing_project" else (
                "p2" if scenario == "wrong_project" else "p1"
            )
            db.execute("INSERT INTO proposals VALUES ('q1',?,?)", (run, project))
    destination = tmp_path / "vault" / "backup.sqlite3"
    if expected is None:
        assert backup.backup_and_verify(source, destination)["restore_drill"] == "passed"
    else:
        with pytest.raises(ValueError, match=expected):
            backup.backup_and_verify(source, destination)
        assert not destination.exists(), "Invalid AI ownership must not publish a backup"


def test_restore_rejects_proposals_without_run_table(tmp_path):
    source = tmp_path / "life.sqlite3"
    make_database(source)
    with sqlite3.connect(str(source)) as db:
        db.execute(
            "CREATE TABLE proposals (id TEXT PRIMARY KEY, run_id TEXT, project_id TEXT)"
        )
    with backup.readonly_connection(source) as db:
        with pytest.raises(ValueError, match="proposals present without runs"):
            backup.validate_database(db)


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


@pytest.mark.parametrize(
    "email_column,wallet_column,expected_message",
    [
        ("email TEXT NOT NULL", "wallet TEXT UNIQUE", "users UNIQUE constraint missing: email"),
        ("email TEXT UNIQUE NOT NULL", "wallet TEXT", "users UNIQUE constraint missing: wallet"),
        ("email TEXT UNIQUE", "wallet TEXT UNIQUE", "users email must be NOT NULL"),
    ],
)
def test_backup_rejects_missing_account_identity_constraints(
    tmp_path, email_column, wallet_column, expected_message
):
    source = tmp_path / "broken-accounts.sqlite3"
    make_database(source)
    with sqlite3.connect(str(source)) as db:
        db.execute("DROP TABLE users")
        db.execute(
            "CREATE TABLE users (id TEXT PRIMARY KEY, "
            + email_column
            + ", pwdhash TEXT, "
            + wallet_column
            + ", member_since INTEGER, credits INTEGER)"
        )
    destination = tmp_path / "vault" / "unsafe-accounts.sqlite3"
    with pytest.raises(ValueError, match=expected_message):
        backup.backup_and_verify(source, destination)
    assert not destination.exists()


def test_partial_account_unique_indexes_do_not_pass_restore_checks(tmp_path):
    source = tmp_path / "partial-account-unique.sqlite3"
    make_database(source)
    with sqlite3.connect(str(source)) as db:
        db.execute("DROP TABLE users")
        db.execute(
            "CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT NOT NULL,"
            " pwdhash TEXT, wallet TEXT, member_since INTEGER, credits INTEGER)"
        )
        db.execute(
            "CREATE UNIQUE INDEX email_partial ON users(email)"
            " WHERE member_since > 0"
        )
        db.execute("CREATE UNIQUE INDEX wallet_unique ON users(wallet)")
    destination = tmp_path / "vault" / "unsafe-accounts.sqlite3"
    with pytest.raises(ValueError, match="users UNIQUE constraint missing: email"):
        backup.backup_and_verify(source, destination)
    assert not destination.exists()


@pytest.mark.parametrize(
    "table,statement",
    [
        ("sessions", "INSERT INTO sessions VALUES ('token-hash', 'missing-user', 100)"),
        ("projects", "INSERT INTO projects VALUES ('p1', 'missing-user', 'title', 'code', 100)"),
        ("files", "INSERT INTO files VALUES ('missing-project', 'file.txt', 'private', 1)"),
        ("ledger", "INSERT INTO ledger VALUES ('l1', 'missing-user', 'charge', 'agent', 1, 'idem1', 100)"),
    ],
)
def test_backup_rejects_orphaned_private_ownership(tmp_path, table, statement):
    source = tmp_path / "orphaned.sqlite3"
    make_database(source)
    with sqlite3.connect(str(source)) as db:
        db.execute(statement)
    destination = tmp_path / "vault" / "orphaned-copy.sqlite3"
    with pytest.raises(ValueError, match=f"orphaned {table} owner references"):
        backup.backup_and_verify(source, destination)
    assert not destination.exists()


def test_backup_accepts_consistent_account_project_and_ledger_ownership(tmp_path):
    source = tmp_path / "owned.sqlite3"
    make_database(source)
    with sqlite3.connect(str(source)) as db:
        db.execute(
            "INSERT INTO users VALUES ('u1', 'u@example.test', 'test-hash', NULL, 1, 5)"
        )
        db.execute("INSERT INTO sessions VALUES ('" + "a" * 64 + "', 'u1', 100)")
        db.execute("INSERT INTO projects VALUES ('p1', 'u1', 'title', 'code', 100)")
        db.execute("INSERT INTO files VALUES ('p1', 'file.txt', 'private', 1)")
        db.execute(
            "INSERT INTO ledger VALUES ('l1', 'u1', 'charge', 'agent', -1, 'idem1', 100)"
        )
    destination = tmp_path / "vault" / "owned-copy.sqlite3"
    assert backup.backup_and_verify(source, destination)["restore_drill"] == "passed"


@pytest.mark.parametrize("key, valid", [
    ("retry-123", True),
    ("x" * 180, True),
    ("", False),
    ("  \t\n  ", False),
    ("x" * 181, False),
    (b"binary-key", False),
])
def test_backup_rejects_invalid_credit_ledger_retry_keys(tmp_path, key, valid):
    source = tmp_path / "life.sqlite3"
    make_database(source)
    with sqlite3.connect(str(source)) as db:
        db.execute(
            "INSERT INTO users VALUES ('u1','member@example.test','synthetic-hash',NULL,1,1)"
        )
        db.execute(
            "INSERT INTO ledger VALUES (?,?,?,?,?,?,?)",
            ("l1", "u1", "credit", "test", 1, key, 1),
        )
    destination = tmp_path / "vault" / "snapshot.sqlite3"
    if valid:
        assert backup.backup_and_verify(source, destination)["restore_drill"] == "passed"
    else:
        with pytest.raises(ValueError, match="invalid credit ledger idempotency key"):
            backup.backup_and_verify(source, destination)
        assert not destination.exists(), "Malformed retry keys must not publish a backup"


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


@pytest.mark.parametrize("scenario,expected", [
    ("valid", None),
    ("orphan_event", "orphaned Cogvative events"),
    ("wrong_owner", "Cogvative event owner mismatch"),
    ("orphan_line", "orphaned Cogvative lines"),
    ("missing_events", "Cogvative lines present without events"),
])
def test_backup_rejects_broken_cogvative_provenance_ownership(tmp_path, scenario, expected):
    source = tmp_path / "life.sqlite3"
    make_database(source)
    with sqlite3.connect(str(source)) as db:
        db.execute("INSERT INTO users VALUES ('u1','owner@example.test','hash',NULL,1,0)")
        db.execute("INSERT INTO users VALUES ('u2','other@example.test','hash',NULL,1,0)")
        db.execute("INSERT INTO projects VALUES ('p1','u1','Test','code',1)")
        if scenario != "missing_events":
            db.execute(
                "CREATE TABLE cog_events (id TEXT PRIMARY KEY, "
                "owner_id TEXT NOT NULL, project_id TEXT NOT NULL)"
            )
            db.execute(
                "INSERT INTO cog_events VALUES (?,?,?)",
                ("e1", "u2" if scenario == "wrong_owner" else "u1",
                 "absent" if scenario == "orphan_event" else "p1"),
            )
        db.execute(
            "CREATE TABLE cog_lines (event_id TEXT NOT NULL, line_no INTEGER NOT NULL)"
        )
        db.execute(
            "INSERT INTO cog_lines VALUES (?,1)",
            ("absent" if scenario == "orphan_line" else "e1",),
        )
    destination = tmp_path / "vault" / "cogvative-backup.sqlite3"
    if expected is None:
        assert backup.backup_and_verify(source, destination)["restore_drill"] == "passed"
    else:
        with pytest.raises(ValueError, match=expected):
            backup.backup_and_verify(source, destination)
        assert not destination.exists(), "Broken provenance must not publish a backup"


@pytest.mark.parametrize("scenario,expected", [
    ("valid", None),
    ("orphan_quote", "orphaned BNB quotes"),
    ("orphan_redemption", "orphaned BNB redemptions"),
    ("wrong_member", "BNB redemption member mismatch"),
    ("missing_quotes", "BNB redemptions present without quotes"),
])
def test_restored_bnb_redemption_ownership(tmp_path, scenario, expected):
    """Payment audit receipts must never be restored under the wrong account."""
    source = tmp_path / "life.sqlite3"
    make_database(source)
    with sqlite3.connect(str(source)) as db:
        db.execute("INSERT INTO users VALUES ('u1','one@example.test','hash',NULL,1,0)")
        db.execute("INSERT INTO users VALUES ('u2','two@example.test','hash',NULL,1,0)")
        if scenario != "missing_quotes":
            db.execute("CREATE TABLE bnb_priv_quotes (id TEXT PRIMARY KEY, user_id TEXT NOT NULL)")
            db.execute(
                "INSERT INTO bnb_priv_quotes VALUES ('q1',?)",
                ("missing" if scenario == "orphan_quote" else "u1",),
            )
        db.execute(
            "CREATE TABLE bnb_priv_redemptions "
            "(quote_id TEXT NOT NULL, user_id TEXT NOT NULL)"
        )
        db.execute(
            "INSERT INTO bnb_priv_redemptions VALUES (?,?)",
            ("missing" if scenario == "orphan_redemption" else "q1",
             "u2" if scenario == "wrong_member" else "u1"),
        )
    destination = tmp_path / "vault" / "bnb-audit-copy.sqlite3"
    if expected is None:
        assert backup.backup_and_verify(source, destination)["restore_drill"] == "passed"
    else:
        with pytest.raises(ValueError, match=expected):
            backup.backup_and_verify(source, destination)
        assert not destination.exists(), "Broken payment history must not publish a backup"


@pytest.mark.parametrize("scenario,expected", [
    ("valid", None),
    ("orphan_quote", "orphaned PRVI quotes"),
    ("orphan_redemption", "orphaned PRVI redemptions"),
    ("wrong_member", "PRVI redemption member mismatch"),
    ("missing_quotes", "PRVI redemptions present without quotes"),
    ("missing_quote_owner_column", "PRVI quote ownership columns missing"),
    ("missing_redemption_owner_column", "PRVI redemption ownership columns missing"),
])
def test_restored_native_prvi_redemption_ownership(tmp_path, scenario, expected):
    """Staging-disabled native payment history must restore to the right member."""
    source = tmp_path / "life.sqlite3"
    make_database(source)
    with sqlite3.connect(str(source)) as db:
        db.execute("INSERT INTO users VALUES ('u1','one@example.test','hash',NULL,1,0)")
        db.execute("INSERT INTO users VALUES ('u2','two@example.test','hash',NULL,1,0)")
        if scenario != "missing_quotes":
            quote_columns = (
                "id TEXT PRIMARY KEY, user_id TEXT NOT NULL"
                if scenario != "missing_quote_owner_column"
                else "id TEXT PRIMARY KEY"
            )
            db.execute("CREATE TABLE quotes (" + quote_columns + ")")
            if scenario != "missing_quote_owner_column":
                db.execute(
                    "INSERT INTO quotes VALUES ('q1',?)",
                    ("absent" if scenario == "orphan_quote" else "u1",),
                )
        redemption_columns = (
            "quote_id TEXT NOT NULL, user_id TEXT NOT NULL"
            if scenario != "missing_redemption_owner_column"
            else "quote_id TEXT NOT NULL"
        )
        db.execute("CREATE TABLE redemptions (" + redemption_columns + ")")
        if scenario not in ("missing_quote_owner_column", "missing_redemption_owner_column"):
            db.execute(
                "INSERT INTO redemptions VALUES (?,?)",
                ("absent" if scenario == "orphan_redemption" else "q1",
                 "u2" if scenario == "wrong_member" else "u1"),
            )
    destination = tmp_path / "vault" / "prvi-audit-copy.sqlite3"
    if expected is None:
        assert backup.backup_and_verify(source, destination)["restore_drill"] == "passed"
    else:
        with pytest.raises(ValueError, match=expected):
            backup.backup_and_verify(source, destination)
        assert not destination.exists(), "Broken native payment history must not publish a backup"


@pytest.mark.parametrize(
    "table,statement",
    [
        ("users", "INSERT INTO users VALUES (NULL,'null@example.test','hash',NULL,1,0)"),
        ("sessions", "INSERT INTO sessions VALUES (NULL,'u1',100)"),
        ("projects", "INSERT INTO projects VALUES (NULL,'u1','Untitled','code',100)"),
        ("files", "INSERT INTO files VALUES ('p1',NULL,'private',1)"),
        ("files", "INSERT INTO files VALUES (NULL,'notes.txt','private',1)"),
        ("ledger", "INSERT INTO ledger VALUES (NULL,'u1','charge','agent',1,'idem',100)"),
    ],
)
def test_backup_rejects_null_primary_key_data(tmp_path, table, statement):
    """SQLite TEXT PRIMARY KEY allows NULL in rowid tables; fail closed."""
    source = tmp_path / "null-identity.sqlite3"
    make_database(source)
    with sqlite3.connect(str(source)) as db:
        db.execute("INSERT INTO users VALUES ('u1','member@example.test','hash',NULL,1,0)")
        db.execute("INSERT INTO projects VALUES ('p1','u1','Project','code',1)")
        db.execute(statement)
    destination = tmp_path / "vault" / "snapshot.sqlite3"
    with pytest.raises(ValueError, match=rf"{table} primary key contains NULL"):
        backup.backup_and_verify(source, destination)
    assert not destination.exists(), "Do not publish backups with NULL identities"


@pytest.mark.parametrize("scenario,expected", [
    ("valid", None),
    ("null_key", "invalid login throttle state"),
    ("malformed_hash", "invalid login throttle state"),
    ("blob_hash", "invalid login throttle state"),
    ("negative_failures", "invalid login throttle state"),
    ("bad_lockout", "invalid login throttle state"),
    ("missing_pk", "login throttle primary key missing"),
    ("missing_column", "login throttle columns missing"),
    ("nullable_counter", "login throttle required fields nullable"),
])
def test_restore_rejects_invalid_persisted_login_throttle(tmp_path, scenario, expected):
    """An invalid restored throttle must not silently bypass account lockouts."""
    source = tmp_path / "life.sqlite3"
    make_database(source)
    with sqlite3.connect(str(source)) as db:
        key_column = "key_hash TEXT" if scenario == "missing_pk" else "key_hash TEXT PRIMARY KEY"
        failures_column = (
            "failures INTEGER" if scenario == "nullable_counter"
            else "failures INTEGER NOT NULL"
        )
        other_columns = (
            "window_started INTEGER NOT NULL"
            if scenario == "missing_column"
            else "window_started INTEGER NOT NULL, blocked_until INTEGER NOT NULL"
        )
        db.execute(
            f"CREATE TABLE login_throttle ({key_column}, {failures_column}, "
            f"{other_columns})"
        )
        if scenario not in {"missing_pk", "missing_column", "nullable_counter"}:
            db.execute(
                "INSERT INTO login_throttle VALUES (?,?,?,?)",
                (
                    None if scenario == "null_key" else (
                        b"a" * 64 if scenario == "blob_hash" else (
                            "not-a-sha256-hash" if scenario == "malformed_hash" else "a" * 64
                        )
                    ),
                    -1 if scenario == "negative_failures" else 5,
                    200,
                    100 if scenario == "bad_lockout" else 1100,
                ),
            )
    destination = tmp_path / "vault" / "throttle-snapshot.sqlite3"
    if expected is None:
        assert backup.backup_and_verify(source, destination)["restore_drill"] == "passed"
    else:
        with pytest.raises(ValueError, match=expected):
            backup.backup_and_verify(source, destination)
        assert not destination.exists(), "Invalid throttle state must not publish a backup"


@pytest.mark.parametrize("scenario,expected", [
    ("pending", None),
    ("fulfilled", None),
    ("orphan_member", "invalid Stripe checkout order"),
    ("wrong_amount", "invalid Stripe checkout order"),
    ("missing_primary_key", "Stripe checkout session primary key missing"),
    ("missing_column", "Stripe checkout columns missing"),
    ("nullable_member", "Stripe checkout required fields nullable"),
    ("fulfilled_without_ledger", "Stripe checkout ledger mismatch"),
    ("pending_with_ledger", "Stripe checkout ledger mismatch"),
    ("wrong_ledger_member", "Stripe checkout ledger mismatch"),
    ("wrong_ledger_amount", "Stripe checkout ledger mismatch"),
    ("wrong_ledger_service", "Stripe checkout ledger mismatch"),
    ("bad_fulfillment_time", "invalid Stripe checkout order"),
])
def test_restore_rejects_broken_stripe_checkout_audit_history(tmp_path, scenario, expected):
    """Checkout orders must preserve owner, fulfillment state and exact credit entry."""
    source = tmp_path / "life.sqlite3"
    make_database(source)
    with sqlite3.connect(str(source)) as db:
        db.execute("INSERT INTO users VALUES ('u1','one@example.test','hash',NULL,1,0)")
        db.execute("INSERT INTO users VALUES ('u2','two@example.test','hash',NULL,1,0)")
        columns = (
            "session_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, "
            "price_id TEXT NOT NULL, credits INTEGER NOT NULL, "
            "amount_cents INTEGER NOT NULL, created INTEGER NOT NULL, fulfilled_at INTEGER"
        )
        if scenario == "missing_primary_key":
            columns = columns.replace("session_id TEXT PRIMARY KEY", "session_id TEXT")
        if scenario == "missing_column":
            columns = columns.replace("price_id TEXT NOT NULL, ", "")
        if scenario == "nullable_member":
            columns = columns.replace("user_id TEXT NOT NULL", "user_id TEXT")
        db.execute("CREATE TABLE stripe_checkout_sessions (" + columns + ")")
        if scenario not in {"missing_primary_key", "missing_column", "nullable_member"}:
            completed = scenario in {
                "fulfilled", "fulfilled_without_ledger", "wrong_ledger_member",
                "wrong_ledger_amount", "wrong_ledger_service", "bad_fulfillment_time",
            }
            db.execute(
                "INSERT INTO stripe_checkout_sessions VALUES (?,?,?,?,?,?,?)",
                ("cs_test_123", "missing" if scenario == "orphan_member" else "u1",
                 "price_test", 100, 999 if scenario == "wrong_amount" else 1000,
                 100, 99 if scenario == "bad_fulfillment_time" else (101 if completed else None)),
            )
            with_ledger = scenario in {
                "fulfilled", "pending_with_ledger", "wrong_ledger_member",
                "wrong_ledger_amount", "wrong_ledger_service",
            }
            if with_ledger:
                db.execute(
                    "INSERT INTO ledger VALUES (?,?,?,?,?,?,?)",
                    ("led1", "u2" if scenario == "wrong_ledger_member" else "u1",
                     "credit", "wrong_service" if scenario == "wrong_ledger_service"
                     else "stripe_life_credits",
                     99 if scenario == "wrong_ledger_amount" else 100,
                     "stripe:cs_test_123", 101),
                )
    destination = tmp_path / "vault" / "stripe-audit-copy.sqlite3"
    if expected is None:
        assert backup.backup_and_verify(source, destination)["restore_drill"] == "passed"
    else:
        with pytest.raises(ValueError, match=expected):
            backup.backup_and_verify(source, destination)
        assert not destination.exists(), "Broken Stripe audit history must not publish a backup"

@pytest.mark.parametrize("balance,valid", [
    (0, True),
    (25, True),
    (-1, False),
    (None, False),
    ("not-a-number", False),
    (1.5, False),
])
def test_restore_rejects_malformed_member_credit_balances(tmp_path, balance, valid):
    """Synthetic member balances must be nonnegative SQLite integers."""
    source = tmp_path / "life.sqlite3"
    make_database(source)
    with sqlite3.connect(str(source)) as db:
        db.execute(
            "INSERT INTO users (id,email,pwdhash,wallet,member_since,credits) "
            "VALUES (?,?,?,?,?,?)",
            ("u1", "synthetic@example.invalid", "synthetic-hash", None, 1, balance),
        )
    destination = tmp_path / "vault" / "snapshot.sqlite3"
    if valid:
        assert backup.backup_and_verify(source, destination)["restore_drill"] == "passed"
    else:
        with pytest.raises(ValueError, match="invalid member credit balance"):
            backup.backup_and_verify(source, destination)
        assert not destination.exists(), "Unsafe balance must not publish a snapshot"


@pytest.mark.parametrize("scenario,expected", [
    ("unrelated_ledger", None),
    ("stripe_without_orders_table", "Stripe credit ledger without checkout orders"),
    ("stripe_without_order", "orphaned Stripe credit ledger entry"),
    ("stripe_service_with_wrong_key", "orphaned Stripe credit ledger entry"),
    ("stripe_prefix_with_wrong_service", "orphaned Stripe credit ledger entry"),
])
def test_restore_rejects_orphaned_stripe_credit_ledger(tmp_path, scenario, expected):
    """Both sides of the Checkout-to-credit audit trail must survive a restore."""
    source = tmp_path / "life.sqlite3"
    make_database(source)
    with sqlite3.connect(str(source)) as db:
        db.execute(
            "INSERT INTO users VALUES ('u1','synthetic@example.invalid','hash',NULL,1,0)"
        )
        if scenario not in ("stripe_without_orders_table", "unrelated_ledger"):
            db.execute(
                "CREATE TABLE stripe_checkout_sessions ("
                "session_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, "
                "price_id TEXT NOT NULL, credits INTEGER NOT NULL, "
                "amount_cents INTEGER NOT NULL, created INTEGER NOT NULL, "
                "fulfilled_at INTEGER)"
            )
        service = ("agent_run" if scenario in
                   ("unrelated_ledger", "stripe_prefix_with_wrong_service")
                   else "stripe_life_credits")
        key = ("unrelated:synthetic" if scenario in
               ("unrelated_ledger", "stripe_service_with_wrong_key")
               else "stripe:cs_missing")
        db.execute(
            "INSERT INTO ledger VALUES (?,?,?,?,?,?,?)",
            ("led1", "u1", "credit", service, 100, key, 1),
        )
    destination = tmp_path / "vault" / "stripe-ledger-copy.sqlite3"
    if expected is None:
        assert backup.backup_and_verify(source, destination)["restore_drill"] == "passed"
    else:
        with pytest.raises(ValueError, match=expected):
            backup.backup_and_verify(source, destination)
        assert not destination.exists(), "Unreconciled Stripe credits must not publish a backup"


@pytest.mark.parametrize("scenario,valid", [
    ("valid", True),
    ("short_hash", False),
    ("uppercase_hash", False),
    ("nonhex_hash", False),
    ("blob_hash", False),  # SQLite accepts BLOB values in TEXT PK columns.
    ("negative_expiry", False),
    ("text_expiry", False),
    ("null_expiry", False),
])
def test_restore_rejects_malformed_session_authentication_state(tmp_path, scenario, valid):
    """Only well-formed SHA-256 session identifiers and integer expiries restore."""
    source = tmp_path / "life.sqlite3"
    make_database(source)
    session_hash = "a" * 64
    expiry = 123456
    if scenario == "short_hash":
        session_hash = "a" * 63
    elif scenario == "uppercase_hash":
        session_hash = "A" * 64
    elif scenario == "nonhex_hash":
        session_hash = "g" * 64
    elif scenario == "blob_hash":
        session_hash = b"a" * 64
    elif scenario == "negative_expiry":
        expiry = -1
    elif scenario == "text_expiry":
        expiry = "not-a-time"
    elif scenario == "null_expiry":
        expiry = None
    with sqlite3.connect(str(source)) as db:
        db.execute("INSERT INTO users VALUES (?,?,?,?,?,?)",
                   ("u1", "synthetic@example.invalid", "hash", None, 1, 0))
        db.execute("INSERT INTO sessions VALUES (?,?,?)",
                   (session_hash, "u1", expiry))
    destination = tmp_path / "vault" / "snapshot.sqlite3"
    if valid:
        assert backup.backup_and_verify(source, destination)["restore_drill"] == "passed"
    else:
        with pytest.raises(ValueError, match="invalid session authentication state"):
            backup.backup_and_verify(source, destination)
        assert not destination.exists(), "Unsafe session state must not publish a snapshot"


@pytest.mark.parametrize("version,accepted", [
    (1, True),
    (3, True),
    (0, False),
    (-1, False),
    ("corrupt", False),
    (None, False),
])
def test_backup_rejects_invalid_private_file_versions(tmp_path, version, accepted):
    source = tmp_path / "life.sqlite3"
    make_database(source)
    with sqlite3.connect(str(source)) as db:
        db.execute(
            "INSERT INTO users VALUES ('u1','member@example.test','hash',NULL,1,0)"
        )
        db.execute(
            "INSERT INTO projects VALUES ('p1','u1','private','code',100)"
        )
        db.execute(
            "INSERT INTO files VALUES ('p1','notes.txt','private content',?)",
            (version,),
        )
    destination = tmp_path / "vault" / "snapshot.sqlite3"
    if accepted:
        assert backup.backup_and_verify(source, destination)["restore_drill"] == "passed"
    else:
        with pytest.raises(ValueError, match="invalid project file version"):
            backup.backup_and_verify(source, destination)
        assert not destination.exists(), "Invalid private files must not publish a backup"


@pytest.mark.parametrize("kind,amount,accepted", [
    ("credit", 2, True),
    ("charge", -2, True),
    ("charge", 0, True),  # store.charge permits zero-cost usage.
    ("credit", 0, False),
    ("credit", -2, False),
    ("charge", 2, False),
    ("refund", 2, False),
    (None, 2, False),
    ("credit", None, False),
    ("credit", "not-an-amount", False),
    ("charge", 1.5, False),
])
def test_restore_rejects_invalid_credit_ledger_amounts(tmp_path, kind, amount, accepted):
    """A restore must not publish a ledger with invalid credit or debit entries."""
    source = tmp_path / "life.sqlite3"
    make_database(source)
    with sqlite3.connect(str(source)) as db:
        db.execute(
            "INSERT INTO users VALUES ('u1','synthetic@example.invalid','hash',NULL,1,0)"
        )
        db.execute(
            "INSERT INTO ledger VALUES (?,?,?,?,?,?,?)",
            ("l1", "u1", kind, "agent_run", amount, "idem1", 100),
        )
    destination = tmp_path / "vault" / "snapshot.sqlite3"
    if accepted:
        assert backup.backup_and_verify(source, destination)["restore_drill"] == "passed"
    else:
        with pytest.raises(ValueError, match="invalid credit ledger amount or kind"):
            backup.backup_and_verify(source, destination)
        assert not destination.exists(), "Malformed credit history must not publish a backup"


@pytest.mark.parametrize("created,accepted", [
    (0, True),
    (1700000000, True),
    (-1, False),
    ("not-a-timestamp", False),
    (None, False),
    (1.5, False),
])
def test_restore_rejects_invalid_credit_ledger_timestamps(tmp_path, created, accepted):
    """Reject malformed financial audit times without publishing a snapshot."""
    source = tmp_path / "life.sqlite3"
    make_database(source)
    with sqlite3.connect(str(source)) as db:
        db.execute(
            "INSERT INTO users VALUES ('u1','synthetic@example.invalid','hash',NULL,1,0)"
        )
        db.execute(
            "INSERT INTO ledger VALUES (?,?,?,?,?,?,?)",
            ("l1", "u1", "charge", "agent_run", -1, "idem1", created),
        )
    destination = tmp_path / "vault" / "snapshot.sqlite3"
    if accepted:
        assert backup.backup_and_verify(source, destination)["restore_drill"] == "passed"
    else:
        with pytest.raises(ValueError, match="invalid credit ledger timestamp"):
            backup.backup_and_verify(source, destination)
        assert not destination.exists(), "Malformed audit history must not publish a backup"


@pytest.mark.parametrize("table", ["cog_wallets", "cog_claim_challenges"])
@pytest.mark.parametrize("scenario,accepted", [
    ("valid", True),
    ("orphan_user", False),
    ("orphan_project", False),
    ("cross_account_project", False),
    ("missing_user_column", False),
    ("missing_project_column", False),
])
def test_restore_rejects_cogvative_wallet_link_ownership(tmp_path, table, scenario, accepted):
    """Private wallet and claim records must belong to the project's owner."""
    source = tmp_path / "life.sqlite3"
    make_database(source)
    with sqlite3.connect(str(source)) as db:
        db.execute("INSERT INTO users VALUES ('u1','owner@example.invalid','hash',NULL,1,0)")
        db.execute("INSERT INTO users VALUES ('u2','other@example.invalid','hash',NULL,1,0)")
        db.execute("INSERT INTO projects VALUES ('p1','u1','Project','code',1)")
        columns = ["user_id TEXT", "project_id TEXT"]
        if scenario == "missing_user_column":
            columns.remove("user_id TEXT")
        if scenario == "missing_project_column":
            columns.remove("project_id TEXT")
        db.execute(f'CREATE TABLE "{table}" (' + ", ".join(columns) + ")")
        if scenario not in ("missing_user_column", "missing_project_column"):
            user_id = "missing" if scenario == "orphan_user" else (
                "u2" if scenario == "cross_account_project" else "u1"
            )
            project_id = "missing" if scenario == "orphan_project" else "p1"
            db.execute(f'INSERT INTO "{table}" VALUES (?,?)', (user_id, project_id))
    destination = tmp_path / "vault" / "snapshot.sqlite3"
    if accepted:
        assert backup.backup_and_verify(source, destination)["restore_drill"] == "passed"
    else:
        expected = ("ownership columns missing" if scenario.startswith("missing_")
                    else "ownership mismatch")
        with pytest.raises(ValueError, match=expected):
            backup.backup_and_verify(source, destination)
        assert not destination.exists(), "Do not publish cross-account wallet links"


@pytest.mark.parametrize("email", ["", "   ", b"binary@example.test"])
def test_backup_rejects_blank_or_binary_member_email(tmp_path, email):
    source = tmp_path / "bad-email.sqlite3"
    make_database(source)
    with sqlite3.connect(str(source)) as db:
        db.execute(
            "INSERT INTO users (id, email, pwdhash, wallet, member_since, credits) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("u1", email, "synthetic-hash", None, 1, 0),
        )
    destination = tmp_path / "vault" / "backup.sqlite3"
    with pytest.raises(ValueError, match="invalid member email identity"):
        backup.backup_and_verify(source, destination)
    assert not destination.exists()


def test_backup_accepts_nonempty_text_member_email(tmp_path):
    source = tmp_path / "good-email.sqlite3"
    make_database(source)
    with sqlite3.connect(str(source)) as db:
        db.execute(
            "INSERT INTO users (id, email, pwdhash, wallet, member_since, credits) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("u1", "member@example.test", "synthetic-hash", None, 1, 0),
        )
    destination = tmp_path / "vault" / "backup.sqlite3"
    assert backup.backup_and_verify(source, destination)["restore_drill"] == "passed"


@pytest.mark.parametrize("wallet,accepted", [
    (None, True),  # Members may not have linked a wallet yet.
    ("0xabc123", True),  # The restore verifier does not impose chain formats.
    ("", False),
    ("   ", False),
    (b"binary-wallet", False),
])
def test_backup_rejects_invalid_linked_wallet_identity(tmp_path, wallet, accepted):
    """Do not publish a restore containing blank or binary account wallet IDs."""
    source = tmp_path / "wallet-identity.sqlite3"
    make_database(source)
    with sqlite3.connect(str(source)) as db:
        db.execute(
            "INSERT INTO users (id,email,pwdhash,wallet,member_since,credits) "
            "VALUES (?,?,?,?,?,?)",
            ("u1", "synthetic@example.invalid", "synthetic-hash", wallet, 1, 0),
        )
    destination = tmp_path / "vault" / "snapshot.sqlite3"
    if accepted:
        assert backup.backup_and_verify(source, destination)["restore_drill"] == "passed"
    else:
        with pytest.raises(ValueError, match="invalid linked wallet identity"):
            backup.backup_and_verify(source, destination)
        assert not destination.exists(), "Invalid wallet identity must not publish a backup"


@pytest.mark.parametrize("created,accepted", [
    (0, True),
    (1700000000, True),
    (None, False),
    (-1, False),
    ("unknown", False),
    (1.5, False),
])
def test_restore_rejects_invalid_project_creation_timestamps(tmp_path, created, accepted):
    """Malformed project audit times must not be published as recoverable data."""
    source = tmp_path / "life.sqlite3"
    make_database(source)
    with sqlite3.connect(str(source)) as db:
        db.execute(
            "INSERT INTO users VALUES ('u1','synthetic@example.invalid','hash',NULL,1,0)"
        )
        db.execute(
            "INSERT INTO projects (id,owner_id,title,kind,created) VALUES (?,?,?,?,?)",
            ("p1", "u1", "Synthetic", "code", created),
        )
    destination = tmp_path / "vault" / "snapshot.sqlite3"
    if accepted:
        assert backup.backup_and_verify(source, destination)["restore_drill"] == "passed"
    else:
        with pytest.raises(ValueError, match="invalid project creation timestamp"):
            backup.backup_and_verify(source, destination)
        assert not destination.exists(), "Malformed project history must not publish a backup"

def test_restore_rejects_orphaned_credit_ledger(tmp_path):
    source = tmp_path / "life.sqlite3"
    make_database(source)
    with sqlite3.connect(str(source)) as db:
        db.execute(
            "INSERT INTO ledger (id,user_id,kind,service,amount,idempotency,created) "
            "VALUES (?,?,?,?,?,?,?)",
            ("l1", "missing-user", "debit", "synthetic", 1, "test-1", 1),
        )
    destination = tmp_path / "vault" / "backup.sqlite3"
    with pytest.raises(ValueError, match="orphaned ledger owner references"):
        backup.backup_and_verify(source, destination)
    assert not destination.exists(), "Orphaned customer charges must not publish a backup"

@pytest.mark.parametrize("path,content,valid", [
    ("notes.txt", "hello", True),
    ("unicode-🌌.txt", "", True),
    ("", "text", False),
    ("  \t\n ", "text", False),
    ("notes\x00.txt", "text", False),
    ("\x00notes.txt", "text", False),
    (b"binary-path", "text", False),
    ("notes.txt", b"binary-content", False),
    ("notes.txt", None, False),
])
def test_backup_rejects_malformed_private_project_file_text(tmp_path, path, content, valid):
    source = tmp_path / "life.sqlite3"
    make_database(source)
    with sqlite3.connect(str(source)) as db:
        db.execute(
            "INSERT INTO users VALUES ('u1','member@example.test','hash',NULL,1,0)"
        )
        db.execute("INSERT INTO projects VALUES ('p1','u1','Title','code',1)")
        db.execute(
            "INSERT INTO files (project_id,path,content,version) VALUES (?,?,?,1)",
            ("p1", path, content),
        )
    destination = tmp_path / "vault" / "snapshot.sqlite3"
    if valid:
        assert backup.backup_and_verify(source, destination)["restore_drill"] == "passed"
    else:
        with pytest.raises(ValueError, match="invalid private project file text"):
            backup.backup_and_verify(source, destination)
        assert not destination.exists(), "Malformed project data must not publish a backup"


@pytest.mark.parametrize("stored_path,valid", [
    ("src/main.py", True),
    ("tests/test_main.py", True),
    ("../private.txt", False),
    ("src/../../private.txt", False),
    ("/absolute.txt", False),
    (".env", False),
    ("src/.private", False),
    ("src\\escape.py", False),
    ("src/file name.py", True),
    ("unicode-🌌.txt", True),
    ("src//main.py", False),
    ("a/b/c/d/e/f/g/h/i.py", False),
    ("a" * 181, False),
])
def test_backup_requires_canonical_safe_private_file_paths(tmp_path, stored_path, valid):
    """Recovered project paths must obey the same constraints as new writes."""
    source = tmp_path / "life.sqlite3"
    make_database(source)
    with sqlite3.connect(str(source)) as db:
        db.execute(
            "INSERT INTO users VALUES ('u1','member@example.test','synthetic-hash',NULL,1,0)"
        )
        db.execute("INSERT INTO projects VALUES ('p1','u1','Test','code',1)")
        db.execute(
            "INSERT INTO files VALUES (?,?,?,1)",
            ("p1", stored_path, "synthetic private content"),
        )
    destination = tmp_path / "vault" / "safe-files.sqlite3"
    if valid:
        assert backup.backup_and_verify(source, destination)["restore_drill"] == "passed"
    else:
        with pytest.raises(ValueError, match="unsafe private project file path"):
            backup.backup_and_verify(source, destination)
        assert not destination.exists(), "Unsafe project paths must not publish a backup"

def test_backup_rejects_session_owned_by_missing_account(tmp_path):
    source = tmp_path / "life.sqlite3"
    make_database(source)
    with sqlite3.connect(source) as db:
        db.execute(
            "INSERT INTO sessions (token_hash,user_id,expires) VALUES (?,?,?)",
            ("a" * 64, "deleted-account", 123456),
        )
    dest = tmp_path / "vault" / "snapshot.sqlite3"
    with pytest.raises(ValueError, match="orphaned sessions owner references"):
        backup.backup_and_verify(source, dest)
    assert not dest.exists(), "Invalid authentication state must not publish a backup"



@pytest.mark.parametrize("service,valid", [
    ("ai-inference", True),
    ("collaboration-🌌", True),
    (None, False),
    ("", False),
    (" \t\n ", False),
    (b"binary-service", False),
])
def test_backup_rejects_invalid_credit_ledger_service_identity(tmp_path, service, valid):
    """A recovered idempotent charge must retain a usable service identifier."""
    source = tmp_path / "life.sqlite3"
    make_database(source)
    with sqlite3.connect(str(source)) as db:
        db.execute(
            "INSERT INTO users VALUES ('u1','member@example.test','synthetic-hash',NULL,1,5)"
        )
        db.execute(
            "INSERT INTO ledger (id,user_id,kind,service,amount,idempotency,created) "
            "VALUES (?,?,?,?,?,?,?)",
            ("l1", "u1", "credit", service, 5, "synthetic-credit-1", 1),
        )
    destination = tmp_path / "vault" / "snapshot.sqlite3"
    if valid:
        assert backup.backup_and_verify(source, destination)["restore_drill"] == "passed"
    else:
        with pytest.raises(ValueError, match="invalid credit ledger service identity"):
            backup.backup_and_verify(source, destination)
        assert not destination.exists(), "Malformed financial audit data must not publish a backup"
