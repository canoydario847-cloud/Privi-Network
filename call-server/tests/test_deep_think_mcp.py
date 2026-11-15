# Copyright (c) 2026 Privi World Corp. All rights reserved.
"""Deep Think MCP payment flow tests with a fake facilitator (no chain transfers)."""
import asyncio
from types import SimpleNamespace

from mcp_types import CallToolResult, TextContent

from privi_call import deep_think_tools

A, B = "a" * 64, "b" * 64
TX = "0x" + "1" * 64
PASS = {x: True for x in ("syntax", "tests", "edge_cases", "security", "integration")}


class FakeMCP:
    def __init__(self):
        self.tools = {}

    def tool(self, **kwargs):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn
        return deco


class FakePaywall:
    def __init__(self):
        self.calls = 0
        self.settles = 0

    async def run(self, tool, description, meta, work):
        self.calls += 1
        if "x402/payment" not in meta:
            quote = {"accepts": [{"amount": "10000", "network": "eip155:8453"}]}
            return CallToolResult(is_error=True, structured_content=quote,
                                  content=[TextContent(type="text", text="payment required")])
        self.settles += 1
        return CallToolResult(structured_content=await work(),
                              content=[TextContent(type="text", text="paid")],
                              meta={"x402/payment-response": {"success": True, "transaction": TX}})


def call_async(fn, **kwargs):
    return asyncio.run(fn(**kwargs))


def ctx(paid=False):
    return SimpleNamespace(request_context=SimpleNamespace(
        meta={"x402/payment": {"signed": "fake-test-only"}} if paid else {}))


def new(tmp_path, monkeypatch):
    server, paywall = FakeMCP(), FakePaywall()
    s = SimpleNamespace(db_path=str(tmp_path / "calls.sqlite"), payments_ready=True,
                        network_key="base", per_call_prices={})
    deep_think_tools.register(server, s, paywall)
    init = server.tools["deep_think_plan"](
        "Implement a safe payment pipeline.", "Python", ["No charges on validation errors"])
    assert init["task_id"].startswith("dt_")
    assert s.per_call_prices["deep_think_redo"] == "0.01"
    return server.tools, paywall, init


def test_paid_redo_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEP_THINK_PAID_REDOS_ENABLED", raising=False)
    api, paywall, init = new(tmp_path, monkeypatch)
    tid, token = init["task_id"], init["task_token"]
    api["deep_think_review"](tid, token, A, PASS)
    out = call_async(api["deep_think_redo"], task_id=tid, task_token=token,
                     prior_sha256=A, new_sha256=B, approve_usdc_charge=True, ctx=ctx(paid=True))
    assert out.is_error
    assert paywall.calls == 0


def test_approval_quote_settlement_and_duplicate_are_safe(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEP_THINK_PAID_REDOS_ENABLED", "1")
    api, paywall, init = new(tmp_path, monkeypatch)
    tid, token = init["task_id"], init["task_token"]
    first = api["deep_think_review"](tid, token, A, PASS)
    assert first["revision"] == 0

    def redo(approved, paid):
        return call_async(api["deep_think_redo"], task_id=tid, task_token=token,
                          prior_sha256=A, new_sha256=B, approve_usdc_charge=approved, ctx=ctx(paid))

    rejected = redo(False, True)
    assert rejected.is_error and paywall.calls == 0

    quote = redo(True, False)
    assert quote.is_error and quote.structured_content["accepts"][0]["amount"] == "10000"
    assert paywall.settles == 0
    assert api["deep_think_review"](tid, token, B, PASS)["status"] == "redo_requires_payment"

    paid = redo(True, True)
    assert not paid.is_error
    assert paid.structured_content["revision"] == 1
    assert paid.structured_content["settlement_tx"] == TX
    assert paywall.settles == 1

    duplicate = redo(True, True)
    assert not duplicate.is_error
    assert duplicate.structured_content["charged"] is False
    assert paywall.settles == 1
