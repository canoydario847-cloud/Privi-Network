"""Folder manifests and proof-of-existence certificates."""
import anyio
from mcp import Client
from starlette.testclient import TestClient

from privi_anchor import merkle
from privi_anchor.proofs import file_leaf
from privi_anchor.server import Settings, build_server
from test_anchor import FakeChain, h, store  # noqa: F401


def test_manifest_and_certificate(store, monkeypatch):
    monkeypatch.setenv("ANCHOR_ALLOW_LOCAL", "1")
    chain = FakeChain()
    files = [{"path": f"evidence/file{i}.pdf", "sha256": h(f"f{i}")} for i in range(7)]
    srv = build_server(Settings(), chain, store, receipt_timeout=1)
    out = {}

    async def go():
        async with Client(srv) as c:
            m = (await c.call_tool("anchor_manifest", {"files": files, "name": "Audit evidence"})).structured_content
            assert m["status"] == "confirmed" and m["files"] == 7 and len(chain.txs) == 1      # one transaction for all files
            root = m["manifest_root"]
            assert merkle.root_from_calldata(chain.txs[m["tx_hash"]]["input"]) == root
            ok = (await c.call_tool("anchor_manifest_check", {"manifest_root": root, "path": "evidence/file3.pdf",
                                                              "sha256": h("f3")})).structured_content
            assert ok["in_manifest"] and ok["anchored"] and ok["manifest"]["files"] == 7
            assert merkle.root_from_proof(file_leaf("evidence/file3.pdf", h("f3")), ok["proof"]) == root
            changed = (await c.call_tool("anchor_manifest_check", {"manifest_root": root, "path": "evidence/file3.pdf",
                                                                   "sha256": h("edited")})).structured_content
            assert changed["in_manifest"] is False and "changed" in changed["reason"]
            renamed = (await c.call_tool("anchor_manifest_check", {"manifest_root": root, "path": "evidence/other.pdf",
                                                                   "sha256": h("f3"), "proof": ok["proof"]})).structured_content
            assert renamed["in_manifest"] is False
            dup = await c.call_tool("anchor_manifest", {"files": files[:1] * 2})
            assert dup.is_error and "twice" in dup.structured_content["error"]

            await c.call_tool("anchor_hashes", {"hashes": [h("drawing rev C")]})
            cert = (await c.call_tool("anchor_certificate", {"hash": h("drawing rev C"), "title": "Bracket A-12 drawing rev C",
                                                             "owner": "Blue Water Fab"})).structured_content
            assert cert["hash"] == h("drawing rev C") and cert["block_time_utc"] and cert["certificate_url"].endswith(cert["certificate_id"])
            got = (await c.call_tool("anchor_certificate_get", {"certificate_id": cert["certificate_id"]})).structured_content
            assert got["tx_hash"] == cert["tx_hash"]
            none = await c.call_tool("anchor_certificate", {"hash": h("never anchored"), "title": "Nope doc", "owner": "X Co"})
            assert none.is_error
            out["cid"] = cert["certificate_id"]
    anyio.run(go)
    http = TestClient(srv.streamable_http_app())
    page = http.get(f"/certificates/{out['cid']}")
    assert page.status_code == 200 and "Bracket A-12 drawing rev C" in page.text and "Blue Water Fab" in page.text
    assert http.get(f"/certificates/{out['cid']}?format=json").json()["owner"] == "Blue Water Fab"
    assert http.get("/certificates/cert_nope").status_code == 404


def test_new_tools_need_a_key(store, monkeypatch):
    monkeypatch.setenv("ANCHOR_ALL_TOOLS_PAID", "1")
    monkeypatch.delenv("ANCHOR_ALLOW_LOCAL", raising=False)

    async def go():
        async with Client(build_server(Settings(), FakeChain(), store, receipt_timeout=1)) as c:
            for tool, args in (("anchor_manifest", {"files": [{"path": "a", "sha256": h("a")}]}),
                               ("anchor_certificate_get", {"certificate_id": "cert_x"})):
                assert (await c.call_tool(tool, args)).is_error
    anyio.run(go)
