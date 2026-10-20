import os
import sqlite3

import anyio
import pytest
from mcp import Client

from privi_ledger.config import Settings
from privi_ledger.server import build_server
from privi_ledger.store import Ledger

PAY_TO = "0x1990589FD200E043b8C6FD9ec5956c61b3071048"


class FakeFacilitator:
    def __init__(self):
        self.calls = []

    async def verify(self, payload, req):
        self.calls.append("verify")
        return {"isValid": True}

    async def settle(self, payload, req):
        self.calls.append("settle")
        return {"success": True, "transaction": "0x" + "ab" * 32, "network": req["network"]}


@pytest.fixture
def ledger(tmp_path):
    return Ledger(str(tmp_path / "l.db"))


def server(ledger, fac=None, **kw):
    return build_server(Settings(pay_to=PAY_TO, **kw), ledger, fac or FakeFacilitator())


def as_org(monkeypatch, key):
    """Over in-process (stdio-like) transport the org key comes from LEDGER_LOCAL_ORG_KEY."""
    if key is None:
        monkeypatch.delenv("LEDGER_LOCAL_ORG_KEY", raising=False)
    else:
        monkeypatch.setenv("LEDGER_LOCAL_ORG_KEY", key)


def test_record_read_and_receipt(ledger, monkeypatch):
    acme = ledger.create_org("Acme")
    as_org(monkeypatch, acme["api_key"])

    async def go():
        async with Client(server(ledger)) as c:
            r1 = await c.call_tool("ledger_record_action", {
                "stream_id": "billing-agent", "actor": "claude", "action_type": "payment",
                "summary": "Paid invoice 1042", "resource": "inv_1042", "details": {"usd": 120.5}})
            assert not r1.is_error, r1
            e1 = r1.structured_content["entry"]
            assert e1["seq"] == 1 and e1["details"] == {"usd": 120.5}
            await c.call_tool("ledger_record_action", {
                "stream_id": "billing-agent", "actor": "claude", "action_type": "message",
                "summary": "Emailed receipt", "outcome": "failure"})
            read = (await c.call_tool("ledger_read_stream", {"stream_id": "billing-agent"})).structured_content
            assert [e["seq"] for e in read["entries"]] == [1, 2] and read["integrity"]["intact"]
            assert read["entries"][1]["prev_hash"] == e1["entry_hash"]
            streams = (await c.call_tool("ledger_list_streams", {})).structured_content
            assert streams["streams"][0]["entries"] == 2
            rc = (await c.call_tool("ledger_check_receipt", {"entry_hash": e1["entry_hash"]})).structured_content
            assert rc["found"] and rc["seq"] == 1 and "summary" not in rc
    anyio.run(go)


def test_auth_and_org_isolation(ledger, monkeypatch):
    acme, other = ledger.create_org("Acme"), ledger.create_org("Other")
    ledger.record(acme["org_id"], "agent-a", "claude", "tool_call", "secret thing")

    async def call(name, args):
        async with Client(server(ledger)) as c:
            return await c.call_tool(name, args)

    as_org(monkeypatch, None)
    assert anyio.run(call, "ledger_list_streams", {}).is_error
    as_org(monkeypatch, "plk_wrong")
    assert anyio.run(call, "ledger_record_action", {
        "stream_id": "x", "actor": "y", "action_type": "other", "summary": "z"}).is_error
    as_org(monkeypatch, other["api_key"])
    r = anyio.run(call, "ledger_read_stream", {"stream_id": "agent-a"}).structured_content
    assert r["entries"] == []  # other org cannot see Acme's stream
    # keys are stored hashed
    raw = sqlite3.connect(ledger._db.execute("PRAGMA database_list").fetchone()[2])
    assert acme["api_key"] not in str(raw.execute("SELECT * FROM orgs").fetchall())


def test_paid_audit_and_tamper_detection(ledger, tmp_path):
    acme = ledger.create_org("Acme")
    for i in range(3):
        ledger.record(acme["org_id"], "ops-agent", "claude", "data_change", f"step {i}")
    fac = FakeFacilitator()

    async def go():
        async with Client(server(ledger, fac)) as c:
            args = {"org_id": acme["org_id"], "stream_id": "ops-agent"}
            need = await c.call_tool("ledger_audit_stream", args)
            assert need.is_error and need.structured_content["accepts"][0]["amount"] == "20000"
            pay = {"x402Version": 2, "resource": need.structured_content["resource"],
                   "accepted": need.structured_content["accepts"][0], "payload": {}}
            ok = await c.call_tool("ledger_audit_stream", args, meta={"x402/payment": pay})
            a = ok.structured_content
            assert a["intact"] and a["entry_count"] == 3 and "summary" not in str(a)
            assert ok.meta["x402/payment-response"]["success"] and fac.calls == ["verify", "settle"]

            db = sqlite3.connect(str(tmp_path / "l.db"))
            db.execute("UPDATE entries SET summary='edited' WHERE seq=2"); db.commit()
            bad = (await c.call_tool("ledger_audit_stream", args, meta={"x402/payment": pay})).structured_content
            assert bad["intact"] is False and bad["broken_at_seq"] == 2

            db.execute("DELETE FROM entries WHERE seq=2"); db.commit()
            gone = (await c.call_tool("ledger_audit_stream", args, meta={"x402/payment": pay})).structured_content
            assert gone["intact"] is False and gone["broken_at_seq"] == 3
    anyio.run(go)


def test_validation(ledger):
    org = ledger.create_org("Acme")["org_id"]
    for bad in [dict(action_type="hack"), dict(outcome="maybe"), dict(stream_id="has space"),
                dict(details={"x": "y" * 20000}), dict(summary="  ")]:
        args = dict(stream_id="s", actor="a", action_type="other", summary="ok") | bad
        with pytest.raises(ValueError):
            ledger.record(org, **args)


class FakeAnchor:
    def __init__(self):
        self.calls = []

    def anchor(self, hashes, label):
        self.calls.append(list(hashes))
        return {"status": "confirmed", "merkle_root": "ab" * 32, "tx_hash": "0x" + "cd" * 32,
                "block_number": 58200, "block_time": 1792466000,
                "receipts": [{"hash": h, "proof": [], "tx_hash": "0x" + "cd" * 32} for h in hashes]}


def test_onchain_checkpoint_catches_consistent_rewrite(ledger, tmp_path):
    from privi_ledger.anchoring import Checkpoints
    from privi_ledger.store import fingerprint, GENESIS

    org = ledger.create_org("Acme")["org_id"]
    for i in range(3):
        ledger.record(org, "ops", "claude", "data_change", f"step {i}")
    cps, fake = Checkpoints(ledger._db, ledger._lock), FakeAnchor()
    assert cps.run_once(ledger.heads(), fake, "privi-ledger") == 1
    assert cps.run_once(ledger.heads(), fake, "privi-ledger") == 0      # nothing new
    ledger.record(org, "ops", "claude", "data_change", "step 3")
    assert cps.run_once(ledger.heads(), fake, "privi-ledger") == 1      # new head only

    async def audit():
        async with Client(server(ledger, payments_enabled=False)) as c:
            return (await c.call_tool("ledger_audit_stream", {"org_id": org, "stream_id": "ops"})).structured_content

    a = anyio.run(audit)
    assert a["intact"] and a["onchain_checkpoint"]["anchored"] and a["onchain_checkpoint"]["matches_current_record"]
    assert a["onchain_checkpoint"]["seq"] == 4 and a["onchain_checkpoint"]["verify_with"]["tool"] == "anchor_verify"

    # Rewrite entry 2 AND recompute every later hash, so the local chain is internally consistent.
    db = sqlite3.connect(str(tmp_path / "l.db")); db.row_factory = sqlite3.Row
    rows = [dict(r) for r in db.execute("SELECT * FROM entries WHERE org_id=? ORDER BY seq", (org,))]
    prev = GENESIS
    for r in rows:
        if r["seq"] == 2:
            r["summary"] = "step 1 (quietly edited)"
        r["prev_hash"] = prev
        r["entry_hash"] = fingerprint(r)
        prev = r["entry_hash"]
        db.execute("UPDATE entries SET summary=?, prev_hash=?, entry_hash=? WHERE id=?",
                   (r["summary"], r["prev_hash"], r["entry_hash"], r["id"]))
    db.commit()
    assert ledger.check_chain(ledger.entries(org, "ops")).valid      # local check alone is fooled
    b = anyio.run(audit)
    assert b["intact"] is False and "anchored on the Privi chain" in b["reason"]
    assert b["onchain_checkpoint"]["matches_current_record"] is False


class FakeAnchorWithVerify(FakeAnchor):
    def verify(self, hash_hex, tx_hash, proof):
        return {"verified": any(hash_hex in c for c in self.calls), "block_number": 58200,
                "block_time_utc": "2026-10-20T03:50:00Z"}


def test_compliance_report_sealed_and_verifiable(ledger, monkeypatch):
    import copy
    acme = ledger.create_org("Acme")
    org = acme["org_id"]
    ledger.record(org, "billing-agent", "claude", "payment", "Paid invoice 7")
    ledger.record(org, "billing-agent", "claude", "message", "Emailed customer", outcome="failure")
    ledger.record(org, "support-agent", "claude", "data_access", "Read ticket 9")
    ledger.record(org, "support-agent", "dana", "approval", "Approved refund")
    as_org(monkeypatch, acme["api_key"])
    fake = FakeAnchorWithVerify()

    async def go():
        srv = build_server(Settings(pay_to=PAY_TO), ledger, FakeFacilitator(), anchor_client=fake)
        async with Client(srv) as c:
            r = (await c.call_tool("ledger_compliance_report", {})).structured_content
            rep, att = r["report"], r["attestation"]
            assert rep["totals"]["entries"] == 4 and rep["totals"]["failures"] == 1 and rep["totals"]["approvals"] == 1
            assert rep["status"] == "attention_required"          # billing-agent: sensitive actions, no approval; not anchored
            sev = {(f["stream_id"], f["severity"]) for f in rep["findings"]}
            assert ("billing-agent", "medium") in sev
            assert att["anchored"] and fake.calls == [[att["report_hash"]]]
            assert "# AI Agent Activity Report: Acme" in r["markdown"] and att["report_hash"] in r["markdown"]

            ok = (await c.call_tool("ledger_verify_report", {"report": rep})).structured_content
            assert ok["valid"] and ok["onchain_verified"] and ok["report_id"] == r["report_id"]

            edited = copy.deepcopy(rep)
            edited["totals"]["failures"] = 0                       # someone hides the failure
            bad = (await c.call_tool("ledger_verify_report", {"report": edited})).structured_content
            assert bad["valid"] is False and "edited" in bad["reason"]

            # period filter and stream filter
            only = (await c.call_tool("ledger_compliance_report", {"streams": ["support-agent"]})).structured_content
            assert [s["stream_id"] for s in only["report"]["streams"]] == ["support-agent"]
            future = (await c.call_tool("ledger_compliance_report", {"since": "2999-01-01T00:00:00Z"})).structured_content
            assert future["report"]["totals"]["entries"] == 0

        monkeypatch.setenv("LEDGER_LOCAL_ORG_KEY", "plk_wrong")
        async with Client(srv) as c:
            assert (await c.call_tool("ledger_compliance_report", {})).is_error
    anyio.run(go)
