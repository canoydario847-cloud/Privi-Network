# Copyright (c) 2026 Privi World Corp. All rights reserved.
"""Deep Think ledger regression tests. No production wallets or network required."""
import sqlite3

import pytest

from privi_call.deep_think import DeepThinkLedger, DeepThinkError

A, B, C = "a" * 64, "b" * 64, "c" * 64
TX1, TX2 = "0x" + "1" * 64, "0x" + "2" * 64
ALL = {x: True for x in ("syntax", "tests", "edge_cases", "security", "integration")}


@pytest.fixture
def task(tmp_path):
    db = DeepThinkLedger(str(tmp_path / "think.sqlite"))
    first = db.start("Implement robust payment handling.", "Python", ["No charge on error"])
    return db, first["task_id"], first["task_token"]


def test_first_submission_and_same_hash_free(task):
    db, tid, secret = task
    r = db.review(tid, secret, A, ALL)
    assert r["revision"] == 0 and r["all_checks_reported_passed"]
    assert db.review(tid, secret, A, ALL)["revision"] == 0
    assert db.inspect_redo(tid, secret, A, A)["charged"] is False


def test_changed_snapshot_requires_payment(task):
    db, tid, secret = task
    db.review(tid, secret, A, ALL)
    assert db.review(tid, secret, B, ALL)["status"] == "redo_requires_payment"
    assert db.inspect_redo(tid, secret, A, B)["fee_usdc"] == "0.01"
    assert db.review(tid, secret, C, ALL)["status"] == "redo_requires_payment"


def test_paid_revision_unique_settlement_and_stale_update(task):
    db, tid, secret = task
    db.review(tid, secret, A, ALL)
    assert db.record_paid_redo(tid, secret, A, B, TX1)["revision"] == 1
    assert db.inspect_redo(tid, secret, A, B)["charged"] is False
    with pytest.raises(DeepThinkError):
        db.record_paid_redo(tid, secret, A, C, TX2)
    with pytest.raises(DeepThinkError):
        db.record_paid_redo(tid, secret, B, C, TX1)
    assert db.record_paid_redo(tid, secret, B, C, TX2)["revision"] == 2


def test_invalid_secret_input_and_check_results_fail_closed(task):
    db, tid, secret = task
    db.review(tid, secret, A, ALL)
    with pytest.raises(DeepThinkError):
        db.review(tid, "wrong", A, ALL)
    with pytest.raises(DeepThinkError):
        db.review(tid, secret, "0x" + A, ALL)
    with pytest.raises(DeepThinkError):
        db.review(tid, secret, A, {**ALL, "tests": "yes"})
    with pytest.raises(DeepThinkError):
        db.record_paid_redo(tid, secret, A, B, "no-transaction")


def test_storage_is_hash_only_and_persistent(task):
    db, tid, secret = task
    db.review(tid, secret, A, ALL)
    dump = "\n".join(db._db.iterdump())
    assert "Implement robust payment handling." not in dump
    assert secret not in dump
    path = db._db.execute("PRAGMA database_list").fetchone()[2]
    db2 = DeepThinkLedger(path)
    assert db2.review(tid, secret, A, ALL)["revision"] == 0
