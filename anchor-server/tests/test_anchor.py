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
    chain_id = 8453  # Base
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
            assert st["anchor_wallet"] == WALLET and st["chain_id"] == 8453 and "Base" in st["network"]
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


def test_devnet_anchors_survive_move_to_base(tmp_path, monkeypatch):
    """Anchors made on the Privi devnet are reported honestly after the move, not as forgeries."""
    import sqlite3
    db = str(tmp_path / "old.db")
    old = sqlite3.connect(db)  # a pre-0.4 database: no chain_id column
    old.executescript("""
        CREATE TABLE batches (batch_id INTEGER PRIMARY KEY AUTOINCREMENT, root TEXT NOT NULL, tx_hash TEXT,
          status TEXT NOT NULL, block_number INTEGER, block_time INTEGER, label TEXT NOT NULL DEFAULT '',
          client TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, error TEXT);
        CREATE TABLE leaves (leaf TEXT NOT NULL, batch_id INTEGER NOT NULL, proof TEXT NOT NULL, PRIMARY KEY (leaf, batch_id));""")
    old.execute("INSERT INTO batches (root, tx_hash, status, block_number, block_time, created_at) VALUES (?, ?, 'confirmed', 58638, 1760900000, '2026-10-20T00:00:00+00:00')",
                (h("genesis"), "0x" + "ab" * 32))
    old.execute("INSERT INTO leaves VALUES (?, 1, '[]')", (h("genesis"),))
    old.commit()
    old.close()

    monkeypatch.setenv("ANCHOR_ALLOW_LOCAL", "1")
    store = AnchorStore(db, 8453)
    assert store.stats()["confirmed_batches"] == 0, "devnet anchors are not counted as Base anchors"
    assert store.confirmed_on_current_chain() == 0
    chain = FakeChain()

    async def go():
        async with Client(build_server(Settings(), chain, store, receipt_timeout=1)) as c:
            v = (await c.call_tool("anchor_verify", {"hash": h("genesis")})).structured_content
            assert v["verified"] is None and v["anchored_on_chain_id"] == 262144 and "Devnet" in v["reason"]
            assert v["block_number"] == 58638
            r = (await c.call_tool("anchor_hashes", {"hashes": [h("genesis")]})).structured_content
            assert r["status"] == "confirmed" and r["chain_id"] == 8453
            v = (await c.call_tool("anchor_verify", {"hash": h("genesis")})).structured_content
            assert v["verified"] is True and v["tx_link"].startswith("https://basescan.org/tx/")
    anyio.run(go)


def test_daily_gas_budget(store, monkeypatch):
    monkeypatch.setenv("ANCHOR_ALLOW_LOCAL", "1")
    chain = FakeChain()

    async def go():
        async with Client(build_server(Settings(max_tx_per_day=2), chain, store, receipt_timeout=1)) as c:
            for i in range(2):
                assert not (await c.call_tool("anchor_hashes", {"hashes": [h(f"d{i}")]})).is_error
            over = await c.call_tool("anchor_hashes", {"hashes": [h("d3")]})
            assert over.is_error and "budget" in over.structured_content["error"]
    anyio.run(go)
    assert len(chain.txs) == 2


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


def test_rpc_sends_user_agent(monkeypatch):
    """Public Base RPCs answer 403 to Python's default User-Agent; we must send our own."""
    import io
    import json as _json
    import urllib.request
    from privi_anchor import chain as chain_mod

    seen = {}

    def fake_urlopen(req, timeout=None):
        seen["ua"] = req.get_header("User-agent")
        return io.BytesIO(_json.dumps({"jsonrpc": "2.0", "id": 1, "result": "0x2105"}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    c = chain_mod.JsonRpcChain.__new__(chain_mod.JsonRpcChain)
    c.rpc_url, c.timeout, c._id = "https://mainnet.base.org", 5, 0
    assert c.remote_chain_id() == 8453
    assert seen["ua"].startswith("privi-anchor/") and "Python-urllib" not in seen["ua"]


def test_pending_batches_settle_in_background(store, monkeypatch):
    from privi_anchor.server import reconcile_pending
    monkeypatch.setenv("ANCHOR_ALLOW_LOCAL", "1")
    chain = FakeChain(mine=False)
    store.chain_id = chain.chain_id

    async def go():
        async with Client(build_server(Settings(), chain, store, receipt_timeout=0.2)) as c:
            r = (await c.call_tool("anchor_hashes", {"hashes": [h("late")]})).structured_content
            assert r["status"] == "pending"
    anyio.run(go)
    assert reconcile_pending(chain, store) == 0          # still not mined: stays pending
    assert store.find_leaf(h("late"))["status"] == "pending"
    chain.mine = True
    assert reconcile_pending(chain, store) == 1          # mined later: settled without anyone calling verify
    rec = store.find_leaf(h("late"))
    assert rec["status"] == "confirmed" and rec["block_number"] and rec["block_time"]
    assert reconcile_pending(chain, store) == 0
