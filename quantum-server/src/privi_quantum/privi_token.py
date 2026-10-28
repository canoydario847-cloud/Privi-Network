# Copyright (c) 2026 Privi World Co. All rights reserved.
"""PRIVI token payments and market checks (Base mainnet).

Identical copies live in Privi Verify, Ledger and Call. Read-only toward the chain: this module never
signs or sends a transaction. It

* reads the Privi swap desk (fixed-price PRIVI <-> USDC contract) for the PRIVI price and how much
  PRIVI / USDC it holds, and also looks for PRIVI pools on Uniswap v3 and Aerodrome;
* quotes a swap at the desk price, capped by what the desk can actually fill;
* turns a USD tool price into a PRIVI amount, and verifies a customer's PRIVI payment from the
  Transfer event in its transaction receipt (right token, right recipient, enough PRIVI, confirmed,
  recent, never used before).

Env: PRIVI_TOKEN, PRIVI_DESK, PRIVI_RPC_URL, PRIVI_PAY_TO (defaults to the service's x402 pay_to),
PRIVI_USD_RATE (optional manual price; otherwise the desk price), PRIVI_PAYMENTS=0 to turn PRIVI off.
"""
from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import threading
import time
import urllib.request
from decimal import Decimal
from typing import Annotated, Any, Callable

from mcp_types import ToolAnnotations
from pydantic import Field

TOKEN = "0xa11626baf87524e61b5697634c7ec48d26279d6c"      # PRIVI (ERC-20, 18 decimals)
DESK = "0x59d0fd923242e30e48c0d5486410c3c4039785e1"       # Privi swap desk (owner 0x1990…1048)
USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
WETH = "0x4200000000000000000000000000000000000006"
UNI_V3_FACTORY = "0x33128a8fc17869897dce68ed026d694621f6fdfd"
AERO_FACTORY = "0x420dd381b31aef6683db6b902084cb0ffece40da"
CHAIN_ID = 8453
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
PAYMENT_META_KEY = "privi/payment"
RECEIPT_META_KEY = "privi/receipt"

# function selectors (keccak-256, checked against known vectors)
SEL = {
    "balanceOf": "70a08231", "decimals": "313ce567",
    "desk_price": "10bace8c", "desk_scale": "c2ee3a08", "desk_base": "cbd11194", "desk_quote": "11eac855",
    "desk_paused": "5c975abb", "desk_owner": "8da5cb5b",
    "uni_getPool": "1698ee82", "uni_liquidity": "1a686502", "uni_slot0": "3850c7bd", "uni_token0": "0dfe1681",
    "aero_getPool": "79bc57d5", "aero_reserves": "0902f1ac",
}
TOLERANCE = Decimal("0.98")      # accept payments within 2% of the quote (price can move between quote and pay)
MIN_CONFIRMATIONS = 2
MAX_AGE_SECONDS = 24 * 3600


def _addr(a: str) -> str:
    return a.lower().removeprefix("0x").rjust(64, "0")


def _dec(d: Decimal) -> str:
    """Plain decimal text (10, not 1E+1)."""
    return format(d.normalize(), "f")


def _u(n: int) -> str:
    return format(n, "x").rjust(64, "0")


class RpcError(Exception):
    pass


class Rpc:
    def __init__(self, url: str, timeout: float = 10.0):
        self.url, self.timeout = url, timeout

    def __call__(self, method: str, params: list) -> Any:
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
        req = urllib.request.Request(self.url, data=body, headers={"content-type": "application/json",
                                                                    "user-agent": "privi-token/1"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                j = json.loads(r.read())
        except Exception as ex:  # network, HTTP, JSON
            raise RpcError(f"Base RPC unavailable: {ex}") from None
        if "error" in j:
            raise RpcError(f"Base RPC error: {j['error'].get('message', j['error'])}")
        return j.get("result")


class PriviToken:
    def __init__(self, rpc: Callable[[str, list], Any], pay_to: str, db_path: str = ":memory:",
                 token: str = TOKEN, desk: str = DESK, manual_usd: str | None = None, enabled: bool = True,
                 clock: Callable[[], float] = time.time, cache_seconds: float = 30.0):
        self.rpc, self.token, self.desk = rpc, token.lower(), desk.lower()
        self.pay_to = (pay_to or "").lower()
        self.manual_usd = Decimal(manual_usd) if manual_usd else None
        self.enabled = enabled and bool(re.fullmatch(r"0x[0-9a-f]{40}", self.pay_to))
        self.clock, self.cache_seconds = clock, cache_seconds
        self._cache: tuple[float, dict] | None = None
        self._lock = threading.Lock()
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.execute("CREATE TABLE IF NOT EXISTS privi_payments (tx_hash TEXT PRIMARY KEY, tool TEXT, payer TEXT,"
                         " amount TEXT, usd TEXT, used_at REAL)")
        self._db.commit()

    @classmethod
    def from_env(cls, pay_to: str, db_path: str) -> "PriviToken":
        return cls(Rpc(os.getenv("PRIVI_RPC_URL", "https://mainnet.base.org")),
                   os.getenv("PRIVI_PAY_TO", "") or pay_to, db_path,
                   token=os.getenv("PRIVI_TOKEN", TOKEN), desk=os.getenv("PRIVI_DESK", DESK),
                   manual_usd=os.getenv("PRIVI_USD_RATE") or None,
                   enabled=os.getenv("PRIVI_PAYMENTS", "1") != "0")

    # ---------------------------------------------------------------- chain reads

    def _call(self, to: str, data: str) -> str:
        out = self.rpc("eth_call", [{"to": to, "data": "0x" + data}, "latest"]) or "0x"
        return out[2:] if out.startswith("0x") else out

    def _uint(self, to: str, data: str) -> int:
        h = self._call(to, data)
        return int(h[:64], 16) if h else 0

    def _address(self, to: str, data: str) -> str:
        h = self._call(to, data)
        return ("0x" + h[24:64]).lower() if len(h) >= 64 else "0x" + "0" * 40

    def _balance(self, token: str, holder: str) -> int:
        return self._uint(token, SEL["balanceOf"] + _addr(holder))

    def _pools(self) -> list[dict[str, Any]]:
        """PRIVI pools on Uniswap v3 and Aerodrome with any liquidity (none exist as of Oct 2026)."""
        found = []
        for other, name in ((USDC, "USDC"), (WETH, "WETH")):
            for fee in (100, 500, 3000, 10000):
                pool = self._address(UNI_V3_FACTORY, SEL["uni_getPool"] + _addr(self.token) + _addr(other) + _u(fee))
                if int(pool, 16):
                    found.append({"dex": "Uniswap v3", "pair": f"PRIVI/{name}", "fee_bps": fee / 100, "pool": pool,
                                  "privi_in_pool": str(Decimal(self._balance(self.token, pool)) / Decimal(10**18)),
                                  "active_liquidity": str(self._uint(pool, SEL["uni_liquidity"]))})
            for stable in (0, 1):
                pool = self._address(AERO_FACTORY, SEL["aero_getPool"] + _addr(self.token) + _addr(other) + _u(stable))
                if int(pool, 16):
                    found.append({"dex": "Aerodrome", "pair": f"PRIVI/{name}", "stable": bool(stable), "pool": pool,
                                  "privi_in_pool": str(Decimal(self._balance(self.token, pool)) / Decimal(10**18))})
        return found

    def market(self, fresh: bool = False) -> dict[str, Any]:
        """Price and liquidity from the Privi swap desk, plus any DEX pools. Cached for a few seconds."""
        with self._lock:
            if not fresh and self._cache and self.clock() - self._cache[0] < self.cache_seconds:
                return self._cache[1]
        out: dict[str, Any] = {"token": self.token, "chain_id": CHAIN_ID, "desk": self.desk}
        try:
            base = self._address(self.desk, SEL["desk_base"])
            quote = self._address(self.desk, SEL["desk_quote"])
            if base != self.token or quote != USDC:
                raise RpcError(f"swap desk is not PRIVI/USDC (base {base}, quote {quote})")
            price_raw = self._uint(self.desk, SEL["desk_price"])
            scale = self._uint(self.desk, SEL["desk_scale"]) or 10**18
            paused = bool(self._uint(self.desk, SEL["desk_paused"]))
            privi_held = self._balance(self.token, self.desk)
            usdc_held = self._balance(USDC, self.desk)
            desk_price = Decimal(price_raw) / Decimal(scale)       # USDC per PRIVI
            out["desk_state"] = {
                "price_usdc_per_privi": _dec(desk_price), "paused": paused,
                "owner": self._address(self.desk, SEL["desk_owner"]),
                "privi_available_to_buy": _dec(Decimal(privi_held) / Decimal(10**18)),
                "usdc_available_for_sells": _dec(Decimal(usdc_held) / Decimal(10**6)),
                "can_buy_privi": privi_held > 0 and not paused and price_raw > 0,
                "can_sell_privi": usdc_held > 0 and not paused and price_raw > 0,
            }
            out["pools"] = self._pools()
            out["price_usd"] = _dec(self.manual_usd if self.manual_usd else desk_price) if (self.manual_usd or price_raw) else None
            out["price_source"] = "manual (PRIVI_USD_RATE)" if self.manual_usd else ("Privi swap desk" if price_raw else None)
            out["ok"] = True
        except RpcError as ex:
            out.update(ok=False, error=str(ex),
                       price_usd=str(self.manual_usd) if self.manual_usd else None,
                       price_source="manual (PRIVI_USD_RATE)" if self.manual_usd else None)
        with self._lock:
            self._cache = (self.clock(), out)
        return out

    def swap_quote(self, side: str, amount: str) -> dict[str, Any]:
        """Quote a desk swap. side='buy' spends USDC for PRIVI, side='sell' spends PRIVI for USDC."""
        m = self.market()
        if not m.get("ok"):
            return {"ok": False, "error": m.get("error")}
        d = m["desk_state"]
        price = Decimal(d["price_usdc_per_privi"])
        amt = Decimal(str(amount))
        if amt <= 0 or price <= 0:
            return {"ok": False, "error": "amount must be positive and the desk must have a price"}
        if side == "buy":
            out, avail, unit_in, unit_out = amt / price, Decimal(d["privi_available_to_buy"]), "USDC", "PRIVI"
        elif side == "sell":
            out, avail, unit_in, unit_out = amt * price, Decimal(d["usdc_available_for_sells"]), "PRIVI", "USDC"
        else:
            return {"ok": False, "error": "side must be 'buy' or 'sell'"}
        fillable = (not d["paused"]) and out <= avail
        return {"ok": True, "side": side, "amount_in": f"{_dec(amt)} {unit_in}", "amount_out": f"{_dec(out)} {unit_out}",
                "price_usdc_per_privi": str(price), "fillable": fillable, "desk_holds": f"{_dec(avail)} {unit_out}",
                "note": None if fillable else ("desk is paused" if d["paused"] else
                                               f"the desk holds only {_dec(avail)} {unit_out}; it needs more liquidity"),
                "desk": self.desk}

    # ---------------------------------------------------------------- payments

    def quote_usd(self, usd: str | Decimal) -> dict[str, Any] | None:
        """PRIVI amount for a USD price, or None if PRIVI payments are off or there is no price."""
        if not self.enabled:
            return None
        m = self.market()
        if not m.get("price_usd"):
            return None
        price = Decimal(m["price_usd"])
        if price <= 0:
            return None
        raw = math.ceil(Decimal(str(usd)) / price * Decimal(10**18))
        return {"asset": "PRIVI", "token": self.token, "network": "base", "chainId": CHAIN_ID, "payTo": self.pay_to,
                "amount": str(raw), "amount_privi": _dec(Decimal(raw) / Decimal(10**18)), "usd": str(usd),
                "price_usd": m["price_usd"], "price_source": m["price_source"],
                "how": f"Send amount_privi PRIVI to payTo on Base, then call the tool again with "
                       f"_meta['{PAYMENT_META_KEY}'] = {{'tx_hash': '0x…'}}. Each transaction pays for one call. "
                       f"Get PRIVI at the Privi swap desk {self.desk}."}

    def verify_payment(self, payment: Any, tool: str, usd: str | Decimal) -> tuple[bool, dict[str, Any]]:
        """Check a PRIVI payment transaction and mark it used. Returns (ok, receipt or error)."""
        if not self.enabled:
            return False, {"error": "PRIVI payments are not enabled on this service"}
        tx = str((payment or {}).get("tx_hash") if isinstance(payment, dict) else payment or "").strip().lower()
        if not re.fullmatch(r"0x[0-9a-f]{64}", tx):
            return False, {"error": "privi/payment needs a tx_hash (0x + 64 hex)"}
        q = self.quote_usd(usd)
        if not q:
            return False, {"error": "PRIVI has no price right now; pay in USDC instead"}
        if self._db.execute("SELECT 1 FROM privi_payments WHERE tx_hash=?", (tx,)).fetchone():
            return False, {"error": "this PRIVI payment was already used"}
        try:
            rc = self.rpc("eth_getTransactionReceipt", [tx])
            if not rc:
                return False, {"error": "transaction not found or not mined yet; wait a few seconds and retry"}
            if int(rc.get("status", "0x0"), 16) != 1:
                return False, {"error": "transaction failed on chain"}
            head = int(self.rpc("eth_blockNumber", []), 16)
            blk = int(rc["blockNumber"], 16)
            if head - blk + 1 < MIN_CONFIRMATIONS:
                return False, {"error": f"wait for {MIN_CONFIRMATIONS} confirmations, then retry"}
            ts = int((self.rpc("eth_getBlockByNumber", [rc["blockNumber"], False]) or {}).get("timestamp", "0x0"), 16)
        except RpcError as ex:
            return False, {"error": str(ex)}
        if self.clock() - ts > MAX_AGE_SECONDS:
            return False, {"error": "payment transaction is older than 24 hours"}
        paid, payer = 0, None
        for log in rc.get("logs", []):
            t = [x.lower() for x in log.get("topics", [])]
            if (log.get("address", "").lower() == self.token and len(t) == 3 and t[0] == TRANSFER_TOPIC
                    and "0x" + t[2][-40:] == self.pay_to):
                paid += int(log.get("data", "0x0"), 16)
                payer = "0x" + t[1][-40:]
        need = int(q["amount"])
        if paid == 0:
            return False, {"error": f"no PRIVI transfer to {self.pay_to} in this transaction"}
        if Decimal(paid) < Decimal(need) * TOLERANCE:
            return False, {"error": f"paid {Decimal(paid) / Decimal(10**18)} PRIVI, need {q['amount_privi']}"}
        try:
            with self._lock:
                self._db.execute("INSERT INTO privi_payments VALUES (?,?,?,?,?,?)",
                                 (tx, tool, payer, str(paid), str(usd), self.clock()))
                self._db.commit()
        except sqlite3.IntegrityError:
            return False, {"error": "this PRIVI payment was already used"}
        return True, {"success": True, "asset": "PRIVI", "transaction": tx, "network": "base", "payer": payer,
                      "amount": str(paid), "amount_privi": _dec(Decimal(paid) / Decimal(10**18)),
                      "block": blk, "tool": tool}


def register_market_tool(mcp, get_token: Callable[[], "PriviToken"]) -> None:
    """Free, read-only MCP tool: PRIVI price, swap-desk liquidity, DEX pools and a swap quote."""
    @mcp.tool(title="PRIVI token market", annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
    def privi_token_market(
        side: Annotated[str, Field(description="Optional swap quote: 'buy' (USDC -> PRIVI) or 'sell' (PRIVI -> USDC)")] = "",
        amount: Annotated[str, Field(description="Amount to swap in (USDC for buy, PRIVI for sell), e.g. '25'")] = "",
    ) -> dict[str, Any]:
        """PRIVI on Base: price, how much PRIVI and USDC the Privi swap desk holds (so whether a swap can fill),
        any Uniswap v3 / Aerodrome pools, and optionally a swap quote. Every paid Privi tool also accepts PRIVI. Free."""
        t = get_token()
        out = {"market": t.market(fresh=True)}
        if side:
            out["quote"] = t.swap_quote(side, amount or "1")
        return out
