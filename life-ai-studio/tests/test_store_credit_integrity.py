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
