"""Synthetic guarded-startup tests; never use real LIFE member data."""
import importlib.util
import os
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "life_store_privacy", Path(__file__).resolve().parents[1] / "store.py"
)
store = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(store)


@pytest.mark.parametrize("file_mode,dir_mode,allowed", [
    (0o600, 0o700, True),
    (0o640, 0o700, False),
    (0o644, 0o700, False),
    (0o600, 0o750, False),
    (0o600, 0o755, False),
])
def test_private_existing_database_permissions(tmp_path, file_mode, dir_mode, allowed):
    vault = tmp_path / "vault"
    vault.mkdir(mode=0o700)
    db = vault / "synthetic.sqlite3"
    db.write_bytes(b"synthetic fixture, not customer data")
    os.chmod(db, file_mode)
    os.chmod(vault, dir_mode)
    assert store.private_existing_database(db) is allowed


def test_private_existing_database_rejects_symlinked_paths(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir(mode=0o700)
    db = vault / "synthetic.sqlite3"
    db.write_bytes(b"synthetic fixture")
    os.chmod(db, 0o600)
    assert store.private_existing_database(db)
    assert not store.private_existing_database(vault / "missing.sqlite3")
    direct_alias = vault / "alias.sqlite3"
    direct_alias.symlink_to(db)
    assert not store.private_existing_database(direct_alias)
    parent_alias = tmp_path / "vault-alias"
    parent_alias.symlink_to(vault, target_is_directory=True)
    assert not store.private_existing_database(parent_alias / db.name)


def test_guarded_startup_rejects_exposed_db_without_bootstrapping(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir(mode=0o700)
    db = vault / "synthetic.sqlite3"
    db.write_bytes(b"synthetic fixture")
    os.chmod(db, 0o644)
    monkeypatch.setattr(store, "DB", str(db))
    monkeypatch.setenv("LIFE_REQUIRE_EXISTING_DB", "1")
    # Even if schema validation succeeds, insecure file access must block startup.
    monkeypatch.setattr(store, "database_readable", lambda: True)
    with pytest.raises(RuntimeError, match="owner-only permissions"):
        store.init()
    assert db.read_bytes() == b"synthetic fixture"


def test_guarded_startup_accepts_private_initialized_db(tmp_path, monkeypatch):
    db = tmp_path / "vault" / "life.sqlite3"
    monkeypatch.setattr(store, "DB", str(db))
    monkeypatch.delenv("LIFE_REQUIRE_EXISTING_DB", raising=False)
    store.init()  # Disposable synthetic bootstrap only.
    assert store.private_existing_database(db)
    monkeypatch.setenv("LIFE_REQUIRE_EXISTING_DB", "1")
    store.init()  # Existing private database passes the guard without recreation.
    assert db.exists()


def test_private_existing_database_rejects_hardlinked_file(tmp_path):
    """A second pathname must not bypass the guarded database's private vault."""
    vault = tmp_path / "vault"
    vault.mkdir(mode=0o700)
    db = vault / "synthetic.sqlite3"
    db.write_bytes(b"synthetic fixture, no customer data")
    os.chmod(db, 0o600)
    assert store.private_existing_database(db)

    # An accessible second pathname refers to the same inode even though the
    # original database path and vault retain owner-only permissions.
    public = tmp_path / "public"
    public.mkdir(mode=0o755)
    alias = public / "hardlink.sqlite3"
    os.link(db, alias)
    assert not store.private_existing_database(db)
    assert not store.private_existing_database(alias)

    alias.unlink()
    assert store.private_existing_database(db)
