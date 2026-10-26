"""PRIVI token payments and market checks, against a fake Base node shaped like the live chain."""
import anyio
import pytest

from privi_call import privi_token as pt
from privi_call.privi_token import PriviToken

PAY_TO = "0x1990589fd200e043b8c6fd9ec5956c61b3071048"
PAYER = "0x00000000000000000000000000000000000000aa"
NOW = 1_793_000_000


def word(n: int) -> str:
    return format(n, "x").rjust(64, "0")


def addr_word(a: str) -> str:
    return a.lower().removeprefix("0x").rjust(64, "0")


class FakeBase:
    """Answers the eth_call / receipt queries PriviToken makes. Desk state matches Oct 26, 2026 by default."""

    def __init__(self, desk_privi=0, desk_usdc=0, price=10**18, paused=0, base=pt.TOKEN, quote=pt.USDC):
        self.balances = {(pt.TOKEN, pt.DESK): desk_privi, (pt.USDC, pt.DESK): desk_usdc}
        self.desk = {"desk_price": price, "desk_scale": 10**18, "desk_paused": paused}
        self.addrs = {"desk_base": base, "desk_quote": quote, "desk_owner": PAY_TO}
        self.head = 1000
        self.txs = {}
        self.down = False

    def add_tx(self, tx, amount, to=PAY_TO, token=pt.TOKEN, block=990, status=1, ts=NOW - 60):
        self.txs[tx] = {"status": hex(status), "blockNumber": hex(block), "ts": ts, "logs": [
            {"address": token, "topics": [pt.TRANSFER_TOPIC, "0x" + addr_word(PAYER), "0x" + addr_word(to)],
             "data": "0x" + word(amount)}]}

    def __call__(self, method, params):
        if self.down:
            raise pt.RpcError("Base RPC unavailable: test")
        if method == "eth_call":
            to, data = params[0]["to"].lower(), params[0]["data"][2:]
            sel, args = data[:8], data[8:]
            if sel == pt.SEL["balanceOf"]:
                return "0x" + word(self.balances.get((to, "0x" + args[24:64]), 0))
            if to == pt.DESK:
                for k, v in self.desk.items():
                    if sel == pt.SEL[k]:
                        return "0x" + word(v)
                for k, v in self.addrs.items():
                    if sel == pt.SEL[k]:
                        return "0x" + addr_word(v)
            return "0x" + word(0)                       # factories: no PRIVI pools
        if method == "eth_getTransactionReceipt":
            t = self.txs.get(params[0])
            return t and {"status": t["status"], "blockNumber": t["blockNumber"], "logs": t["logs"]}
        if method == "eth_blockNumber":
            return hex(self.head)
        if method == "eth_getBlockByNumber":
            t = next(t for t in self.txs.values() if t["blockNumber"] == params[0])
            return {"timestamp": hex(t["ts"])}
        raise AssertionError(method)


def token(chain, **kw):
    return PriviToken(chain, PAY_TO, ":memory:", clock=lambda: NOW, cache_seconds=0, **kw)


def test_market_reads_live_shaped_desk():
    m = token(FakeBase()).market()
    assert m["ok"] and m["price_usd"] == "1" and m["price_source"] == "Privi swap desk"
    d = m["desk_state"]
    assert d["privi_available_to_buy"] == "0" and not d["can_buy_privi"] and not d["can_sell_privi"]
    assert m["pools"] == []


def test_desk_must_be_privi_usdc_and_rpc_errors_are_reported():
    bad = token(FakeBase(base="0x" + "11" * 20)).market()
    assert not bad["ok"] and "not PRIVI/USDC" in bad["error"] and bad["price_usd"] is None
    chain = FakeBase(); chain.down = True
    m = token(chain, manual_usd="0.05").market()
    assert not m["ok"] and m["price_usd"] == "0.05"          # a manual rate still works offline


def test_swap_quotes_are_capped_by_desk_liquidity():
    t = token(FakeBase(desk_privi=50 * 10**18, desk_usdc=10 * 10**6, price=2 * 10**18))   # 1 PRIVI = 2 USDC
    buy = t.swap_quote("buy", "20")
    assert buy["amount_out"] == "10 PRIVI" and buy["fillable"]
    too_big = t.swap_quote("buy", "200")
    assert not too_big["fillable"] and "needs more liquidity" in too_big["note"]
    sell = t.swap_quote("sell", "5")
    assert sell["amount_out"] == "10 USDC" and sell["fillable"]
    assert not t.swap_quote("sell", "6")["fillable"]
    assert not token(FakeBase(desk_privi=10**30, paused=1)).swap_quote("buy", "1")["fillable"]


def test_payment_quote_and_verification():
    chain = FakeBase()                               # desk price 1 USDC per PRIVI
    t = token(chain)
    q = t.quote_usd("29")
    assert q["amount_privi"] == "29" and q["payTo"] == PAY_TO and q["chainId"] == 8453
    good, short, wrong_to, other_token = ("0x" + c * 64 for c in "abcd")
    chain.add_tx(good, 29 * 10**18)
    chain.add_tx(short, 20 * 10**18)
    chain.add_tx(wrong_to, 29 * 10**18, to="0x" + "22" * 20)
    chain.add_tx(other_token, 29 * 10**18, token=pt.USDC)
    ok, rc = t.verify_payment({"tx_hash": good}, "ledger_upgrade_pro", "29")
    assert ok and rc["amount_privi"] == "29" and rc["payer"] == PAYER
    again = t.verify_payment({"tx_hash": good}, "ledger_upgrade_pro", "29")
    assert not again[0] and "already used" in again[1]["error"]
    assert "need 29" in t.verify_payment({"tx_hash": short}, "x", "29")[1]["error"]
    assert "no PRIVI transfer" in t.verify_payment({"tx_hash": wrong_to}, "x", "29")[1]["error"]
    assert "no PRIVI transfer" in t.verify_payment({"tx_hash": other_token}, "x", "29")[1]["error"]
    assert "tx_hash" in t.verify_payment({"tx_hash": "nope"}, "x", "29")[1]["error"]
    assert "not found" in t.verify_payment({"tx_hash": "0x" + "e" * 64}, "x", "29")[1]["error"]


def test_payment_needs_confirmations_success_and_freshness():
    chain = FakeBase()
    t = token(chain)
    fresh, failed, old = ("0x" + c * 64 for c in "123")
    chain.add_tx(fresh, 10**18, block=1000)
    chain.add_tx(failed, 10**18, block=980, status=0)
    chain.add_tx(old, 10**18, block=970, ts=NOW - 2 * 86400)
    assert "confirmations" in t.verify_payment(fresh, "x", "1")[1]["error"]
    chain.head = 1001
    assert t.verify_payment(fresh, "x", "1")[0]
    assert "failed" in t.verify_payment(failed, "x", "1")[1]["error"]
    assert "older than 24 hours" in t.verify_payment(old, "x", "1")[1]["error"]


def test_disabled_without_pay_to_or_price():
    assert PriviToken(FakeBase(), "", ":memory:").quote_usd("1") is None
    assert token(FakeBase(price=0)).quote_usd("1") is None
    assert token(FakeBase(), enabled=False).verify_payment("0x" + "a" * 64, "x", "1")[0] is False


def test_paywall_offers_and_accepts_privi(tmp_path):
    from privi_call.config import Settings
    from privi_call.x402 import Paywall

    class NoFacilitator:
        async def verify(self, *a):
            raise AssertionError("USDC facilitator must not be used for a PRIVI payment")
        settle = verify

    settings = Settings(pay_to=PAY_TO)
    tool = sorted(settings.prices_usd)[0]
    chain = FakeBase()
    paid = "0x" + "f" * 64
    chain.add_tx(paid, 10**24)                       # 1,000,000 PRIVI covers any tool price at $1/PRIVI
    pw = Paywall(settings, NoFacilitator(), privi=PriviToken(chain, PAY_TO, str(tmp_path / "p.db"),
                                                              clock=lambda: NOW, cache_seconds=0))

    async def work():
        return {"ok": True}

    async def flow():
        unpaid = await pw.run(tool, "test", {}, work)
        assert unpaid.is_error and unpaid.structured_content["privi"]["usd"] == str(settings.prices_usd[tool])
        ok = await pw.run(tool, "test", {"privi/payment": {"tx_hash": paid}}, work)
        assert not ok.is_error and ok.meta["privi/receipt"]["transaction"] == paid
        replay = await pw.run(tool, "test", {"privi/payment": {"tx_hash": paid}}, work)
        assert replay.is_error and "already used" in replay.structured_content["error"]
    anyio.run(flow)
