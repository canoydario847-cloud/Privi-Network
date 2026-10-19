#!/usr/bin/env python3
"""Read-only native PRVI genesis parameter audit for pinned Cosmos EVM v0.7.3.

No signing, tokens, RPC, genesis edits, or network access. This enforces
static configuration alignment; it does NOT prove mint-route security,
staking economics, consensus, token vesting or launch readiness.
"""
from decimal import Decimal, InvalidOperation

DENOM = "aprvi"
SYMBOL = "PRVI"
DECIMALS = 18
MAX_BASE = 10**27
_ZERO_FIELDS = ("inflation_rate_change", "inflation_max", "inflation_min")

def obj(value, where):
    if not isinstance(value, dict):
        raise ValueError(where + " must be an object")
    return value

def values(value, where):
    if not isinstance(value, list):
        raise ValueError(where + " must be an array")
    return value

def decimal_zero(raw, where):
    # Numeric floats are refused: no imprecise/exponent shorthand in the
    # reviewed unsigned genesis JSON.
    if not isinstance(raw, str) or not raw or len(raw) > 80:
        raise ValueError(where + " must be an exact zero decimal string")
    if any(c not in "0123456789." for c in raw) or raw.count(".") > 1:
        raise ValueError(where + " must be an exact zero decimal string")
    try:
        d = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(where + " must be a decimal") from exc
    if not d.is_finite() or d != 0:
        raise ValueError(where + " must be zero")
    return None

def audit(genesis):
    genesis = obj(genesis, "genesis")
    app = obj(genesis.get("app_state"), "app_state")
    bank = obj(app.get("bank"), "app_state.bank")
    evm = obj(app.get("evm"), "app_state.evm")
    staking = obj(app.get("staking"), "app_state.staking")
    mint = obj(app.get("mint"), "app_state.mint")

    if obj(evm.get("params"), "evm.params").get("evm_denom") != DENOM:
        raise ValueError("EVM gas denomination must be aprvi")
    if obj(staking.get("params"), "staking.params").get("bond_denom") != DENOM:
        raise ValueError("staking bonded denomination must be aprvi")
    mint_params = obj(mint.get("params"), "mint.params")
    if mint_params.get("mint_denom") != DENOM:
        raise ValueError("x/mint denomination must be aprvi")
    for name in _ZERO_FIELDS:
        decimal_zero(mint_params.get(name), "mint.params." + name)
    minter = obj(mint.get("minter"), "mint.minter")
    for name in ("inflation", "annual_provisions"):
        decimal_zero(minter.get(name), "mint.minter." + name)

    metadata = values(bank.get("denom_metadata"), "bank.denom_metadata")
    matches = [row for row in metadata
               if isinstance(row, dict) and row.get("base") == DENOM]
    if len(matches) != 1:
        raise ValueError("exactly one aprvi bank denomination metadata record required")
    record = matches[0]
    if record.get("display") != SYMBOL or record.get("symbol") != SYMBOL:
        raise ValueError("aprvi display and symbol must both be PRVI")
    units = values(record.get("denom_units"), "aprvi.denom_units")
    if len(units) != 2 or any(not isinstance(u, dict) for u in units):
        raise ValueError("aprvi metadata requires exactly base and display units")
    seen = set()
    for unit in units:
        denom, exponent = unit.get("denom"), unit.get("exponent")
        if type(exponent) is not int:
            raise ValueError("denom exponent must be an integer")
        if denom not in (DENOM, SYMBOL) or denom in seen:
            raise ValueError("duplicate or unexpected aprvi denom unit")
        if (denom == DENOM and exponent != 0) or (denom == SYMBOL and exponent != DECIMALS):
            raise ValueError("aprvi must use 18 decimals")
        seen.add(denom)
    if seen != {DENOM, SYMBOL}:
        raise ValueError("aprvi base/display denom units missing")

    supplies = values(bank.get("supply"), "bank.supply")
    native = [coin for coin in supplies if isinstance(coin, dict) and coin.get("denom") == DENOM]
    if len(native) != 1:
        raise ValueError("exactly one aprvi bank supply entry required")
    amount = native[0].get("amount")
    if not isinstance(amount, str) or not amount.isascii() or not amount.isdecimal() or amount.startswith("0"):
        raise ValueError("aprvi supply must be canonical positive base-unit string")
    if int(amount) > MAX_BASE:
        raise ValueError("aprvi genesis supply exceeds 1 billion PRVI")
    # Bank balance summation is separately verified by genesis_supply_audit;
    # the final custom Cosmos EVM binary must independently validate InitChain.
    return {
        "native_prvi_parameters": "PASS_STATIC_ONLY",
        "base_denom": DENOM,
        "decimals": DECIMALS,
        "evm_gas": DENOM,
        "staking": DENOM,
        "mint_denom": DENOM,
        "inflation": "ZERO",
        "financial_mainnet": "NOT_AUTHORIZED",
    }
