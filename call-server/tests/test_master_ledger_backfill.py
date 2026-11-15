# Copyright (c) 2026 Privi World Corp. All rights reserved.
"""Historical Privi Call master-ledger import: integrity, privacy, and idempotency."""
import json
import sqlite3

import pytest

from privi_call.master_ledger_backfill import (
    BackfillError, import_records, legacy_event, open_read_only, verify_original_chain)
from privi_call.store import Store


@pytest.fixture
def call_db(tmp_path):
    path = str(tmp_path / "call.db")
    store = Store(path)
    for i in range(3):
        store.log(channel="agent", caller="SECRET-BUYER-123", callee="sensitive-agent",
                  tool="company_secret", status="ok" if i < 2 else "failed",
                  args={"access_token": "SUPER-SECRET"}, result={"private": "abc"},
                  detail={"email": "secret@example.org", "phone": "+15559991111"})
    return path


def fake_response(body):
    return {"accepted": len(body["events"]), "rejected": [], "receipts": [
        {"id": e["id"], "entry_hash": "ab" * 32} for e in body["events"]]}


def test_dry_run_never_contacts_master_or_changes_local_state(call_db):
    conn = open_read_only(call_db)
    try:
        def forbidden(*args):
            raise AssertionError("dry run must never call master")
        check = import_records(conn, "https://ledger.example", "", post=forbidden)
        assert check["mode"] == "dry-run" and check["records"] == 3
        assert check["submitted"] == 0 and not check["source_deleted"]
    finally:
        conn.close()
    assert sqlite3.connect(call_db).execute("SELECT COUNT(*) FROM calls").fetchone()[0] == 3


def test_authorized_hash_only_backfill_has_stable_dedup_ids(call_db):
    requests = []
    def post(url, key, body):
        assert url == "https://ledger.example" and key == "verified-report-key"
        requests.append(body)
        return fake_response(body)
    for _ in range(2):
        with open_read_only(call_db) as conn:
            res = import_records(conn, "https://ledger.example", "verified-report-key",
                                 commit=True, batch_size=2, post=post)
            assert res["submitted"] == 3 and res["batches"] == 2
    first, replay = (requests[0]["events"] + requests[1]["events"],
                     requests[2]["events"] + requests[3]["events"])
    assert [x["id"] for x in first] == [x["id"] for x in replay]
    assert len({x["id"] for x in first}) == 3
    exported = json.dumps(requests)
    for sensitive in ("SECRET-BUYER-123", "SUPER-SECRET", "secret@example.org", "+15559991111",
                      "sensitive-agent", "company_secret"):
        assert sensitive not in exported
    assert all(x["meta"]["legacy_hash"] == x["hash"] for x in first)
    assert first[-1]["outcome"] == "failure"
    assert sqlite3.connect(call_db).execute("SELECT COUNT(*) FROM calls").fetchone()[0] == 3


def test_missing_or_invalid_master_receipts_abort_without_deleting_source(call_db):
    responses = [
        lambda b: {"accepted": 3},  # HTTP success alone is not durable acknowledgement
        lambda b: {"accepted": 3, "rejected": [{"id": b["events"][0]["id"]}], "receipts": []},
        lambda b: {"receipts": [{"id": e["id"], "entry_hash": "bad"} for e in b["events"]]},
        lambda b: {"receipts": [{"id": b["events"][0]["id"], "entry_hash": "ab" * 32}] * 3},
    ]
    for reply in responses:
        with open_read_only(call_db) as conn:
            with pytest.raises(BackfillError):
                import_records(conn, "https://ledger.example", "verified-report-key",
                               commit=True, post=lambda u, k, b: reply(b))
    assert sqlite3.connect(call_db).execute("SELECT COUNT(*) FROM calls").fetchone()[0] == 3


def test_tampered_history_fails_before_any_network_submission(call_db):
    c = sqlite3.connect(call_db)
    c.execute("UPDATE calls SET price_usd='9999' WHERE seq=2")
    c.commit()
    c.close()
    with open_read_only(call_db) as conn:
        with pytest.raises(BackfillError):
            verify_original_chain(conn)
        with pytest.raises(BackfillError):
            import_records(conn, "https://ledger.example", "verified-report-key", commit=True,
                           post=lambda *a: pytest.fail("never send a corrupt source"))


def test_validation_rejects_invalid_parameters_and_can_limit_batch(call_db):
    with open_read_only(call_db) as conn:
        with pytest.raises(BackfillError):
            import_records(conn, "https://ledger.example", "x", commit=True)
        with pytest.raises(BackfillError):
            import_records(conn, "https://ledger.example", "verified-report-key", batch_size=201)
        payloads = []
        res = import_records(conn, "https://ledger.example", "verified-report-key",
                             commit=True, batch_size=2, limit=2,
                             post=lambda u, k, b: (payloads.append(b), fake_response(b))[1])
        assert res["submitted"] == 2 and len(payloads) == 1
