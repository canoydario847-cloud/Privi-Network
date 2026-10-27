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


def test_scan_pages_and_search(tmp_path):
    from starlette.testclient import TestClient
    ledger = Ledger(str(tmp_path / "q.db"))
    srv = _srv(ledger)
    ql = _ql(srv)
    org = ledger.create_org("Acme")["org_id"]
    e1 = ledger.record(org, "secret-stream", "claude", "payment", "secret thing")["entry_hash"]
    ledger.record(org, "secret-stream", "claude", "message", "another")
    b0 = ql.seal(force=True)
    e3 = ledger.record(org, "secret-stream", "claude", "data_access", "third")["entry_hash"]
    b1 = ql.seal()
    ql.set_settlement(1, {"tx_hash": "0x" + "ab" * 32, "proof": ["cd" * 32], "block_number": 7, "chain_id": 8453,
                          "anchored_hash": b1["signing_digest"]})
    c = TestClient(srv.streamable_http_app(host="0.0.0.0", stateless_http=True, json_response=True))

    assert "Privi" in c.get("/quantum-scan").text and "Quantum Scan" in c.get("/quantum-scan").text
    st = c.get("/quantum-ledger/stats").json()
    assert st["blocks"] == 2 and st["entries"] == 3 and st["settled_blocks"] == 1 and st["head_height"] == 1

    bl = c.get("/quantum-ledger/blocks?limit=1").json()
    assert [b["height"] for b in bl["blocks"]] == [1] and bl["next_before"] == 1 and bl["blocks"][0]["tx_hash"].startswith("0x")
    assert [b["height"] for b in c.get("/quantum-ledger/blocks?before=1").json()["blocks"]] == [0]

    d = c.get("/quantum-ledger/blocks/1").json()
    assert d["valid"] and d["first_entry_index"] == 2 and d["settlement"]["chain_id"] == 8453
    assert c.get("/quantum-ledger/blocks/9").status_code == 404

    ents = c.get("/quantum-ledger/entries").json()
    assert [e["index"] for e in ents["entries"]] == [2, 1, 0] and ents["entries"][0]["block"] == 1
    assert c.get("/quantum-ledger/entries?block=0").json()["total"] == 2
    page = c.get("/quantum-ledger/entries?limit=1&offset=1").json()["entries"]
    assert [e["index"] for e in page] == [1]
    # nothing but hashes leaves the server: no org, stream or contents
    raw = c.get("/quantum-ledger/entries").text + c.get("/quantum-ledger/blocks").text
    assert org not in raw and "secret" not in raw

    kinds = lambda q: {m["kind"] for m in c.get("/quantum-ledger/search", params={"q": q}).json()["matches"]}
    assert kinds("1") == {"block_height"}
    assert kinds(b1["block_hash"]) == {"block_hash"} and kinds(b1["signing_digest"]) == {"signing_digest"}
    assert "entry_hash" in kinds(e1) and kinds(e3) == {"entry_hash"}
    assert "settlement_tx" in kinds("0x" + "ab" * 32) and kinds(b1["block"]["log_root"]) == {"log_root"}
    assert "previous_block_hash" in kinds(b0["block_hash"])
    assert c.get("/quantum-ledger/search", params={"q": "zz"}).json()["matches"] == []
