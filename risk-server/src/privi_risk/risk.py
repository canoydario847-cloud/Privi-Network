# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Risk - https://priviflow.us - dariocanoy@priviflow.us
"""Pre-trade risk math: the checks that decide whether a trade can blow up an account.

position_size   how many units to buy for a fixed account risk, fees included, with the
                liquidation price for leveraged (perp/futures) positions and a hard warning
                when liquidation sits before the stop - the classic account killer.
risk_of_ruin    Monte Carlo of a trading plan (win rate, payoff, risk per trade): odds of a
                given drawdown or ruin, Kelly fraction, and the largest risk per trade that
                keeps a deep drawdown unlikely.
market_risk     realized volatility, ATR, max drawdown, Value-at-Risk and Expected
                Shortfall (CVaR) for a position, from candles or closing prices.
verdict         GO / REDUCE / NO-TRADE for a planned trade, with every reason stated.

Educational risk analytics, not financial advice.
"""
from __future__ import annotations

import math

import numpy as np

MAX_ABS = 1e15
MAX_TRADES = 1000
PATHS = 10_000


class RiskError(ValueError):
    pass


def num(v, name: str, lo: float | None = None, hi: float | None = None, positive: bool = False) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise RiskError(f"{name} must be a number")
    if not math.isfinite(f) or abs(f) > MAX_ABS:
        raise RiskError(f"{name} must be a finite number")
    if positive and f <= 0:
        raise RiskError(f"{name} must be greater than 0")
    if lo is not None and f < lo:
        raise RiskError(f"{name} must be at least {lo}")
    if hi is not None and f > hi:
        raise RiskError(f"{name} must be at most {hi}")
    return f


def _r(x, d=6):
    return None if x is None else round(float(x), d)


# ------------------------------------------------------------------ position sizing

def position_size(account: float, entry: float, stop: float, risk_pct: float = 1.0, side: str = "long",
                  leverage: float | None = None, fee_pct: float = 0.1, maintenance_margin_pct: float = 0.5,
                  take_profit: float | None = None) -> dict:
    account = num(account, "account", positive=True)
    entry = num(entry, "entry", positive=True)
    stop = num(stop, "stop", positive=True)
    risk_pct = num(risk_pct, "risk_pct", positive=True, hi=100)
    fee = num(fee_pct, "fee_pct", lo=0, hi=10) / 100
    mmr = num(maintenance_margin_pct, "maintenance_margin_pct", lo=0, hi=50) / 100
    side = side.lower().strip()
    if side not in ("long", "short"):
        raise RiskError("side must be long or short")
    if side == "long" and stop >= entry:
        raise RiskError("for a long, the stop must be below the entry")
    if side == "short" and stop <= entry:
        raise RiskError("for a short, the stop must be above the entry")

    risk_usd = account * risk_pct / 100
    per_unit_loss = abs(entry - stop) + fee * (entry + stop)   # price move + entry and exit fees
    units = risk_usd / per_unit_loss
    notional = units * entry
    lev_needed = notional / account
    sgn = 1 if side == "long" else -1
    out = {
        "side": side, "units": _r(units, 8), "notional_usd": _r(notional, 2),
        "risk_usd": _r(risk_usd, 2), "risk_pct_of_account": _r(risk_pct, 4),
        "stop_distance_pct": _r(abs(entry - stop) / entry * 100, 4),
        "fees_usd_round_trip": _r(units * fee * (entry + stop), 2),
        "leverage_needed": _r(lev_needed, 3),
        "targets": {f"{k}R": _r(entry + sgn * k * abs(entry - stop), 8) for k in (1, 2, 3)},
        "warnings": [],
    }
    if take_profit is not None:
        tp = num(take_profit, "take_profit", positive=True)
        if (tp - entry) * sgn <= 0:
            raise RiskError("take_profit must be on the winning side of the entry")
        reward = units * abs(tp - entry) - units * fee * (entry + tp)
        out["reward_usd"] = _r(reward, 2)
        out["reward_to_risk"] = _r(reward / risk_usd, 3)
        if reward / risk_usd < 1:
            out["warnings"].append("reward is smaller than the risk after fees (below 1R)")

    if leverage is not None:
        lev = num(leverage, "leverage", lo=1, hi=500)
        margin = notional / lev
        liq = entry * (1 - 1 / lev + mmr) if side == "long" else entry * (1 + 1 / lev - mmr)
        out.update(leverage=_r(lev, 3), margin_usd=_r(margin, 2), liquidation_price=_r(liq, 8),
                   liquidation_distance_pct=_r(abs(entry - liq) / entry * 100, 4),
                   liquidation_before_stop=bool((side == "long" and liq >= stop) or (side == "short" and liq <= stop)))
        if margin > account:
            out["warnings"].append(f"needs ${margin:,.2f} margin but the account is ${account:,.2f}; "
                                   f"use at least {math.ceil(lev_needed * 100) / 100}x or a smaller size")
        if out["liquidation_before_stop"]:
            out["warnings"].append("LIQUIDATION BEFORE STOP: you would be liquidated before your stop fills "
                                   "and lose the whole margin. Lower the leverage or tighten the stop.")
        elif abs(liq - stop) / entry < 0.01:
            out["warnings"].append(f"liquidation ({liq:,.2f}) is within 1% of the stop: slippage or a wick past the "
                                   "stop could liquidate you. Use lower leverage for a safety buffer.")
    elif lev_needed > 1:
        out["warnings"].append(f"this size is {lev_needed:.2f}x the account; it needs leverage or a wider account")
    if risk_pct > 2:
        out["warnings"].append(f"risking {risk_pct}% per trade; most professional desks cap it at 0.5-2%")
    return out


# ------------------------------------------------------------------ risk of ruin

def _simulate(win_rate, avg_win_r, avg_loss_r, risk, trades, u):
    """u: uniform draws (PATHS x trades), shared across calls so results move smoothly."""
    step = np.where(u < win_rate, 1 + risk * avg_win_r, 1 - risk * avg_loss_r)
    step = np.maximum(step, 1e-9)
    log_eq = np.cumsum(np.log(step), axis=1)
    peak = np.maximum.accumulate(np.maximum(log_eq, 0.0), axis=1)
    max_dd = 1 - np.exp(np.min(log_eq - peak, axis=1))
    return np.exp(log_eq[:, -1]), max_dd


def risk_of_ruin(win_rate: float, avg_win_r: float, avg_loss_r: float = 1.0, risk_pct: float = 1.0,
                 trades: int = 200, drawdown_limit_pct: float = 30.0, ruin_pct: float = 50.0,
                 seed: int = 7) -> dict:
    w = num(win_rate, "win_rate", lo=0, hi=100)
    W = w if w <= 1 else w / 100   # accepts 0.55 or 55
    R = num(avg_win_r, "avg_win_r", positive=True, hi=1000)
    L = num(avg_loss_r, "avg_loss_r", positive=True, hi=100)
    risk = num(risk_pct, "risk_pct", positive=True, hi=100) / 100
    n = int(num(trades, "trades", lo=1, hi=MAX_TRADES))
    dd_lim = num(drawdown_limit_pct, "drawdown_limit_pct", positive=True, hi=99.9) / 100
    ruin = num(ruin_pct, "ruin_pct", positive=True, hi=99.9) / 100
    if risk * L >= 1:
        raise RiskError("risk_pct x avg_loss_r must be below 100% (one loss would wipe the account)")
    u = np.random.default_rng(seed).random((PATHS, n), dtype=np.float32)
    final, mdd = _simulate(W, R, L, risk, n, u)
    expectancy = W * R - (1 - W) * L
    kelly = W / L - (1 - W) / R   # optimal fraction of equity to risk per trade (as the loss size)

    def p_dd(r):
        return float(np.mean(_simulate(W, R, L, r, n, u)[1] >= dd_lim))

    safe = None
    if expectancy > 0:
        lo, hi = 0.0005, min(0.5, 0.99 / L)
        if p_dd(lo) <= 0.05:
            for _ in range(22):
                mid = (lo + hi) / 2
                lo, hi = (mid, hi) if p_dd(mid) <= 0.05 else (lo, mid)
            safe = lo
    out = {
        "plan": {"win_rate": _r(W, 4), "avg_win_r": R, "avg_loss_r": L, "risk_pct": _r(risk * 100, 4), "trades": n},
        "expectancy_r_per_trade": _r(expectancy, 4),
        "edge": "positive" if expectancy > 0 else "negative - this plan loses money on average at any size",
        "probability_drawdown_at_least_limit": _r(float(np.mean(mdd >= dd_lim)), 4),
        "drawdown_limit_pct": _r(dd_lim * 100, 2),
        "probability_of_ruin": _r(float(np.mean(mdd >= ruin)), 4),
        "ruin_defined_as_drawdown_pct": _r(ruin * 100, 2),
        "probability_account_ends_lower": _r(float(np.mean(final < 1)), 4),
        "ending_equity_multiple": {"p5": _r(np.percentile(final, 5), 4), "median": _r(np.median(final), 4),
                                   "p95": _r(np.percentile(final, 95), 4)},
        "median_max_drawdown_pct": _r(float(np.median(mdd)) * 100, 2),
        "kelly_risk_pct": _r(max(kelly, 0) * 100, 3),
        "half_kelly_risk_pct": _r(max(kelly, 0) * 50, 3),
        "max_safe_risk_pct": math.floor(safe * 100_000) / 1000 if safe is not None else None,  # floor: never round up past the limit
        "max_safe_risk_rule": f"largest risk per trade with at most a 5% chance of a {dd_lim * 100:g}% drawdown over {n} trades",
        "simulation": f"Monte Carlo, {PATHS:,} paths x {n} trades, fixed-fractional sizing",
        "warnings": [],
    }
    if expectancy <= 0:
        out["warnings"].append("negative expectancy: no position size makes this plan profitable")
    if kelly > 0 and risk > kelly:
        out["warnings"].append(f"risk per trade is above full Kelly ({kelly * 100:.2f}%): more size lowers long-run growth")
    if safe is not None and risk > safe:
        out["warnings"].append(f"risk per trade is above the max safe level ({safe * 100:.2f}%)")
    return out


# ------------------------------------------------------------------ market risk

def market_risk(closes, highs=None, lows=None, position_usd: float | None = None, horizon_days: int = 1,
                periods_per_year: int = 365) -> dict:
    c = np.asarray([num(x, "close", positive=True) for x in (closes or [])], dtype=float)
    if len(c) < 20:
        raise RiskError("need at least 20 closing prices (oldest first)")
    if len(c) > 5000:
        raise RiskError("at most 5000 prices")
    h = int(num(horizon_days, "horizon_days", lo=1, hi=365))
    ppy = int(num(periods_per_year, "periods_per_year", lo=1, hi=525_600))
    rets = np.diff(np.log(c))
    vol = float(np.std(rets, ddof=1))
    simple = np.exp(rets) - 1
    if len(c) > h + 20 and h > 1:
        hr = c[h:] / c[:-h] - 1          # overlapping h-period returns
    else:
        hr = simple * math.sqrt(h)
    var95, var99 = (-float(np.percentile(hr, q)) for q in (5, 1))
    cvar95 = -float(hr[hr <= -var95].mean()) if np.any(hr <= -var95) else var95
    cvar99 = -float(hr[hr <= -var99].mean()) if np.any(hr <= -var99) else var99
    if highs is not None and lows is not None and len(highs) == len(c) == len(lows):
        hi = np.asarray([num(x, "high", positive=True) for x in highs])
        lo = np.asarray([num(x, "low", positive=True) for x in lows])
        tr = np.maximum(hi[1:] - lo[1:], np.maximum(abs(hi[1:] - c[:-1]), abs(lo[1:] - c[:-1])))
        atr_method = "true range"
    else:
        tr = np.abs(np.diff(c))
        atr_method = "close-to-close (no highs/lows given)"
    atr = float(np.mean(tr[-14:]))
    peak = np.maximum.accumulate(c)
    mdd = float(np.max(1 - c / peak))
    last = float(c[-1])
    sma50 = float(np.mean(c[-50:])) if len(c) >= 50 else None
    out = {
        "last_price": _r(last, 8), "observations": int(len(c)),
        "volatility_per_period_pct": _r(vol * 100, 4),
        "volatility_annualized_pct": _r(vol * math.sqrt(ppy) * 100, 3),
        "atr_14": _r(atr, 8), "atr_14_pct": _r(atr / last * 100, 4), "atr_method": atr_method,
        "suggested_stop_distance": {"atr_multiple": 2, "price_distance": _r(2 * atr, 8),
                                    "long_stop": _r(last - 2 * atr, 8), "short_stop": _r(last + 2 * atr, 8)},
        "max_drawdown_in_window_pct": _r(mdd * 100, 3),
        "trend": None if sma50 is None else ("above 50-period average" if last > sma50 else "below 50-period average"),
        "horizon_periods": h,
        "value_at_risk_pct": {"95": _r(var95 * 100, 4), "99": _r(var99 * 100, 4)},
        "expected_shortfall_pct": {"95": _r(cvar95 * 100, 4), "99": _r(cvar99 * 100, 4)},
        "method": "historical simulation on log returns; ES (CVaR) = average loss beyond VaR",
    }
    if position_usd is not None:
        p = num(position_usd, "position_usd", positive=True)
        out["position_usd"] = _r(p, 2)
        out["value_at_risk_usd"] = {"95": _r(p * var95, 2), "99": _r(p * var99, 2)}
        out["expected_shortfall_usd"] = {"95": _r(p * cvar95, 2), "99": _r(p * cvar99, 2)}
    return out


# ------------------------------------------------------------------ verdict

def verdict(account: float, sizing: dict, market: dict | None, ruin: dict | None) -> dict:
    """GO / REDUCE / NO-TRADE with every reason. Stricter checks win."""
    no, reduce, ok = [], [], []
    if sizing.get("liquidation_before_stop"):
        no.append("liquidation price is before the stop: the stop cannot protect you")
    if sizing.get("margin_usd") and sizing["margin_usd"] > account:
        no.append("the position needs more margin than the account holds")
    rp = sizing["risk_pct_of_account"]
    if rp > 5:
        no.append(f"risks {rp}% of the account on one trade")
    elif rp > 2:
        reduce.append(f"risks {rp}% of the account; keep single-trade risk at or under 2%")
    else:
        ok.append(f"single-trade risk {rp}% is within the 2% rule")
    if ruin:
        if ruin["expectancy_r_per_trade"] is not None and ruin["expectancy_r_per_trade"] <= 0:
            no.append("the trading plan has negative expectancy")
        safe = ruin.get("max_safe_risk_pct")
        if safe is not None and rp > safe:
            reduce.append(f"above the plan's max safe risk of {safe}% per trade")
        if ruin["probability_of_ruin"] > 0.05:
            reduce.append(f"{ruin['probability_of_ruin'] * 100:.1f}% chance of a {ruin['ruin_defined_as_drawdown_pct']:g}% drawdown over the plan")
        elif ruin["expectancy_r_per_trade"] and ruin["expectancy_r_per_trade"] > 0:
            ok.append(f"risk of ruin {ruin['probability_of_ruin'] * 100:.2f}% over {ruin['plan']['trades']} trades")
    if market:
        atr_pct = market.get("atr_14_pct")
        if atr_pct and sizing["stop_distance_pct"] < atr_pct:
            reduce.append(f"stop is {sizing['stop_distance_pct']}% away, inside one ATR ({atr_pct}%): likely stopped out by normal noise")
        es = (market.get("expected_shortfall_usd") or {}).get("99")
        if es is not None and es > account * 0.10:
            reduce.append(f"a bad-day loss (99% expected shortfall) of ${es:,.2f} is over 10% of the account if the stop gaps")
        elif es is not None:
            ok.append(f"99% expected shortfall ${es:,.2f} stays under 10% of the account")
    decision = "NO-TRADE" if no else ("REDUCE" if reduce else "GO")
    return {"decision": decision, "blocking": no, "reduce_because": reduce, "passed": ok}
