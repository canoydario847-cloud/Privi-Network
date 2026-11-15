"""Master Ledger acknowledgments and outbox disk-reclamation regression tests."""
import os

import privi_verify.ledger_report as lr


def _ack(evs):
    return {"accepted": len(evs), "receipts": [
        {"id": ev["id"], "entry_hash": "ab" * 32} for ev in evs]}


def test_aggregate_ack_is_not_enough_to_delete_unverified_events(tmp_path):
    path = str(tmp_path / "outbox.db")
    r = lr.LedgerReporter("privi-verify", "https://ledger.example", "key",
                          outbox_path=path, post=lambda u, k, body: {"accepted": len(body["events"])})
    r.report("tool_call", "one")
    r.report("tool_call", "two")
    assert r.flush() == 0 and r.pending() == 2
    assert "receipts" in r.last_error
    assert r.status()["acknowledged"] == 0


def test_partial_receipts_only_clean_the_proven_rows(tmp_path):
    first = [True]

    def post(u, k, body):
        evs = body["events"]
        if first[0]:
            first[0] = False
            return _ack(evs[:1])
        return _ack(evs)

    r = lr.LedgerReporter("privi-call", "https://ledger.example", "key",
                          outbox_path=str(tmp_path / "outbox.db"), post=post)
    r.report("tool_call", "first")
    r.report("tool_call", "second")
    assert r.flush() == 1 and r.pending() == 1
    assert "1/2" in r.last_error
    assert r.flush() == 1 and r.pending() == 0


def test_invalid_receipt_hash_and_outbox_overflow_do_not_erase_oldest(monkeypatch, tmp_path):
    monkeypatch.setattr(lr, "MAX_OUTBOX", 2)
    r = lr.LedgerReporter("privi-wallet", "https://ledger.example", "key",
                          outbox_path=str(tmp_path / "outbox.db"),
                          post=lambda u, k, b: {"receipts": [
                              {"id": v["id"], "entry_hash": "bad"} for v in b["events"]]})
    for name in ("original", "second", "overflow"):
        r.report("tool_call", name)
    assert r.pending() == 2 and r.overflow == 1
    names = [__import__("json").loads(row[0])["name"]
             for row in r._db.execute("SELECT event FROM outbox ORDER BY n").fetchall()]
    assert names == ["original", "second"]
    assert r.flush() == 0 and r.pending() == 2


def test_vacuum_only_after_all_rows_are_confirmed(monkeypatch, tmp_path):
    monkeypatch.setattr(lr, "MAX_PER_MIN", 1000)
    db_path = tmp_path / "outbox.db"
    r = lr.LedgerReporter("privi-anchor", "https://ledger.example", "key",
                          outbox_path=str(db_path), post=lambda u, k, b: _ack(b["events"]))
    for i in range(260):
        r.report("tool_call", f"tool_{i}", meta={"padding": "x" * 900})
    assert r.pending() == 260
    assert not r.compact_if_idle(min_bytes=0)
    before = os.path.getsize(db_path)
    assert r.flush() == 260 and r.pending() == 0
    assert r.compact_if_idle(min_bytes=0)
    after = os.path.getsize(db_path)
    assert after < before and r.status()["acknowledged"] == 260
