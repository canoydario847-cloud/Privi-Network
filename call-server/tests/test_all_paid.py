"""Production default: no free tools on Privi Call (prepaid call keys still work for call_agent)."""
import anyio
from mcp import Client

from test_call import make


def test_directory_is_paid_per_call(tmp_path, monkeypatch):
    monkeypatch.setenv("CALL_ALL_TOOLS_PAID", "1")
    s, store, mcp = make(tmp_path, pay_to="0x1990589FD200E043b8C6FD9ec5956c61b3071048")

    async def go():
        async with Client(mcp) as c:
            need = await c.call_tool("call_directory", {})
            assert need.is_error and need.structured_content["accepts"][0]["amount"] == "10000"
    anyio.run(go)
