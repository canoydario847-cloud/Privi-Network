"""Production default: no free tools on Privi Anchor; every tool needs a paid API key."""
import anyio
from mcp import Client

from privi_anchor.server import Settings, build_server
from test_anchor import FakeChain, store  # noqa: F401


def test_every_tool_needs_a_paid_key(store, monkeypatch):
    monkeypatch.setenv("ANCHOR_ALL_TOOLS_PAID", "1")
    monkeypatch.delenv("ANCHOR_ALLOW_LOCAL", raising=False)

    async def go():
        async with Client(build_server(Settings(), FakeChain(), store, receipt_timeout=1)) as c:
            for tool, args in (("anchor_status", {}), ("anchor_hash_text", {"text": "x"})):
                r = await c.call_tool(tool, args)
                assert r.is_error and "paid service" in r.structured_content["error"]
    anyio.run(go)

    monkeypatch.setenv("ANCHOR_ALLOW_LOCAL", "1")     # a key holder (local operator) gets through

    async def keyed():
        async with Client(build_server(Settings(), FakeChain(), store, receipt_timeout=1)) as c:
            assert not (await c.call_tool("anchor_hash_text", {"text": "x"})).is_error
    anyio.run(keyed)
