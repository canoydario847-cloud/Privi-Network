"""Privi Guard: wallet policies, transaction scan, owner approval, escrow, agent registry."""

import anyio
import pytest
from mcp import Client

from privi_ledger.config import Settings
from privi_ledger.guard import UNLIMITED, decode, escrow_digest, selector
from privi_ledger.kya import keccak256, recover_address
from privi_ledger.server import build_server
from privi_ledger.store import Ledger

from test_ledger import PAY_TO, FakeFacilitator, _eth_wallet, as_org

USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"


class FakeRpc:
    def __init__(self, contracts=(), revert=False):
        self.urls = {8453: "fake"}
        self.contracts = {c.lower() for c in contracts}
        self.revert = revert

    def is_contract(self, chain_id, address):
        return address.lower() in self.contracts

    def simulate(self, chain_id, tx):
        if self.revert:
            return {"simulated": True, "reverts": True, "revert_reason": "execution reverted: insufficient balance"}
        return {"simulated": True, "reverts": False, "return_data": "0x01"}


class FakeAnchor:
    def __init__(self):
        self.calls = 0

    def anchor(self, hashes, label):
        self.calls += 1
        return {"tx_hash": "0x" + "cd" * 32, "merkle_root": hashes[0], "block_number": 100 + self.calls,
                "chain_id": 262144, "status": "confirmed",
                "receipts": [{"hash": h, "proof": []} for h in hashes]}

    def verify(self, h, tx, proof):
        return {"verified": True, "block_number": 101}


@pytest.fixture
def ledger(tmp_path):
    return Ledger(str(tmp_path / "g.db"))


def word(x) -> str:
    if isinstance(x, str):
        return x.lower().removeprefix("0x").rjust(64, "0")
    return f"{x:064x}"


def calldata(sig, *args) -> str:
    return "0x" + selector(sig) + "".join(word(a) for a in args)


def make(ledger, monkeypatch, rpc=None, anchor=None):
    srv = build_server(Settings(pay_to=PAY_TO), ledger, FakeFacilitator(), anchor, rpc or FakeRpc())

    def call(key, name, args):
        as_org(monkeypatch, key)

        async def go():
            async with Client(srv) as c:
                return await c.call_tool(name, args)
        return anyio.run(go)
    return srv, call


def bind(call, key, stream="treasury-agent"):
    addr, sign = _eth_wallet()
    ch = call(key, "kya_challenge", {"address": addr}).structured_content
    b = call(key, "kya_bind_wallet", {"address": addr, "challenge_id": ch["challenge_id"],
                                      "signature": sign(ch["message"]), "stream_id": stream}).structured_content
    assert b["bound"], b
    return addr, sign


def test_decode_and_explain_known_patterns():
    spender = "0x" + "ab" * 20
    d = decode(bytes.fromhex(calldata("approve(address,uint256)", spender, 2 ** 256 - 1)[2:]))
    assert d["function"] == "approve" and d["args"][0].lower() == spender and d["args"][1] >= UNLIMITED
    assert selector("transfer(address,uint256)") == "a9059cbb"
    assert selector("approve(address,uint256)") == "095ea7b3"
    assert selector("setApprovalForAll(address,bool)") == "a22cb465"
    assert decode(bytes.fromhex("deadbeef"))["function"] == "unknown"


def test_preview_flags_drainer_patterns(ledger, monkeypatch):
    _, call = make(ledger, monkeypatch, FakeRpc(contracts=[USDC]))
    me, eoa = "0x" + "11" * 20, "0x" + "22" * 20
    r = call(None, "guard_tx_preview", {"tx": {"from": me, "to": USDC,
             "data": calldata("approve(address,uint256)", eoa, 2 ** 256 - 1)}}).structured_content
    codes = {x["code"] for x in r["risks"]}
    assert {"unlimited_approval", "approval_to_personal_wallet"} <= codes and r["risk_level"] == "high"
    assert "UNLIMITED" in r["summary"]
    nft = call(None, "guard_tx_preview", {"tx": {"from": me, "to": "0x" + "33" * 20,
               "data": calldata("setApprovalForAll(address,bool)", eoa, 1)}}).structured_content
    assert any(x["code"] == "nft_operator_grant" for x in nft["risks"])
    own = call(None, "guard_tx_preview", {"tx": {"from": me, "to": "0x" + "33" * 20,
               "data": calldata("transferOwnership(address)", eoa)}}).structured_content
    assert own["risk_level"] == "critical"
    plain = call(None, "guard_tx_preview", {"tx": {"from": me, "to": eoa, "value": str(10 ** 17)}}).structured_content
    assert plain["risks"] == [] and "0.1 native coin" in plain["summary"]
    assert call(None, "guard_tx_preview", {"tx": {"from": "nope", "to": eoa}}).is_error


def test_policy_allow_block_and_owner_approval(ledger, monkeypatch):
    acme = ledger.create_org("Acme")
    _, call = make(ledger, monkeypatch)
    key = acme["api_key"]
    wallet, wsign = bind(call, key)
    owner, osign = _eth_wallet()
    to = "0x" + "44" * 20

    # no policy -> block
    r0 = call(key, "guard_check_tx", {"tx": {"from": wallet, "to": to, "value": "1"}, "usd_value": 1}).structured_content
    assert r0["verdict"] == "block" and "guard_policy_set" in r0["reasons"][0]

    # policy needs a bound wallet and a different owner
    assert call(key, "guard_policy_set", {"wallet": "0x" + "55" * 20, "owner_address": owner,
                                          "max_tx_usd": 500, "daily_cap_usd": 1000}).is_error
    assert call(key, "guard_policy_set", {"wallet": wallet, "owner_address": wallet,
                                          "max_tx_usd": 500, "daily_cap_usd": 1000}).is_error
    p = call(key, "guard_policy_set", {"wallet": wallet, "owner_address": owner, "max_tx_usd": 500,
                                       "daily_cap_usd": 600, "approval_above_usd": 100}).structured_content
    assert p["policy"]["approval_above_usd"] == "100" and p["recorded"]

    # small payment -> allow with signed attestation, counts toward the cap
    tx = {"from": wallet, "to": USDC, "data": calldata("transfer(address,uint256)", to, 50 * 10 ** 6)}
    a = call(key, "guard_check_tx", {"tx": tx, "usd_value": 50, "purpose": "pay invoice 7"}).structured_content
    assert a["verdict"] == "allow" and a["guard_attestation"]["body"]["verdict"] == "allow"
    assert len(a["guard_attestation"]["signature"]) == 128 and a["recorded_in_your_log"]["stream_id"] == "treasury-agent"

    # over per-tx limit -> block; missing usd on a value move -> needs approval
    assert call(key, "guard_check_tx", {"tx": tx, "usd_value": 900}).structured_content["verdict"] == "block"
    assert call(key, "guard_check_tx", {"tx": tx}).structured_content["verdict"] == "needs_approval"

    # unlimited approval is blocked by default policy
    ap = {"from": wallet, "to": USDC, "data": calldata("approve(address,uint256)", to, 2 ** 256 - 1)}
    assert call(key, "guard_check_tx", {"tx": ap, "usd_value": 1}).structured_content["verdict"] == "block"

    # $300 -> needs owner approval
    big = {"from": wallet, "to": USDC, "data": calldata("transfer(address,uint256)", to, 300 * 10 ** 6)}
    n = call(key, "guard_check_tx", {"tx": big, "usd_value": 300}).structured_content
    assert n["verdict"] == "needs_approval"
    apr = n["approval"]
    assert apr["approval_id"].startswith("apr_") and "/guard/approvals/" in apr["approve_url"]
    # same tx again reuses the pending approval
    assert call(key, "guard_check_tx", {"tx": big, "usd_value": 300}).structured_content["approval"]["approval_id"] == apr["approval_id"]

    # the agent cannot approve itself; using a pending approval does not pass
    assert call(None, "guard_approve", {"approval_id": apr["approval_id"], "decision": "approve",
                                        "signature": wsign(apr["message_to_sign"])}).is_error
    still = call(key, "guard_check_tx", {"tx": big, "usd_value": 300, "approval_id": apr["approval_id"]}).structured_content
    assert still["verdict"] == "block" and "pending" in still["reasons"][0]

    # owner approves -> allow once; approval for a different tx is refused
    d = call(None, "guard_approve", {"approval_id": apr["approval_id"], "decision": "approve",
                                     "signature": osign(apr["message_to_sign"])}).structured_content
    assert d["status"] == "approved" and d["signed_by"].lower() == owner.lower()
    other = dict(big, data=calldata("transfer(address,uint256)", to, 301 * 10 ** 6))
    assert call(key, "guard_check_tx", {"tx": other, "usd_value": 300, "approval_id": apr["approval_id"]}).structured_content["verdict"] == "block"
    ok = call(key, "guard_check_tx", {"tx": big, "usd_value": 300, "approval_id": apr["approval_id"]}).structured_content
    assert ok["verdict"] == "allow"
    again = call(key, "guard_check_tx", {"tx": big, "usd_value": 300, "approval_id": apr["approval_id"]}).structured_content
    assert again["verdict"] == "block"   # used, and $50 + $300 + $300 is over the $600 daily cap anyway

    # daily cap
    pol = call(key, "guard_policies", {}).structured_content["policies"][0]
    assert pol["spent_24h_usd"] == "350"
    cap = call(key, "guard_check_tx", {"tx": tx, "usd_value": 260}).structured_content
    assert cap["verdict"] == "block" and any("daily cap" in r for r in cap["reasons"])

    # kill switch
    call(key, "guard_policy_set", {"wallet": wallet, "owner_address": owner, "max_tx_usd": 500,
                                   "daily_cap_usd": 600, "active": False})
    assert "paused" in call(key, "guard_check_tx", {"tx": tx, "usd_value": 1}).structured_content["reasons"][0]
    assert len(call(key, "guard_approvals", {}).structured_content["approvals"]) == 2   # the no-usd check also asked

    # every decision is in the tamper-evident log
    log = call(key, "ledger_read_stream", {"stream_id": "treasury-agent"}).structured_content
    assert log["integrity"]["intact"] and len(log["entries"]) >= 8


def test_simulation_revert_needs_approval(ledger, monkeypatch):
    acme = ledger.create_org("Acme")
    _, call = make(ledger, monkeypatch, FakeRpc(revert=True))
    wallet, _ = bind(call, acme["api_key"])
    owner, _ = _eth_wallet()
    call(acme["api_key"], "guard_policy_set", {"wallet": wallet, "owner_address": owner, "max_tx_usd": 100, "daily_cap_usd": 100})
    r = call(acme["api_key"], "guard_check_tx", {"tx": {"from": wallet, "to": "0x" + "66" * 20, "value": "5"},
                                                 "usd_value": 1}).structured_content
    assert r["verdict"] == "needs_approval" and any("fails" in x for x in r["reasons"])


def test_escrow_between_two_companies(ledger, monkeypatch):
    acme, mill = ledger.create_org("Acme"), ledger.create_org("Mill")
    _, call = make(ledger, monkeypatch)
    payer, _ = bind(call, acme["api_key"])
    payee, _ = bind(call, mill["api_key"], "sales-agent")
    o = call(acme["api_key"], "guard_escrow_open", {"payee_org_id": mill["org_id"], "amount": "250.5",
              "payer_wallet": payer, "payee_wallet": payee, "terms": "Deliver lot 42 traceability report"}).structured_content
    eid = o["escrow_id"]
    assert o["status"] == "offered" and o["terms"]["amount_atomic"] == "250500000" and o["terms"]["token"] == USDC
    assert call(acme["api_key"], "guard_escrow_act", {"escrow_id": eid, "action": "release"}).is_error   # not accepted yet
    assert call(mill["api_key"], "guard_escrow_act", {"escrow_id": eid, "action": "release"}).is_error   # payee can't release
    assert call(mill["api_key"], "guard_escrow_act", {"escrow_id": eid, "action": "accept"}).structured_content["status"] == "accepted"
    assert call(acme["api_key"], "guard_escrow_act", {"escrow_id": eid, "action": "refund"}).is_error   # before deadline
    call(mill["api_key"], "guard_escrow_act", {"escrow_id": eid, "action": "deliver", "note": "report sent, hash abc"})
    r = call(acme["api_key"], "guard_escrow_act", {"escrow_id": eid, "action": "release"}).structured_content
    assert r["status"] == "released"
    auth = r["authorization"]
    # the arbiter signature recovers to the arbiter over the same digest the contract computes
    dg = escrow_digest(8453, auth["escrow_contract"], eid, "release", payee, 250500000)
    assert "0x" + dg.hex() == auth["digest"]
    h = keccak256(b"\x19Ethereum Signed Message:\n32" + dg)
    assert recover_address(h, bytes.fromhex(auth["arbiter_signature"][2:])).lower() == auth["arbiter"].lower()
    pub = call(None, "guard_escrow_status", {"escrow_id": eid}).structured_content
    assert pub["status"] == "released" and all("note" not in e for e in pub["events"])
    assert len(call(mill["api_key"], "guard_escrows", {}).structured_content["escrows"]) == 1
    # outsiders cannot act
    other = ledger.create_org("Other")
    assert call(other["api_key"], "guard_escrow_act", {"escrow_id": eid, "action": "dispute"}).is_error


def test_registry_register_lookup_verify(ledger, monkeypatch):
    acme = ledger.create_org("Acme")
    for i in range(6):
        ledger.record(acme["org_id"], "treasury-agent", "claude", "payment", f"p{i}")
    anchor = FakeAnchor()
    _, call = make(ledger, monkeypatch, anchor=anchor)
    key = acme["api_key"]
    wallet, _ = bind(call, key)
    call(key, "passport_issue", {"stream_id": "treasury-agent"})
    r = call(key, "registry_register", {"stream_id": "treasury-agent", "name": "Acme Treasury",
             "description": "Pays suppliers in USDC", "endpoint": "https://acme.example/mcp",
             "capabilities": ["payments", "invoicing"]}).structured_content
    agent = r["agent"]
    assert r["registered"] and agent["agent_id"].startswith("agt_") and agent["wallets"][0].lower() == wallet.lower()
    assert agent["passport_id"] and r["attestation"]["anchored"] and agent["record_version"] == 1
    v2 = call(key, "registry_register", {"stream_id": "treasury-agent", "name": "Acme Treasury v2"}).structured_content
    assert v2["agent"]["agent_id"] == agent["agent_id"] and v2["agent"]["record_version"] == 2
    found = call(None, "registry_lookup", {"address": wallet}).structured_content
    assert found["agents"][0]["agent"]["name"] == "Acme Treasury v2" and found["total_registered"] == 1
    assert call(None, "registry_lookup", {"capability": "nothing"}).structured_content["agents"] == []
    ver = call(None, "registry_verify", {"agent_id": agent["agent_id"]}).structured_content
    assert ver["valid"] and ver["signature_valid"] and ver["onchain_verified"]
    assert call(key, "registry_remove", {"agent_id": agent["agent_id"]}).structured_content["revoked"]
    assert call(None, "registry_verify", {"agent_id": agent["agent_id"]}).structured_content["valid"] is False


def test_guard_http_routes(ledger, monkeypatch):
    from starlette.testclient import TestClient
    acme = ledger.create_org("Acme")
    srv, call = make(ledger, monkeypatch)
    wallet, _ = bind(call, acme["api_key"])
    owner, osign = _eth_wallet()
    call(acme["api_key"], "guard_policy_set", {"wallet": wallet, "owner_address": owner, "max_tx_usd": 1000,
                                               "daily_cap_usd": 1000, "approval_above_usd": 10})
    n = call(acme["api_key"], "guard_check_tx", {"tx": {"from": wallet, "to": "0x" + "77" * 20, "value": "9"},
                                                 "usd_value": 50}).structured_content
    aid = n["approval"]["approval_id"]
    app = srv.streamable_http_app(stateless_http=True, json_response=True)
    with TestClient(app) as http:
        assert "Approve an AI agent transaction" in http.get(f"/guard/approvals/{aid}").text
        j = http.get(f"/guard/approvals/{aid}.json").json()
        assert j["status"] == "pending" and j["messages"]["approve"] == n["approval"]["message_to_sign"]
        assert http.post(f"/guard/approvals/{aid}/decide", json={"decision": "approve", "signature": "0x" + "00" * 65}).status_code == 400
        ok = http.post(f"/guard/approvals/{aid}/decide", json={"decision": "reject", "signature": osign(j["messages"]["reject"])})
        assert ok.json()["status"] == "rejected"
        wk = http.get("/.well-known/privi-guard.json").json()
        assert wk["arbiter_address"].startswith("0x") and "guard_check_tx" in wk["tools"]
        assert http.get("/registry").json()["total_registered"] == 0
        assert http.get("/registry/agt_nope").status_code == 404
