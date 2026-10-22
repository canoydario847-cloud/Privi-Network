# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Call - https://priviflow.us - dariocanoy@priviflow.us
import base64
import hashlib
import hmac
import json
from urllib.parse import urlencode

import anyio
import httpx2 as httpx
import pytest
from mcp import Client
from starlette.testclient import TestClient

from privi_call import voice
from privi_call.config import Settings
from privi_call.router import RouteError, Router, check_public_endpoint
from privi_call.server import build_server
from privi_call.store import Store, anchor_head

TOKEN = "twilio-test-token"


def fake_agent(request: httpx.Request) -> httpx.Response:
    """A tiny MCP agent: one tool 'echo' and one paid tool 'paid' that wants x402."""
    msg = json.loads(request.content)
    m, rid = msg.get("method"), msg.get("id")
    if m == "initialize":
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": rid, "result": {"protocolVersion": "2025-06-18",
                              "capabilities": {"tools": {}}, "serverInfo": {"name": "fake", "version": "1"}}},
                              headers={"mcp-session-id": "s1"})
    if m == "notifications/initialized":
        return httpx.Response(202)
    if m == "tools/list":
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": rid, "result": {"tools": [
            {"name": "echo", "description": "echo", "inputSchema": {"type": "object"}},
            {"name": "paid", "description": "paid", "inputSchema": {"type": "object"}}]}})
    if m == "tools/call":
        p = msg["params"]
        if p["name"] == "paid" and "x402/payment" not in (p.get("_meta") or {}):
            body = {"x402Version": 2, "accepts": [{"amount": "10000"}]}
            return httpx.Response(200, text="event: message\ndata: " + json.dumps({"jsonrpc": "2.0", "id": rid, "result": {
                "isError": True, "structuredContent": body, "content": [{"type": "text", "text": json.dumps(body)}]}}) + "\n\n",
                headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": rid, "result": {
            "structuredContent": {"echo": p.get("arguments"), "paid": "x402/payment" in (p.get("_meta") or {})},
            "content": [{"type": "text", "text": "ok"}]}})
    return httpx.Response(400, json={"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "nope"}})


class FakeAnchor:
    def anchor(self, hashes, label):
        return {"status": "confirmed", "tx_hash": "0x" + "ab" * 32, "chain_id": 8453, "network": "base",
                "block_number": 9, "receipts": [{"hash": h, "proof": []} for h in hashes]}


class FakeFacilitator:
    async def verify(self, payload, req):
        return {"isValid": True}

    async def settle(self, payload, req):
        return {"success": True, "transaction": "0xfeed"}


def make(tmp_path, **kw):
    official = [{"number": "100", "name": "Privi Ledger", "endpoint": "https://ledger.test/mcp", "description": "ledger", "tags": []}]
    s = Settings(db_path=str(tmp_path / "c.db"), official=official, free_calls_per_day=2, twilio_auth_token=TOKEN,
                 phone_number="+18105550100", public_url="https://privi-call.test", **kw)
    store = Store(s.db_path)
    router = Router(transport=httpx.MockTransport(fake_agent), check_endpoints=False)
    mcp = build_server(s, store=store, router=router)
    return s, store, mcp


def sign(url, params):
    data = url + "".join(k + params[k] for k in sorted(params))
    return base64.b64encode(hmac.new(TOKEN.encode(), data.encode(), hashlib.sha1).digest()).decode()


def test_agent_calls_billing_and_sealed_log(tmp_path, monkeypatch):
    s, store, mcp = make(tmp_path)
    monkeypatch.setattr("privi_call.server.check_public_endpoint", lambda u: u)

    async def go():
        async with Client(mcp) as c:
            d = (await c.call_tool("call_directory", {})).structured_content
            assert d["agents"][0]["number"] == "100" and d["agents"][0]["official"]
            t = (await c.call_tool("call_list_tools", {"number": "100"})).structured_content
            assert [x["name"] for x in t["tools"]] == ["echo", "paid"]
            r = (await c.call_tool("call_agent", {"number": "100", "tool": "echo", "arguments": {"x": 1}})).structured_content
            assert r["result"]["echo"] == {"x": 1} and r["call"]["charged_usd"] == "0"
            # paid target: x402 challenge comes back, then payment is forwarded
            r = await c.call_tool("call_agent", {"number": "100", "tool": "paid"})
            assert r.is_error and r.structured_content["result"]["x402Version"] == 2
            r = (await c.call_tool("call_agent", {"number": "100", "tool": "paid", "payment": {"sig": "x"}})).structured_content
            assert r["result"]["paid"] is True
            # community agent: register, 2 free calls, then credits
            reg = (await c.call_tool("call_register_agent", {"name": "Helper", "endpoint": "https://helper.test/mcp",
                                                             "description": "helps with things", "tags": ["help"]})).structured_content
            num = reg["number"]
            assert num == "2000" and reg["remove_secret"].startswith("pas_")
            for _ in range(2):
                r = (await c.call_tool("call_agent", {"number": num, "tool": "echo"})).structured_content
                assert r["call"]["billing"] == "free (daily allowance)"
            r = await c.call_tool("call_agent", {"number": num, "tool": "echo"})
            assert r.is_error and "call_credits_buy" in r.structured_content["fix"]
            key = store.new_credit_key(3, "test")
            r = (await c.call_tool("call_agent", {"number": num, "tool": "echo", "call_key": key})).structured_content
            assert r["call"]["charged_usd"] == "0.001" and r["call"]["credits_left"] == 2
            # credits can't be sold before payment keys exist
            b = await c.call_tool("call_credits_buy", {})
            assert b.is_error and "free calls" in b.structured_content["error"]
            log = (await c.call_tool("call_log", {"limit": 50})).structured_content
            assert log["calls"][0]["seq"] == log["head"]["seq"] and log["stats"]["agents_on_network"] == 2
            v = (await c.call_tool("call_verify_log", {})).structured_content
            assert v["valid"] and v["records"] == len(log["calls"])
    anyio.run(go)

    assert anchor_head(store, FakeAnchor())["seq"] == store.head()["seq"]
    assert anchor_head(store, FakeAnchor()) is None  # nothing new to anchor
    store._db.execute("UPDATE calls SET tool='forged' WHERE seq=2")
    bad = store.verify_chain()
    assert not bad["valid"] and bad["broken_at_seq"] == 2


def test_credit_sales_with_x402(tmp_path):
    s, store, _ = make(tmp_path, cdp_key_id="k", cdp_key_secret="s")
    from privi_call.x402 import Paywall
    mcp = build_server(s, store=store, router=Router(transport=httpx.MockTransport(fake_agent), check_endpoints=False),
                       paywall=Paywall(s, FakeFacilitator(), service={"url": "https://privi-call.test/mcp"}))

    async def go():
        async with Client(mcp) as c:
            r = await c.call_tool("call_credits_buy", {})
            req = r.structured_content["accepts"][0]
            assert r.is_error and req["amount"] == "1000000" and req["network"] == "eip155:8453"
            pay = {"x402Version": 2, "accepted": req, "payload": {}}
            r = await c.call_tool("call_credits_buy", {}, meta={"x402/payment": pay})
            assert not r.is_error and r.structured_content["credits"] == 1000
            assert store.balance(r.structured_content["call_key"]) == 1000
    anyio.run(go)


def test_phone_line(tmp_path):
    s, store, mcp = make(tmp_path)
    app = mcp.streamable_http_app(stateless_http=True, json_response=True)
    with TestClient(app) as http:
        def post(path, params, good=True):
            url = s.public_url + path
            sig = sign(url, params) if good else "bad"
            return http.post(path, content=urlencode(params), headers={
                "content-type": "application/x-www-form-urlencoded", "x-twilio-signature": sig})

        base = {"CallSid": "CA1", "From": "+18105551234", "To": "+18105550100"}
        assert post("/voice/inbound", base, good=False).status_code == 403
        r = post("/voice/inbound", base)
        assert r.status_code == 200 and "<Gather" in r.text and "Privi" in r.text
        r = post("/voice/turn?t=1", {**base, "SpeechResult": "how much does it cost"})
        assert "29 dollars" in r.text and "t=2" in r.text
        r = post("/voice/turn?t=2", {**base, "Digits": "0"})
        assert "<Dial" in r.text and "+13134138532" in r.text
        r = post("/voice/turn?t=2", {**base, "SpeechResult": "I want a pilot"})
        assert "say your name" in r.text
        r = post("/voice/lead", {**base, "SpeechResult": "Ann at Blue Water Plastics, call 810 555 1234"})
        assert "Dario will get back" in r.text
        assert post("/voice/status", {**base, "CallStatus": "completed", "CallDuration": "95"}).status_code == 204

        pub = http.get("/calls.json").json()
        assert all(c["channel"] == "phone" for c in pub["calls"])
        assert pub["calls"][0]["caller"] == "phone ***-1234" and "+1810" not in json.dumps(pub)
        assert http.get("/admin/calls").status_code == 401
        assert "+13134138532" not in http.get("/").text
        assert "One number for every AI agent" in http.get("/").text
        assert http.get("/verify").json()["valid"]
        assert http.get("/.well-known/agent-card.json").json()["name"] == "Privi Call"


def test_intents_and_safety():
    assert voice.intent("can I talk to Dario") == "human"
    assert voice.intent("what does it cost") == "pricing"
    assert voice.intent("", "2") == "pilot"
    assert voice.intent("we make parts for cars") == "manufacturing"
    assert voice.intent("") == "silence"
    assert "&lt;" in voice.hangup("<b>", "Polly.Matthew")
    for bad in ("http://example.com/mcp", "https://localhost/mcp", "https://127.0.0.1/mcp", "https://user:pw@example.com/mcp"):
        with pytest.raises(RouteError):
            check_public_endpoint(bad)


def test_phone_trial_keeps_number_private(tmp_path):
    s, store, mcp = make(tmp_path, phone_trial=True)
    app = mcp.streamable_http_app(stateless_http=True, json_response=True)
    with TestClient(app) as http:
        assert "+18105550100" not in http.get("/").text
        st = http.get("/status").json()
        assert st["phone"] is None and st["phone_trial"] is True
        base = {"CallSid": "CA2", "From": "+13134138532", "To": "+18105550100"}
        url = s.public_url + "/voice/inbound"
        r = http.post("/voice/inbound", content=urlencode(base), headers={
            "content-type": "application/x-www-form-urlencoded", "x-twilio-signature": sign(url, base)})
        assert r.status_code == 200 and "<Gather" in r.text

    async def go():
        async with Client(mcp) as c:
            r = await c.call_tool("call_phone_line", {})
            assert "+18105550100" not in json.dumps(r.structured_content)
    anyio.run(go)
