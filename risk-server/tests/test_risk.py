# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Risk - https://priviflow.us - dariocanoy@priviflow.us
import copy

import anyio
import numpy as np
import pytest
from mcp import Client

from privi_risk import market, risk
from privi_risk.anchoring import anchor_pending
from privi_risk.attest import Attestor
from privi_risk.config import PaySettings, Settings
from privi_risk.server import build_server

PAY_TO = "0x1990589FD200E043b8C6FD9ec5956c61b3071048"


def candles(n=120, start=60000.0, vol=0.03, seed=1):
    rng = np.random.default_rng(seed)
    closes = start * np.exp(np.cumsum(rng.normal(0, vol, n)))
    t0 = 1_700_000_000
    # Coinbase order: newest first, [time, low, high, open, close, volume]
    return [[t0 + 86400 * i, c * 0.98, c * 1.02, c, c, 10.0] for i, c in enumerate(closes)][::-1]


class FakeFacilitator:
    def __init__(self):
        self.calls = []

    async def verify(self, payload, req):
        self.calls.append("verify")
        return {"isValid": True, "payer": "0xabc"}

    async def settle(self, payload, req):
        self.calls.append("settle")
        return {"success": True, "transaction": "0x" + "cd" * 32, "network": req["network"], "payer": "0xabc"}


class FakeAnchor:
    def __init__(self):
        self.anchored = set()

    def anchor(self, hashes, label):
        self.anchored |= set(hashes)
        return {"status": "confirmed", "tx_hash": "0x" + "ab" * 32, "merkle_root": "00" * 32, "chain_id": 262144,
                "receipts": [{"hash": h, "proof": []} for h in hashes]}

    def verify(self, hash_hex, tx_hash, proof):
        return {"verified": hash_hex in self.anchored, "block_number": 9}


def payment_for(req):
    return {"x402Version": 2, "accepted": req["accepts"][0], "payload": {"signature": "0xsig"}}


def test_position_size_math():
    p = risk.position_size(10000, 100, 95, 1, "long", fee_pct=0)
    assert abs(p["units"] - 20) < 1e-9 and p["risk_usd"] == 100 and p["targets"]["2R"] == 110
    s = risk.position_size(10000, 100, 105, 2, "short", fee_pct=0)
    assert abs(s["units"] - 40) < 1e-9 and s["targets"]["1R"] == 95
    f = risk.position_size(10000, 100, 95, 1, "long", fee_pct=0.1)
    assert f["units"] < 20  # fees shrink the size so total loss stays at 1%
    assert abs(f["units"] * (5 + 0.001 * 195) - 100) < 1e-6


def test_liquidation_before_stop_is_caught():
    bad = risk.position_size(10000, 60000, 58800, 1, "long", leverage=50)
    assert bad["liquidation_before_stop"] and abs(bad["liquidation_price"] - 59100) < 1e-6
    ok = risk.position_size(10000, 60000, 58800, 1, "long", leverage=10)
    assert not ok["liquidation_before_stop"]
    short = risk.position_size(10000, 60000, 61500, 1, "short", leverage=50)
    assert short["liquidation_before_stop"]
    assert risk.verdict(10000, bad, None, None)["decision"] == "NO-TRADE"


def test_bad_inputs():
    for args in [(0, 100, 95), (10000, 100, 105), (10000, -1, 95), (10000, 100, 95, 150)]:
        with pytest.raises(risk.RiskError):
            risk.position_size(*args)
    with pytest.raises(risk.RiskError):
        risk.position_size(10000, 100, 105, 1, "long")
    with pytest.raises(risk.RiskError):
        risk.risk_of_ruin(0.5, 2, 1, 100)          # one loss wipes the account


def test_risk_of_ruin_and_kelly():
    r = risk.risk_of_ruin(0.45, 2.0, 1.0, 1.0, 200)
    assert abs(r["kelly_risk_pct"] - 17.5) < 1e-9 and r["expectancy_r_per_trade"] == 0.35
    hi = risk.risk_of_ruin(0.45, 2.0, 1.0, 10.0, 200)
    assert hi["probability_of_ruin"] > r["probability_of_ruin"]
    assert r["max_safe_risk_pct"] is not None and 0.5 < r["max_safe_risk_pct"] < 10
    neg = risk.risk_of_ruin(55, 0.5, 1.0, 1, 100)   # percent form accepted
    assert neg["expectancy_r_per_trade"] < 0 and neg["max_safe_risk_pct"] is None
    # max safe risk really keeps P(30% drawdown) at or under 5%
    s = risk.risk_of_ruin(0.45, 2.0, 1.0, r["max_safe_risk_pct"], 200)
    assert s["probability_drawdown_at_least_limit"] <= 0.05


def test_market_risk_and_fetch():
    rows = candles()
    data = market.fetch_candles("btc/usd", "1d", fetch=lambda url: rows)
    assert data["symbol"] == "BTC-USD"
    assert data["closes"] == [r[4] for r in rows[::-1]]  # Coinbase sends newest first; we return oldest first
    m = risk.market_risk(data["closes"], data["highs"], data["lows"], 10000)
    assert 0 < m["value_at_risk_pct"]["95"] < m["value_at_risk_pct"]["99"] <= m["expected_shortfall_pct"]["99"]
    assert 30 < m["volatility_annualized_pct"] < 90 and m["atr_method"] == "true range"
    with pytest.raises(market.MarketError):
        market.normalize_symbol("not a symbol!!")
    with pytest.raises(risk.RiskError):
        risk.market_risk([1, 2, 3])


def test_attestation_tamper(tmp_path):
    a = Attestor(str(tmp_path / "r.db"))
    k = a.public_keys()
    att = a.issue("pretrade_risk_report", {"verdict": {"decision": "GO"}})
    assert att["id"].startswith("rr_") and Attestor.verify(att, k["ed25519"], k["ml_dsa_87"])["valid"]
    forged = copy.deepcopy(att); forged["body"]["verdict"]["decision"] = "NO-TRADE"
    assert not Attestor.verify(forged, k["ed25519"], k["ml_dsa_87"])["valid"]


def _settings(tmp_path, **pay):
    p = PaySettings(network_key="base-sepolia", pay_to=PAY_TO, facilitator_url="https://x402.org/facilitator", **pay)
    return Settings(db_path=str(tmp_path / "r.db"), pay=p, rate_per_min=1000)


def test_mcp_free_and_paid_flow(tmp_path):
    fac, anchor, rows = FakeFacilitator(), FakeAnchor(), candles()
    s = _settings(tmp_path)
    att = Attestor(s.db_path)

    async def go():
        async with Client(build_server(s, att, anchor, fac, fetch=lambda url: rows)) as c:
            st = (await c.call_tool("risk_status", {})).structured_content
            assert st["paid_tools"]["risk_pretrade_report"]["accepting_payments"]
            ps = (await c.call_tool("risk_position_size", {"account": 10000, "entry": 60000, "stop": 58800,
                                                           "leverage": 50})).structured_content
            assert ps["liquidation_before_stop"]
            rr = (await c.call_tool("risk_of_ruin", {"win_rate": 0.45, "avg_win_r": 2})).structured_content
            assert rr["kelly_risk_pct"] == 17.5
            mk = (await c.call_tool("risk_market_check", {"symbol": "BTC-USD", "position_usd": 5000})).structured_content
            assert mk["symbol"] == "BTC-USD" and mk["value_at_risk_usd"]["99"] > 0

            args = {"account": 10000, "entry": 60000, "stop": 58200, "side": "long", "risk_pct": 1,
                    "leverage": 5, "symbol": "BTC-USD", "win_rate": 0.45, "avg_win_r": 2, "label": "test"}
            req = await c.call_tool("risk_pretrade_report", args)          # no payment -> 402 body
            assert req.is_error and req.structured_content["accepts"][0]["amount"] == "100000"
            assert fac.calls == []
            bad = await c.call_tool("risk_pretrade_report", {**args, "stop": 61000})   # invalid -> no charge
            assert bad.is_error and "stop" in bad.structured_content["error"] and fac.calls == []
            paid = await c.call_tool("risk_pretrade_report", args, meta={"x402/payment": payment_for(req.structured_content)})
            assert not paid.is_error and fac.calls == ["verify", "settle"]
            assert paid.meta["x402/payment-response"]["success"]
            rep = paid.structured_content
            assert rep["verdict"]["decision"] in ("GO", "REDUCE", "NO-TRADE") and rep["report_id"].startswith("rr_")
            v = (await c.call_tool("risk_verify", {"report_id": rep["report_id"]})).structured_content
            assert v["valid"] and v["anchor"]["verified"] is False
            assert anchor_pending(att, anchor) == 1
            v = (await c.call_tool("risk_verify", {"report_id": rep["report_id"]})).structured_content
            assert v["valid"] and v["anchor"]["verified"] is True
    anyio.run(go)


def test_paid_tool_closed_without_payment_setup(tmp_path):
    s = Settings(db_path=str(tmp_path / "r.db"), pay=PaySettings(pay_to=""))   # mainnet, no wallet, no CDP keys

    async def go():
        async with Client(build_server(s, Attestor(s.db_path), None, FakeFacilitator())) as c:
            r = await c.call_tool("risk_pretrade_report", {"account": 1000, "entry": 10, "stop": 9, "side": "long"})
            assert r.is_error and "not open yet" in r.structured_content["error"]
            ok = await c.call_tool("risk_position_size", {"account": 1000, "entry": 10, "stop": 9})
            assert not ok.is_error
    anyio.run(go)
