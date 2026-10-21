import hashlib
import itertools

import anyio
import pytest
from mcp import Client

from privi_anchor import merkle
from privi_anchor.server import Settings, build_server
from privi_anchor.store import AnchorStore

WALLET = "0xfd5347Efd856DFfAD75B14Dca9bfb95645649b42"


def h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


class FakeChain:
    """In-memory EVM: records self-sent anchor txs and mines them immediately."""
    chain_id = 262144
    address = WALLET

    def __init__(self, mine=True):
        self.txs, self.mine, self._n = {}, mine, itertools.count(1)

    def send_data(self, data_hex):
        n = next(self._n)
        tx = "0x" + f"{n:064x}"
        self.txs[tx] = {"from": self.address, "to": self.address, "input": data_hex, "block": 1000 + n}
        return tx

    def receipt(self, tx):
        t = self.txs.get(tx)
        return {"status": "0x1", "blockNumber": hex(t["block"])} if t and self.mine else None

    def transaction(self, tx):
        t = self.txs.get(tx)
        return {"from": t["from"], "to": t["to"], "input": t["input"]} if t else None

    def block_timestamp(self, n):
        return 1_760_000_000 + n

    def latest_block(self):
        return 1234

    def balance_wei(self):
        return 10**21


@pytest.fixture
def store(tmp_path):
    return AnchorStore(str(tmp_path / "a.db"))


def test_merkle_proofs_all_sizes():
    for n in (1, 2, 3, 5, 8, 13, 100):
        leaves = [h(str(i)) for i in range(n)]
        root, proofs = merkle.build(leaves)
        for leaf in leaves:
            assert merkle.root_from_proof(leaf, proofs[leaf]) == root
        assert merkle.root_from_proof(h("not-in-tree"), proofs[leaves[0]]) != root or n == 0
    assert merkle.root_from_calldata(merkle.calldata(root)) == root
    assert merkle.root_from_calldata("0xdeadbeef") is None
    with pytest.raises(ValueError):
        merkle.norm_hash("xyz")


def test_anchor_then_verify(store, monkeypatch):
    monkeypatch.setenv("ANCHOR_ALLOW_LOCAL", "1")
    chain = FakeChain()
    docs = [h("report v1"), h("model card"), h("dataset.csv")]

    async def go():
        async with Client(build_server(Settings(), chain, store, receipt_timeout=1)) as c:
            st = (await c.call_tool("anchor_status", {})).structured_content
            assert st["anchor_wallet"] == WALLET and st["chain_id"] == 262144
            ht = (await c.call_tool("anchor_hash_text", {"text": "report v1"})).structured_content
            assert ht["sha256"] == docs[0]

            r = (await c.call_tool("anchor_hashes", {"hashes": docs, "label": "test"})).structured_content
            assert r["status"] == "confirmed" and len(r["receipts"]) == 3 and r["block_time"]
            onchain = chain.txs[r["tx_hash"]]["input"]
            assert onchain.startswith("0x5052564101") and merkle.root_from_calldata(onchain) == r["merkle_root"]

            v = (await c.call_tool("anchor_verify", {"hash": docs[1]})).structured_content
            assert v["verified"] and v["by_privi_anchor_service"] and v["block_number"] == r["block_number"]

            rc = next(x for x in r["receipts"] if x["hash"] == docs[2])  # trustless path: receipt only
            v2 = (await c.call_tool("anchor_verify", {"hash": docs[2], "tx_hash": rc["tx_hash"], "proof": rc["proof"]})).structured_content
            assert v2["verified"]

            bad = (await c.call_tool("anchor_verify", {"hash": h("forged"), "tx_hash": rc["tx_hash"], "proof": rc["proof"]})).structured_content
            assert bad["verified"] is False and "not part" in bad["reason"]
            none = (await c.call_tool("anchor_verify", {"hash": h("never anchored")})).structured_content
            assert none["verified"] is False
    anyio.run(go)


def test_pending_then_confirmed(store, monkeypatch):
    monkeypatch.setenv("ANCHOR_ALLOW_LOCAL", "1")
    chain = FakeChain(mine=False)

    async def go():
        async with Client(build_server(Settings(), chain, store, receipt_timeout=0.2)) as c:
            r = (await c.call_tool("anchor_hashes", {"hashes": [h("a")]})).structured_content
            assert r["status"] == "pending"
            v = (await c.call_tool("anchor_verify", {"hash": h("a")})).structured_content
            assert v["verified"] is False and v["status"] == "pending"
            chain.mine = True
            v = (await c.call_tool("anchor_verify", {"hash": h("a")})).structured_content
            assert v["verified"] is True
            assert store.find_leaf(h("a"))["status"] == "confirmed"
    anyio.run(go)


def test_auth_limits_and_validation(store, monkeypatch):
    chain = FakeChain()

    async def call(args, local):
        if local:
            monkeypatch.setenv("ANCHOR_ALLOW_LOCAL", "1")
        else:
            monkeypatch.delenv("ANCHOR_ALLOW_LOCAL", raising=False)
        async with Client(build_server(Settings(rate_per_min=2), chain, store, receipt_timeout=1)) as c:
            return await c.call_tool("anchor_hashes", args)

    assert anyio.run(call, {"hashes": [h("x")]}, False).is_error            # no key
    assert anyio.run(call, {"hashes": ["nothex"]}, True).is_error           # bad hash
    assert anyio.run(call, {"hashes": [h(str(i)) for i in range(101)]}, True).is_error  # too many
    assert not chain.txs  # nothing was sent for rejected calls


def test_eth_account_signing_roundtrip():
    """Runs where eth-account is installed (CI): the raw tx we broadcast recovers to our wallet."""
    eth_account = pytest.importorskip("eth_account")
    from privi_anchor.chain import JsonRpcChain

    key = "0x" + "11" * 32
    c = JsonRpcChain("http://unused", 262144, key)
    sent = {}
    canned = {"eth_getTransactionCount": "0x5", "eth_gasPrice": "0x3b9aca00", "eth_estimateGas": "0x5600"}

    def fake_rpc(method, params):
        if method == "eth_sendRawTransaction":
            sent["raw"] = params[0]
            return "0x" + "ab" * 32
        return canned[method]

    c._rpc = fake_rpc
    data = merkle.calldata(h("doc"))
    assert c.send_data(data) == "0x" + "ab" * 32
    assert eth_account.Account.recover_transaction(sent["raw"]) == c.address
    assert sent["raw"].startswith("0x") and data[2:] in sent["raw"]


def test_nonce_tracking_survives_stale_pending_count():
    """Some RPC nodes report a stale 'pending' nonce right after a send; the client must not reuse it."""
    from privi_anchor.chain import JsonRpcChain, RpcError

    c = JsonRpcChain.__new__(JsonRpcChain)
    import threading
    c._lock, c._id, c._next_nonce, c.address, c.chain_id = threading.Lock(), 0, None, "0xabc", 1
    used, sent = set(), []

    def rpc(method, params):
        if method == "eth_getTransactionCount":
            return hex(5)                          # node never catches up
        if method == "eth_gasPrice":
            return hex(10)
        if method == "eth_estimateGas":
            return hex(21000)
        n = int(params[0])
        if n in used:
            raise RpcError("eth_sendRawTransaction: replacement transaction underpriced")
        used.add(n)
        sent.append(n)
        return f"0xtx{n}"

    c._rpc = rpc
    c._sign = lambda nonce, gp, gas, data: str(nonce)
    assert [c.send_data("0x01") for _ in range(3)] == ["0xtx5", "0xtx6", "0xtx7"]
    used.add(8)                                    # someone else (an older process) took 8
    assert c.send_data("0x01") == "0xtx9"
    c._rpc = lambda m, p: (_ for _ in ()).throw(RpcError("eth_sendRawTransaction: insufficient funds")) \
        if m == "eth_sendRawTransaction" else rpc(m, p)
    try:
        c.send_data("0x01")
        assert False
    except RpcError as e:
        assert "insufficient" in str(e)


def test_public_status_and_health_cors(store, monkeypatch):
    from starlette.testclient import TestClient
    s = build_server(Settings(), None, store)
    app = s.streamable_http_app(host="0.0.0.0", stateless_http=True, json_response=True)
    with TestClient(app) as http:
        h = http.get("/health")
        assert h.headers["access-control-allow-origin"] == "*"
        st = http.get("/status").json()
        assert st["service"] == "privi-anchor" and st["anchoring_enabled"] is False and "last_confirmed_block_time" in st


def test_server_card(store):
    from starlette.testclient import TestClient
    s = build_server(Settings(), None, store)
    with TestClient(s.streamable_http_app(host="0.0.0.0", stateless_http=True, json_response=True)) as http:
        card = http.get("/.well-known/mcp/server-card.json").json()
        assert card["serverInfo"]["name"] == "privi-anchor" and any(t["name"] == "anchor_verify" for t in card["tools"])
