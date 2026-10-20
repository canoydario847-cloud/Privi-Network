import os
import sqlite3

import anyio
import pytest
from mcp import Client

from privi_verify.config import Settings
from privi_verify.server import build_server
from privi_verify.store import LotStore

PAY_TO = "0x1990589FD200E043b8C6FD9ec5956c61b3071048"


class FakeFacilitator:
    def __init__(self, valid=True, settle_ok=True):
        self.valid, self.settle_ok = valid, settle_ok
        self.calls = []

    async def verify(self, payload, req):
        self.calls.append(("verify", req["amount"]))
        return {"isValid": True, "payer": "0xabc"} if self.valid else {"isValid": False, "invalidReason": "insufficient_funds"}

    async def settle(self, payload, req):
        self.calls.append(("settle", req["amount"]))
        if self.settle_ok:
            return {"success": True, "transaction": "0x" + "ab" * 32, "network": req["network"], "payer": "0xabc"}
        return {"success": False, "errorReason": "insufficient_funds", "transaction": "", "network": req["network"]}


@pytest.fixture
def store(tmp_path):
    s = LotStore(str(tmp_path / "t.db"))
    s.record_event("LOT-1", "received", "Port Huron, MI", "Acme Steel", product="Steel coil", quantity="2 t")
    s.record_event("LOT-1", "produced", "Port Huron, MI", "Blue Water Fab", product="Bracket A-12", quantity="800 pcs")
    s.record_event("LOT-1", "shipped", "Port Huron, MI", "Blue Water Fab", notes="to Detroit OEM")
    return s


def settings(**kw):
    return Settings(pay_to=PAY_TO, **kw)


def payment_for(required: dict) -> dict:
    """What a client sends back after signing (signature contents are the facilitator's job)."""
    return {
        "x402Version": 2,
        "resource": required["resource"],
        "accepted": required["accepts"][0],
        "payload": {"signature": "0xsig", "authorization": {"from": "0xabc", "to": PAY_TO}},
    }


def run(coro):
    return anyio.run(coro)


def test_free_tools(store):
    async def go():
        async with Client(build_server(settings(), store, FakeFacilitator())) as c:
            names = {t.name for t in (await c.list_tools()).tools}
            assert names == {"privi_pricing", "privi_lookup_fingerprint", "privi_verify_lot",
                             "privi_chain_of_custody", "privi_record_event"}
            price = await c.call_tool("privi_pricing", {})
            assert price.structured_content["network"] == "eip155:84532"
            head = store.events("LOT-1")[-1]["record_hash"]
            hit = await c.call_tool("privi_lookup_fingerprint", {"fingerprint": head})
            assert hit.structured_content["found"] and hit.structured_content["seq"] == 3
    run(go)


def test_payment_required_then_paid(store):
    fac = FakeFacilitator()

    async def go():
        async with Client(build_server(settings(), store, fac)) as c:
            r = await c.call_tool("privi_verify_lot", {"lot_code": "LOT-1"})
            assert r.is_error
            req = r.structured_content
            assert req["x402Version"] == 2 and req["accepts"][0]["amount"] == "10000"
            assert req["accepts"][0]["payTo"] == PAY_TO
            assert fac.calls == []

            r2 = await c.call_tool("privi_verify_lot", {"lot_code": "LOT-1"},
                                   meta={"x402/payment": payment_for(req)})
            assert not r2.is_error, r2
            assert r2.structured_content["integrity"]["valid"] is True
            assert r2.structured_content["product"] == "Bracket A-12"
            assert r2.meta["x402/payment-response"]["success"] is True
            assert fac.calls == [("verify", "10000"), ("settle", "10000")]
    run(go)


def test_wrong_amount_rejected_before_facilitator(store):
    fac = FakeFacilitator()

    async def go():
        async with Client(build_server(settings(), store, fac)) as c:
            req = (await c.call_tool("privi_verify_lot", {"lot_code": "LOT-1"})).structured_content
            pay = payment_for(req)
            pay["accepted"] = {**pay["accepted"], "amount": "1"}
            r = await c.call_tool("privi_chain_of_custody", {"lot_code": "LOT-1"}, meta={"x402/payment": pay})
            assert r.is_error and "amount" in r.structured_content["error"]
            assert fac.calls == []
    run(go)


def test_invalid_and_failed_settlement(store):
    async def go():
        async with Client(build_server(settings(), store, FakeFacilitator(valid=False))) as c:
            req = (await c.call_tool("privi_verify_lot", {"lot_code": "LOT-1"})).structured_content
            r = await c.call_tool("privi_verify_lot", {"lot_code": "LOT-1"}, meta={"x402/payment": payment_for(req)})
            assert r.is_error and "insufficient_funds" in r.structured_content["error"]
        async with Client(build_server(settings(), store, FakeFacilitator(settle_ok=False))) as c:
            req = (await c.call_tool("privi_verify_lot", {"lot_code": "LOT-1"})).structured_content
            r = await c.call_tool("privi_verify_lot", {"lot_code": "LOT-1"}, meta={"x402/payment": payment_for(req)})
            assert r.is_error and r.structured_content["error"].startswith("Settlement failed")
            assert "integrity" not in r.structured_content  # no free result on failed settlement
    run(go)


def test_tampering_detected(store, tmp_path):
    db = sqlite3.connect(str(tmp_path / "t.db"))
    db.execute("UPDATE events SET quantity='900 pcs' WHERE lot_code='LOT-1' AND seq=2")
    db.commit()

    async def go():
        async with Client(build_server(settings(payments_enabled=False), store)) as c:
            r = await c.call_tool("privi_chain_of_custody", {"lot_code": "LOT-1"})
            integ = r.structured_content["integrity"]
            assert integ["valid"] is False and integ["broken_at_seq"] == 2
    run(go)


def test_write_requires_auth_over_stdio(store, monkeypatch):
    async def go(expect_ok):
        async with Client(build_server(settings(), store, FakeFacilitator())) as c:
            r = await c.call_tool("privi_record_event", {
                "lot_code": "LOT-2", "event_type": "received", "location": "Marysville, MI", "actor": "Acme"})
            assert r.is_error != expect_ok
    monkeypatch.delenv("PRIVI_ALLOW_LOCAL_WRITES", raising=False)
    run(lambda: go(False))
    monkeypatch.setenv("PRIVI_ALLOW_LOCAL_WRITES", "1")
    run(lambda: go(True))
    assert store.exists("LOT-2")


def test_onchain_checkpoint_on_lots(store):
    from privi_verify.anchoring import Checkpoints

    class FakeAnchor:
        def anchor(self, hashes, label):
            return {"status": "confirmed", "merkle_root": "ab" * 32, "tx_hash": "0x" + "cd" * 32,
                    "block_number": 1, "block_time": 2,
                    "receipts": [{"hash": h, "proof": [], "tx_hash": "0x" + "cd" * 32} for h in hashes]}

    cps = Checkpoints(store._db, store._lock)

    async def verify():
        async with Client(build_server(settings(payments_enabled=False), store)) as c:
            return (await c.call_tool("privi_verify_lot", {"lot_code": "LOT-1"})).structured_content

    before = run(verify)
    assert before["integrity"]["onchain_checkpoint"]["anchored"] is False
    assert cps.run_once(store.heads(), FakeAnchor(), "privi-verify") == 1
    after = run(verify)
    cp = after["integrity"]["onchain_checkpoint"]
    assert cp["anchored"] and cp["matches_current_record"] and cp["seq"] == 3 and after["integrity"]["valid"]
