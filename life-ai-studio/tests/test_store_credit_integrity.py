"""Synthetic credit-accounting tests; no payment provider or real funds."""

import pytest

import store


def test_credit_unknown_member_does_not_create_orphan_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB", str(tmp_path / "life.sqlite3"))
    store.init()

    with pytest.raises(ValueError, match="Unknown LIFE member"):
        store.credit("missing-member", 100, "synthetic-test", "missing-member-idem")

    with store.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM ledger").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0


def test_credit_existing_member_remains_atomic_and_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB", str(tmp_path / "life.sqlite3"))
    store.init()
    with store.transaction() as db:
        db.execute(
            "INSERT INTO users (id,email,pwdhash,member_since) VALUES (?,?,?,?)",
            ("synthetic-member", "synthetic@example.invalid", "not-a-real-hash", 1),
        )

    store.credit("synthetic-member", 100, "synthetic-test", "same-idem")
    store.credit("synthetic-member", 100, "synthetic-test", "same-idem")
    with store.transaction() as db:
        assert db.execute("SELECT credits FROM users WHERE id=?",
                          ("synthetic-member",)).fetchone()[0] == 100
        assert db.execute("SELECT COUNT(*) FROM ledger WHERE user_id=?",
                          ("synthetic-member",)).fetchone()[0] == 1


@pytest.mark.parametrize(
    ("amount", "key"),
    [
        (100, None),       # Reject before SQLite's NOT NULL constraint.
        (100, ""),
        (100, "   "),
        (100, "x" * 181),
        (True, "boolean-quantity"),  # bool must not be treated as 1 credit.
        (1.5, "fractional-quantity"),
    ],
)
def test_invalid_credit_request_never_changes_balance_or_ledger(
    tmp_path, monkeypatch, amount, key
):
    monkeypatch.setattr(store, "DB", str(tmp_path / "life.sqlite3"))
    store.init()
    with store.transaction() as db:
        db.execute(
            "INSERT INTO users (id,email,pwdhash,member_since) VALUES (?,?,?,?)",
            ("synthetic-member", "synthetic@example.invalid", "not-a-real-hash", 1),
        )

    with pytest.raises(ValueError, match="Invalid credit"):
        store.credit("synthetic-member", amount, "synthetic-test", key)

    with store.transaction() as db:
        assert db.execute(
            "SELECT credits FROM users WHERE id=?", ("synthetic-member",)
        ).fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM ledger").fetchone()[0] == 0


@pytest.mark.parametrize(
    ("amount", "key"),
    [
        (True, "boolean-debit"),
        (1.5, "fractional-debit"),
        (-1, "negative-debit"),
        (1, None),
        (1, ""),
        (1, "   "),
        (1, "x" * 181),
        (1, 123),
    ],
)
def test_invalid_charge_request_never_changes_balance_or_ledger(
    tmp_path, monkeypatch, amount, key
):
    monkeypatch.setattr(store, "DB", str(tmp_path / "life.sqlite3"))
    store.init()
    with store.transaction() as db:
        db.execute(
            "INSERT INTO users (id,email,pwdhash,wallet,member_since,credits) "
            "VALUES (?,?,?,?,?,?)",
            ("synthetic-member", "synthetic@example.invalid",
             "not-a-real-hash", "0x" + "a" * 40, 1, 10),
        )

    with pytest.raises(ValueError, match="Invalid charge"):
        store.charge("synthetic-member", "synthetic-test", amount, key)

    with store.transaction() as db:
        assert db.execute(
            "SELECT credits FROM users WHERE id=?", ("synthetic-member",)
        ).fetchone()[0] == 10
        assert db.execute("SELECT COUNT(*) FROM ledger").fetchone()[0] == 0


def test_new_database_is_private_under_permissive_umask(tmp_path, monkeypatch):
    """New LIFE member data must not be readable by other OS users."""
    import os

    path = tmp_path / "vault" / "life.sqlite3"
    monkeypatch.setattr(store, "DB", str(path))
    previous_umask = os.umask(0o000)
    try:
        store.init()
    finally:
        os.umask(previous_umask)

    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700


def test_initialization_does_not_repermission_existing_database(tmp_path, monkeypatch):
    """Changing permissions on existing volumes requires an operator review."""
    import os

    path = tmp_path / "existing.sqlite3"
    path.touch(mode=0o644)
    os.chmod(path, 0o644)
    monkeypatch.setattr(store, "DB", str(path))
    store.init()
    assert path.stat().st_mode & 0o777 == 0o644


def test_initialization_rejects_symlinked_database_without_touching_target(
    tmp_path, monkeypatch
):
    """A symlink must not redirect LIFE account initialization into another file."""
    target = tmp_path / "unrelated-private-file"
    target.write_bytes(b"must-remain-unchanged")
    alias = tmp_path / "life.sqlite3"
    alias.symlink_to(target)
    monkeypatch.setattr(store, "DB", str(alias))

    with pytest.raises(ValueError, match="existing regular file"):
        store.init()

    assert alias.is_symlink()
    assert target.read_bytes() == b"must-remain-unchanged"


def test_initialization_rejects_directory_as_database(tmp_path, monkeypatch):
    """A non-regular existing path must fail before attempting SQL operations."""
    directory = tmp_path / "life.sqlite3"
    directory.mkdir()
    monkeypatch.setattr(store, "DB", str(directory))

    with pytest.raises(ValueError, match="existing regular file"):
        store.init()

    assert directory.is_dir()


def test_transaction_never_recreates_missing_member_database(tmp_path, monkeypatch):
    """A lost or unmounted volume must fail, not silently reset customer state."""
    import sqlite3

    path = tmp_path / "lost-volume" / "life.sqlite3"
    monkeypatch.setattr(store, "DB", str(path))

    with pytest.raises(sqlite3.OperationalError):
        with store.transaction() as db:
            db.execute("CREATE TABLE should_not_exist (id INTEGER)")
    assert not path.exists()
    assert not path.parent.exists()

    # Also fail closed when a previously initialized database disappears.
    store.init()
    path.unlink()
    with pytest.raises(sqlite3.OperationalError):
        with store.transaction() as db:
            db.execute("SELECT 1")
    assert not path.exists(), "A request must not recreate a lost LIFE database"


def test_durable_startup_requires_preexisting_initialized_database(tmp_path, monkeypatch):
    """Missing/empty storage must not become a fresh customer database."""
    path = tmp_path / "durable-volume" / "life.sqlite3"
    monkeypatch.setattr(store, "DB", str(path))
    monkeypatch.setenv("LIFE_REQUIRE_EXISTING_DB", "1")

    with pytest.raises(RuntimeError, match="existing initialized database"):
        store.init()
    assert not path.exists()
    assert not path.parent.exists(), "Guarded startup must not create a fake volume"

    path.parent.mkdir()
    path.touch()
    with pytest.raises(RuntimeError, match="existing initialized database"):
        store.init()
    assert path.stat().st_size == 0, "Guarded startup must not initialize an empty file"

    path.unlink()
    monkeypatch.setenv("LIFE_REQUIRE_EXISTING_DB", "0")
    store.init()  # Explicit staging bootstrap, not a production restore.
    with store.transaction() as db:
        db.execute(
            "INSERT INTO users (id,email,pwdhash,member_since) VALUES (?,?,?,?)",
            ("existing-member", "existing@example.invalid", "synthetic-hash", 1),
        )

    monkeypatch.setenv("LIFE_REQUIRE_EXISTING_DB", "1")
    store.init()
    with store.transaction() as db:
        assert db.execute(
            "SELECT COUNT(*) FROM users WHERE id='existing-member'"
        ).fetchone()[0] == 1

    path.unlink()
    with pytest.raises(RuntimeError, match="existing initialized database"):
        store.init()
    assert not path.exists(), "Guarded restart must not recreate a lost database"


@pytest.mark.parametrize("scenario", ["users_only", "missing_ledger_idempotency"])
def test_durable_startup_and_readiness_reject_incomplete_core_schema(
    tmp_path, monkeypatch, scenario
):
    """A lookalike/partial SQLite restore must not report healthy or self-heal."""
    import sqlite3

    path = tmp_path / "partial-life.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE users (id TEXT, email TEXT, pwdhash TEXT, "
            "member_since INTEGER, credits INTEGER)"
        )
        if scenario == "missing_ledger_idempotency":
            db.executescript(
                "CREATE TABLE sessions (token_hash TEXT, user_id TEXT, expires INTEGER);"
                "CREATE TABLE projects (id TEXT, owner_id TEXT, title TEXT);"
                "CREATE TABLE files (project_id TEXT, path TEXT, content TEXT, version INTEGER);"
                "CREATE TABLE ledger (id TEXT, user_id TEXT, amount INTEGER);"
            )
        before = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}

    monkeypatch.setattr(store, "DB", str(path))
    monkeypatch.setenv("LIFE_REQUIRE_EXISTING_DB", "1")
    assert store.database_readable() is False
    with pytest.raises(RuntimeError, match="existing initialized database"):
        store.init()

    with sqlite3.connect(path) as db:
        after = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
    assert after == before, "Guarded startup must not mutate a partial restore"


@pytest.mark.parametrize(
    ("table", "replacement"),
    [
        (
            "users",
            "CREATE TABLE users (id TEXT, email TEXT UNIQUE NOT NULL, "
            "pwdhash TEXT NOT NULL, wallet TEXT UNIQUE, "
            "member_since INTEGER NOT NULL, credits INTEGER NOT NULL DEFAULT 0)",
        ),
        (
            "files",
            "CREATE TABLE files (project_id TEXT NOT NULL, path TEXT NOT NULL, "
            "content TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1)",
        ),
    ],
)
def test_durable_startup_rejects_core_tables_without_identity_primary_keys(
    tmp_path, monkeypatch, table, replacement
):
    """A schema lookalike must not make a broken recovery appear healthy."""
    import sqlite3

    path = tmp_path / "identity-unsafe.sqlite3"
    monkeypatch.setattr(store, "DB", str(path))
    store.init()
    with sqlite3.connect(path) as db:
        db.execute(f'DROP TABLE "{table}"')
        db.execute(replacement)
        before = db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()[0]

    monkeypatch.setenv("LIFE_REQUIRE_EXISTING_DB", "1")
    assert store.database_readable() is False
    with pytest.raises(RuntimeError, match="existing initialized database"):
        store.init()

    with sqlite3.connect(path) as db:
        after = db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()[0]
    assert after == before, "Guarded startup must not repair a broken restore"
