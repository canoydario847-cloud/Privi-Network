"""Production default: no free tools on Privi Verify (manufacturer write keys are customers and pass)."""
import anyio
from mcp import Client

from privi_verify.server import build_server
from test_server import FakeFacilitator, payment_for, settings, store  # noqa: F401


def test_lookup_is_paid_per_call(store, monkeypatch):
    monkeypatch.setenv("PRIVI_ALL_TOOLS_PAID", "1")
    fac = FakeFacilitator()

    async def go():
        async with Client(build_server(settings(), store, fac)) as c:
            need = await c.call_tool("privi_pricing", {})
            assert need.is_error and need.structured_content["accepts"][0]["amount"] == "10000"
            ok = await c.call_tool("privi_pricing", {}, meta={"x402/payment": payment_for(need.structured_content)})
            assert not ok.is_error
    anyio.run(go)
