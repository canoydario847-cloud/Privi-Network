# Copyright (c) 2026 Privi World Co. All rights reserved.
"""REST gateway, voice-agent webhook and kits: every request is paid by key or x402."""
import base64
import json

from starlette.testclient import TestClient

from privi_call.x402 import Paywall
from test_call import FakeFacilitator, make

PAY_TO = "0x1990589FD200E043b8C6FD9ec5956c61b3071048"


def client(tmp_path, **kw):
    s, store, mcp = make(tmp_path, pay_to=PAY_TO, **kw)
    return s, store, mcp, TestClient(mcp.streamable_http_app(stateless_http=True, json_response=True))


def test_no_payment_gets_http_402_with_x402_terms(tmp_path):
    s, store, mcp, c = client(tmp_path)
    for r in (c.get("/v1/agents"), c.get("/v1/agents/100/tools"),
              c.post("/v1/call", json={"number": "100", "tool": "echo", "arguments": {"a": 1}})):
        assert r.status_code == 402
        body = r.json()
        assert body["accepts"][0]["amount"] == "10000" and body["accepts"][0]["payTo"] == PAY_TO
        assert json.loads(base64.b64decode(r.headers["payment-required"]))["x402Version"] == 2
        assert "prepaid_key" in body["how_to_pay"]


def test_prepaid_key_pays_one_credit_per_request_and_refunds_failures(tmp_path):
    s, store, mcp, c = client(tmp_path)
    key = store.new_credit_key(3, "test")
    h = {"Authorization": f"Bearer {key}"}
    assert c.get("/v1/balance", headers=h).json() == {"credits": 3}
    found = c.get("/v1/agents?q=ledger", headers=h).json()
    assert found["agents"][0]["number"] == "100" and found["billing"]["credits_left"] == 2
    tools = c.get("/v1/agents/100/tools", headers=h).json()
    assert [t["name"] for t in tools["tools"]] == ["echo", "paid"]
    bad = c.post("/v1/call", headers=h, json={"number": "999", "tool": "echo"})
    assert bad.status_code == 400 and bad.json()["billing"]["charged_credits"] == 0
    r = c.post("/v1/call/100/echo", headers=h, json={"lot": "A1"})
    d = r.json()
    assert r.status_code == 200 and d["result"]["echo"] == {"lot": "A1"} and d["billing"]["credits_left"] == 0
    assert c.get(f"/calls/{d['call']['id']}").status_code == 200       # sealed in the public log
    assert store.verify_chain()["valid"]
    assert c.post("/v1/call", headers=h, json={"number": "100", "tool": "echo"}).status_code == 402
    assert c.get("/v1/agents", headers={"Authorization": "Bearer pck_nope"}).status_code == 401


def test_x402_header_pays_per_call_and_buys_keys(tmp_path):
    s, store, mcp = make(tmp_path, pay_to=PAY_TO, cdp_key_id="id", cdp_key_secret="secret")
    from privi_call.server import build_server
    from privi_call.router import Router
    import httpx2 as httpx
    from test_call import fake_agent
    paywall = Paywall(s, facilitator=FakeFacilitator())
    mcp = build_server(s, store=store, router=Router(transport=httpx.MockTransport(fake_agent), check_endpoints=False),
                       paywall=paywall)
    c = TestClient(mcp.streamable_http_app(stateless_http=True, json_response=True))
    need = c.post("/v1/call", json={"number": "100", "tool": "echo"}).json()
    pay = base64.b64encode(json.dumps({"x402Version": 2, "accepted": need["accepts"][0], "payload": {"signature": "0x"}}).encode()).decode()
    r = c.post("/v1/call", json={"number": "100", "tool": "echo", "arguments": {"x": 2}}, headers={"PAYMENT-SIGNATURE": pay})
    assert r.status_code == 200, r.text
    assert r.json()["result"]["echo"] == {"x": 2} and r.json()["billing"]["paid_with"] == "x402"
    assert json.loads(base64.b64decode(r.headers["payment-response"]))["transaction"] == "0xfeed"
    assert s.payments_ready
    need = c.post("/v1/keys", json={}).json()
    pay = base64.b64encode(json.dumps({"x402Version": 2, "accepted": need["accepts"][0], "payload": {"signature": "0x"}}).encode()).decode()
    k = c.post("/v1/keys", json={}, headers={"X-PAYMENT": pay}).json()
    assert k["key"].startswith("pck_") and store.balance(k["key"]) == s.pack_credits


def test_voice_webhook_shapes_need_a_key(tmp_path):
    s, store, mcp, c = client(tmp_path)
    assert c.post("/v1/hook", json={"function": "privi_find_agents"}).status_code == 401
    key = store.new_credit_key(10, "test")
    h = {"Authorization": f"Bearer {key}"}
    flat = c.post("/v1/hook?function=privi_call", headers=h, json={"number": "100", "tool": "echo", "arguments": {"a": 1}}).json()
    assert flat["result"]["echo"] == {"a": 1}
    retell = c.post("/v1/hook", headers=h, json={"call": {"call_id": "x"}, "name": "privi_list_tools", "args": {"number": "100"}}).json()
    assert retell["tools"][0]["name"] == "echo"
    vapi = c.post("/v1/hook", headers=h, json={"message": {"type": "tool-calls", "toolCallList": [
        {"id": "tc1", "function": {"name": "privi_call", "arguments": {"number": "100", "tool": "echo", "arguments": {"b": 2}}}}]}}).json()
    assert vapi["results"][0]["toolCallId"] == "tc1" and json.loads(vapi["results"][0]["result"])["result"]["echo"] == {"b": 2}
    assert store.balance(key) == 7


def test_openapi_kits_and_console_are_public(tmp_path):
    s, store, mcp, c = client(tmp_path)
    spec = c.get("/openapi.json").json()
    assert spec["openapi"].startswith("3.1") and "/v1/call" in spec["paths"]
    assert set(c.get("/kits").json()["kits"]) == {"openai", "anthropic", "gemini", "vapi", "retell", "elevenlabs"}
    for p in ("openai", "anthropic", "gemini", "vapi", "retell", "elevenlabs"):
        assert "privi_call" in c.get(f"/kits/{p}.json").text
    assert c.get("/kits/nope.json").status_code == 404
    assert "Privi Console" in c.get("/console").text
    assert "/openapi.json" in c.get("/llms.txt").text
