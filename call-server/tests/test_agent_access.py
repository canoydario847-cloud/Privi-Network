# Copyright (c) 2026 Privi World Co. All rights reserved.
"""Paid AI-agent signup: no payment/no agent; settled payment/agent credentials."""
import base64
import json

import httpx2 as httpx
from starlette.testclient import TestClient

from privi_call.router import RouteError, Router
from privi_call.server import build_server
from privi_call.x402 import Paywall
from test_call import FakeFacilitator, fake_agent, make


def _client(tmp_path, monkeypatch, facilitator=None):
    s, store, _ = make(tmp_path, cdp_key_id="test-id", cdp_key_secret="test-secret")
    def mock_public(url):
        if not url.startswith("https://"):
            raise RouteError("agent endpoint must be an https:// URL")
        return url
    monkeypatch.setattr("privi_call.gateway.check_public_endpoint", mock_public)
    mcp = build_server(
        s, store=store,
        router=Router(transport=httpx.MockTransport(fake_agent), check_endpoints=False),
        paywall=Paywall(s, facilitator=facilitator or FakeFacilitator()))
    client = TestClient(mcp.streamable_http_app(stateless_http=True, json_response=True))
    return s, store, client


def _payment(quote):
    return base64.b64encode(json.dumps({
        "x402Version": 2, "accepted": quote["accepts"][0], "payload": {"signature": "test-payment"}
    }).encode()).decode()


def _body(endpoint="https://agent.test/mcp"):
    return {"name": "Research Agent", "endpoint": endpoint,
            "description": "A self-hosted AI agent exposing useful MCP research tools",
            "tags": ["research", "mcp"]}


def test_agent_access_one_dollar_signup_and_private_calls(tmp_path, monkeypatch):
    s, store, c = _client(tmp_path, monkeypatch)
    offer = c.get("/v1/agent-access")
    assert offer.status_code == 200
    assert offer.json()["price"]["amount"] == "1.00"
    assert offer.json()["price"]["frequency"] == "once"
    assert c.get("/v1/agent-access/status").status_code == 401
    assert c.post("/v1/agent-access/call", json={"number": "100", "tool": "echo"}).status_code == 401

    quote = c.post("/v1/agent-access/signup", json=_body())
    assert quote.status_code == 402
    assert quote.json()["accepts"][0]["amount"] == "1000000"
    assert quote.json()["accepts"][0]["network"] == "eip155:8453"
    assert len(store.directory()) == 1  # nothing provisioned before payment
    assert not c.get("/v1/agent-access/status", headers={"Authorization": "Bearer pck_fake"}).json().get("active")

    bad = {"x402Version": 2, "accepted": {**quote.json()["accepts"][0], "amount": "1"}, "payload": {}}
    bad_h = {"PAYMENT-SIGNATURE": base64.b64encode(json.dumps(bad).encode()).decode()}
    assert c.post("/v1/agent-access/signup", json=_body(), headers=bad_h).status_code == 402
    assert len(store.directory()) == 1

    paid = c.post("/v1/agent-access/signup", json=_body(),
                  headers={"PAYMENT-SIGNATURE": _payment(quote.json())})
    assert paid.status_code == 201, paid.text
    data = paid.json()
    key = data["api_key"]
    assert key.startswith("pck_") and data["agent_number"] == "2000"
    assert store.balance(key) == s.pack_credits
    assert len(store.directory()) == 2
    assert "payment-response" in paid.headers
    assert key not in json.dumps(store.calls())

    headers = {"Authorization": f"Bearer {key}"}
    status = c.get("/v1/agent-access/status", headers=headers)
    assert status.status_code == 200 and status.json()["active"]
    assert status.json()["number"] == "2000"
    routed = c.post("/v1/agent-access/call", headers=headers,
                    json={"number": "100", "tool": "echo", "arguments": {"x": 1}})
    assert routed.status_code == 200, routed.text
    assert routed.json()["result"]["echo"] == {"x": 1}
    assert store.balance(key) == s.pack_credits - 1
    assert store.verify_chain()["valid"]

    # One signed $1 payment can activate only one agent, not an unlimited set.
    other = c.post("/v1/agent-access/signup", json=_body("https://another.test/mcp"),
                   headers={"PAYMENT-SIGNATURE": _payment(quote.json())})
    assert other.status_code == 409
    assert len(store.directory()) == 2
    # An existing endpoint cannot be charged again by this signup route.
    assert c.post("/v1/agent-access/signup", json=_body()).status_code == 409


def test_invalid_agent_endpoint_or_payment_failures_never_activate(tmp_path, monkeypatch):
    class Unsettled(FakeFacilitator):
        async def settle(self, payload, req):
            return {"success": False, "error": "declined"}

    s, store, c = _client(tmp_path, monkeypatch, Unsettled())
    assert c.post("/v1/agent-access/signup", json=_body("http://not-secure.test/mcp")).status_code == 400
    assert c.post("/v1/agent-access/signup", json={"name": "a", "endpoint": "https://ok.test/mcp",
                  "description": "too short"}).status_code == 400
    assert len(store.directory()) == 1
    quote = c.post("/v1/agent-access/signup", json=_body())
    assert quote.status_code == 402
    resp = c.post("/v1/agent-access/signup", json=_body(),
                  headers={"PAYMENT-SIGNATURE": _payment(quote.json())})
    assert resp.status_code == 502
    assert len(store.directory()) == 1
    assert store._db.execute("SELECT COUNT(*) FROM paid_agent_access").fetchone()[0] == 0
