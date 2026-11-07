"""Production default: no free tools. Paid-plan organizations use tools as part of their plan; everyone else pays per call."""
import anyio
from mcp import Client

from test_ledger import FakeFacilitator, as_org, server


def test_every_tool_paid_unless_on_pro(ledger, monkeypatch):
    monkeypatch.setenv("LEDGER_ALL_TOOLS_PAID", "1")
    from privi_ledger.plans import Plans
    free_org = Plans(ledger).signup("Free Co")       # self-serve (pay-as-you-go) organization
    pro_org = Plans(ledger).signup("Pro Co")
    fac = FakeFacilitator()

    async def go():
        srv = server(ledger, fac)
        from privi_ledger.plans import Plans
        Plans(ledger).extend_pro(pro_org["org_id"])
        args = {"stream_id": "a", "actor": "bot", "action_type": "message", "summary": "hello"}
        async with Client(srv) as c:
            # a free-plan organization is asked to pay per call ($0.01 = 10000 atomic USDC)
            need = await c.call_tool("ledger_record_action", args)
            assert need.is_error and need.structured_content["accepts"][0]["amount"] == "10000"
            pay = {"x402Version": 2, "resource": need.structured_content["resource"],
                   "accepted": need.structured_content["accepts"][0], "payload": {}}
            ok = await c.call_tool("ledger_record_action", args, meta={"x402/payment": pay})
            assert not ok.is_error and ok.structured_content["entry"]["seq"] == 1 and fac.calls == ["verify", "settle"]
            # a failing paid call is never settled
            fac.calls.clear()
            bad = await c.call_tool("ledger_record_action", {**args, "action_type": "not-a-type"}, meta={"x402/payment": pay})
            assert bad.is_error and "settle" not in fac.calls
            # signup is paid too
            assert (await c.call_tool("ledger_signup", {"organization_name": "X"})).is_error

    as_org(monkeypatch, free_org["api_key"])
    anyio.run(go)

    async def pro():
        async with Client(server(ledger, fac)) as c:
            r = await c.call_tool("ledger_record_action", {"stream_id": "a", "actor": "bot", "action_type": "message",
                                                           "summary": "included in Pro"})
            assert not r.is_error, r
    from privi_ledger.plans import Plans
    Plans(ledger).extend_pro(pro_org["org_id"])
    as_org(monkeypatch, pro_org["api_key"])
    anyio.run(pro)
