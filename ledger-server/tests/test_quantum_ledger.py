import json
import sqlite3

import anyio
from mcp import Client

from privi_ledger.config import Settings
from privi_ledger.quantum_ledger import GENESIS_PREV, QuantumLedger
from privi_ledger.server import build_server
from privi_ledger.store import Ledger

PAY_TO = "0x1990589FD200E043b8C6FD9ec5956c61b3071048"


class FakeFacilitator:
    async def verify(self, payload, req):
        return {"isValid": True}

    async def settle(self, payload, req):
        return {"success": True, "transaction": "0x" + "ab" * 32, "network": req["network"]}


def _srv(ledger):
    return build_server(Settings(pay_to=PAY_TO), ledger, FakeFacilitator())


def _ql(srv) -> QuantumLedger:
    return srv.privi_qledger


def test_blocks_seal_link_and_verify(tmp_path):
    ledger = Ledger(str(tmp_path / "q.db"))
    srv = _srv(ledger)
    ql = _ql(srv)
    g = ql.seal(force=True)
    assert g["block"]["height"] == 0 and g["block"]["prev_block_hash"] == GENESIS_PREV
    assert len(g["block_hash"]) == 128 and g["block"]["foundation"]["stack"].startswith("Cosmos SDK")
    assert ql.seal() is None                                   # nothing new to seal
    org = ledger.create_org("Acme")["org_id"]
    e1 = ledger.record(org, "agent", "claude", "payment", "Paid invoice 1")
    ledger.record(org, "agent", "claude", "message", "Sent receipt")
    b1 = ql.seal()
    assert b1["block"]["height"] == 1 and b1["block"]["new_entries"] == 2
    assert b1["block"]["prev_block_hash"] == g["block_hash"]
    ledger.record(org, "agent", "claude", "data_access", "Read file")
    b2 = ql.seal()
    assert b2["block"]["tree_size"] == 3
    v = ql.verify_chain()
    assert v["valid"] and v["blocks"] == 3, v

    p = ql.entry_proof(e1["entry_hash"])
    assert p["sealed"] and p["valid"] and p["block"]["block"]["height"] == 1

    # tamper with a sealed block: detected
    with ledger._lock:
        body = json.loads(ledger._db.execute("SELECT body FROM qblocks WHERE height=1").fetchone()[0])
        body["new_entries"] = 99
        ledger._db.execute("UPDATE qblocks SET body=? WHERE height=1", (json.dumps(body),))
        ledger._db.commit()
    bad = ql.verify_chain()
    assert not bad["valid"] and bad["broken_at_height"] == 1


def test_rewritten_entry_is_caught(tmp_path):
    ledger = Ledger(str(tmp_path / "q.db"))
    ql = _ql(_srv(ledger))
    org = ledger.create_org("Acme")["org_id"]
    ledger.record(org, "agent", "claude", "payment", "Paid invoice 1")
    ql.seal(force=True)
    with ledger._lock:
        ledger._db.execute("UPDATE entries SET entry_hash=? WHERE id=1", ("ff" * 32,))
        ledger._db.commit()
    v = ql.verify_chain()
    assert not v["valid"] and any("entries" in p for p in v["problems"])


def test_foundation_witness_is_recorded(tmp_path):
    ledger = Ledger(str(tmp_path / "q.db"))
    srv = _srv(ledger)
    ql = QuantumLedger(ledger, srv.privi_fortress,
                       witness=lambda: {"evm_chain_id": 262144, "height": 58638, "block_hash": "0x" + "cd" * 32})
    b = ql.seal(force=True)
    assert b["block"]["foundation_witness"]["height"] == 58638
    assert ql.verify_chain()["valid"]


def test_mcp_tools(tmp_path, monkeypatch):
    ledger = Ledger(str(tmp_path / "q.db"))
    acme = ledger.create_org("Acme")
    monkeypatch.setenv("LEDGER_LOCAL_ORG_KEY", acme["api_key"])

    async def go():
        async with Client(_srv(ledger)) as c:
            r = (await c.call_tool("ledger_record_action", {"stream_id": "a", "actor": "claude",
                                                            "action_type": "payment", "summary": "x"})).structured_content
            s = (await c.call_tool("qledger_seal", {})).structured_content
            assert s["sealed"] and s["block"]["block"]["height"] == 0
            st = (await c.call_tool("qledger_status", {})).structured_content
            assert st["ledger"] == "Privi Quantum Ledger" and st["pending_entries"] == 0
            blk = (await c.call_tool("qledger_block", {"height": 0})).structured_content
            assert blk["valid"], blk
            pr = (await c.call_tool("qledger_entry_proof", {"entry_hash": r["entry"]["entry_hash"]})).structured_content
            assert pr["sealed"] and pr["valid"]
            v = (await c.call_tool("qledger_verify_chain", {})).structured_content
            assert v["valid"]
    anyio.run(go)
