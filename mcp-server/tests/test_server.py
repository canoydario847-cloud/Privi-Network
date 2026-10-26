import json
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


def test_cdp_jwt_and_mainnet_guard():
    import base64, json as _j
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    from privi_verify.x402 import cdp_jwt, CDP_FACILITATOR_URL

    k = Ed25519PrivateKey.generate()
    seed = k.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    pub = k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    secret = base64.b64encode(seed + pub).decode()
    tok = cdp_jwt("key-123", secret, "POST", CDP_FACILITATOR_URL + "/verify")
    h, c, s = tok.split(".")
    pad = lambda x: x + "=" * (-len(x) % 4)
    header, claims = _j.loads(base64.urlsafe_b64decode(pad(h))), _j.loads(base64.urlsafe_b64decode(pad(c)))
    assert header["alg"] == "EdDSA" and header["kid"] == "key-123" and len(header["nonce"]) == 32
    assert claims["iss"] == "cdp" and claims["aud"] == ["cdp_service"] and claims["sub"] == "key-123"
    assert claims["uri"] == "POST api.cdp.coinbase.com/platform/v2/x402/verify" and claims["exp"] - claims["nbf"] == 120
    k.public_key().verify(base64.urlsafe_b64decode(pad(s)), f"{h}.{c}".encode())   # raises if invalid

    with pytest.raises(ValueError):          # mainnet on the testnet-only facilitator is refused
        Settings(pay_to=PAY_TO, network_key="base").validate()
    with pytest.raises(ValueError):          # Coinbase facilitator without credentials is refused
        Settings(pay_to=PAY_TO, network_key="base", facilitator_url=CDP_FACILITATOR_URL).validate()
    Settings(pay_to=PAY_TO, network_key="base", facilitator_url=CDP_FACILITATOR_URL,
             cdp_key_id="k", cdp_key_secret=secret).validate()


def test_server_card(store):
    from starlette.testclient import TestClient
    s = build_server(settings(), store, FakeFacilitator())
    with TestClient(s.streamable_http_app(host="0.0.0.0", stateless_http=True, json_response=True)) as http:
        card = http.get("/.well-known/mcp/server-card.json").json()
        assert card["serverInfo"]["name"] == "privi-verify" and any(t["name"] == "privi_verify_lot" for t in card["tools"])


def test_pay_page_tools_ask_for_payment(store):
    """/pay lists each paid tool with arguments the tool accepts, and calling it unpaid returns x402 terms."""
    import re
    from starlette.testclient import TestClient
    s = build_server(settings(), store, FakeFacilitator())
    hdr = {"Accept": "application/json, text/event-stream"}
    with TestClient(s.streamable_http_app(host="0.0.0.0", stateless_http=True, json_response=True)) as http:
        page = http.get("/pay")
        assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
        assert "/*PRIVI_PAY_CONFIG*/" not in page.text
        cfg = json.loads(re.search(r"const CONFIG = (\{.*?\});\n", page.text).group(1))
        assert {t["name"] for t in cfg["tools"]} == {"privi_verify_lot", "privi_chain_of_custody"}
        for t in cfg["tools"]:
            args = {a["name"]: a["value"] for a in t["args"]}
            r = http.post("/mcp", headers=hdr, json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                                     "params": {"name": t["name"], "arguments": args}}).json()["result"]
            assert r["isError"] and r["structuredContent"]["accepts"][0]["network"] == cfg["network"]


def test_chainflow_web_api_and_labels(store, tmp_path):
    """Manufacturers record events from the ChainFlow site with a key; anyone with a label sees that event free."""
    from starlette.testclient import TestClient
    from privi_verify.anchoring import Checkpoints
    s = build_server(settings(payments_enabled=False, write_keys={"mk_test"}), store)
    auth = {"Authorization": "Bearer mk_test"}
    with TestClient(s.streamable_http_app(host="0.0.0.0", stateless_http=True, json_response=True)) as http:
        pre = http.options("/api/chainflow/events")
        assert pre.headers["access-control-allow-origin"] == "*" and "authorization" in pre.headers["access-control-allow-headers"]
        assert http.post("/api/chainflow/key", headers=auth).json() == {"valid": True}
        assert http.post("/api/chainflow/key", headers={"Authorization": "Bearer nope"}).status_code == 401
        body = {"lot_code": "BW-2026-0042", "event_type": "inspected", "location": "Port Huron, MI",
                "actor": "Blue Water Fab QA", "product": "Bracket A-12", "quantity": "800 pcs", "notes": "CMM pass"}
        assert http.post("/api/chainflow/events", json=body).status_code == 401
        bad = http.post("/api/chainflow/events", headers=auth, json={**body, "event_type": "painted"})
        assert bad.status_code == 400 and "inspected" in bad.json()["event_types"]
        r = http.post("/api/chainflow/events", headers=auth, json=body).json()
        fp = r["event"]["record_hash"]
        assert r["recorded"] and r["label_url"].endswith(f"/label/{fp}") and r["event"]["seq"] == 1

        lab = http.get(f"/api/chainflow/label/{fp}").json()
        assert lab["found"] and lab["lot_code"] == "BW-2026-0042" and lab["integrity"]["history_intact"]
        assert lab["onchain"]["covered"] is False and lab["later_events"] == 0
        page = http.get(f"/label/{fp}")
        assert page.status_code == 200 and "Bracket A-12" in page.text and "Record intact" in page.text
        assert http.get("/label/" + "0" * 64).status_code == 404
        assert http.get("/api/chainflow/label/xyz").status_code == 400

        # an earlier label stays valid when later events are added, and shows once a checkpoint covers it
        first = store.events("LOT-1")[0]["record_hash"]

        class FakeAnchor:
            def anchor(self, hashes, label):
                return {"status": "confirmed", "merkle_root": "ab" * 32, "tx_hash": "0x" + "cd" * 32, "block_number": 9,
                        "block_time": 2, "receipts": [{"hash": h, "proof": [], "tx_hash": "0x" + "cd" * 32} for h in hashes]}
        Checkpoints(store._db, store._lock).run_once(store.heads(), FakeAnchor(), "privi-verify")
        old = http.get(f"/api/chainflow/label/{first}").json()
        assert old["later_events"] == 2 and old["onchain"]["covered"] and old["onchain"]["block_number"] == 9

    # tampering with an event after the label was printed shows on the label page
    db = sqlite3.connect(str(tmp_path / "t.db"))
    db.execute("UPDATE events SET quantity='9 t' WHERE lot_code='LOT-1' AND seq=1")
    db.commit()
    with TestClient(s.streamable_http_app(host="0.0.0.0", stateless_http=True, json_response=True)) as http:
        page = http.get(f"/label/{first}")
        assert page.status_code == 200 and "Record altered" in page.text
        assert http.get(f"/api/chainflow/label/{first}").json()["integrity"]["history_intact"] is False
