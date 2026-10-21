# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Risk - https://priviflow.us - dariocanoy@priviflow.us
"""Live candles for crypto from Coinbase Exchange's public market-data API (no key).

Any other market (stocks, futures, FX) works by passing closes/highs/lows directly.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request

COINBASE = "https://api.exchange.coinbase.com/products/{product}/candles?granularity={g}"
GRANULARITY = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "6h": 21600, "1d": 86400}
PERIODS_PER_YEAR = {"1m": 525_600, "5m": 105_120, "15m": 35_040, "1h": 8_760, "6h": 1_460, "1d": 365}
_cache: dict[tuple[str, str], tuple[float, dict]] = {}
CACHE_S = 60


class MarketError(RuntimeError):
    pass


def normalize_symbol(symbol: str) -> str:
    s = symbol.strip().upper().replace("/", "-").replace("_", "-")
    if "-" not in s:
        s = s.removesuffix("USDT").removesuffix("USD") + "-USD"
    if not re.fullmatch(r"[A-Z0-9]{2,12}-[A-Z]{3,5}", s):
        raise MarketError("symbol should look like BTC-USD, ETH-USD or SOL/USD")
    return s


def fetch_candles(symbol: str, interval: str = "1d", fetch=None) -> dict:
    """Returns oldest-first closes/highs/lows (up to 300 candles), cached 60 s."""
    if interval not in GRANULARITY:
        raise MarketError(f"interval must be one of {', '.join(GRANULARITY)}")
    product = normalize_symbol(symbol)
    key = (product, interval)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_S:
        return hit[1]
    url = COINBASE.format(product=product, g=GRANULARITY[interval])
    if fetch is None:
        req = urllib.request.Request(url, headers={"User-Agent": "privi-risk/0.1 (+https://priviflow.us)",
                                                   "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                rows = json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise MarketError(f"no market data for {product} (HTTP {e.code}); check the symbol") from e
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            raise MarketError(f"market data unavailable right now: {e}") from e
    else:
        rows = fetch(url)
    if not isinstance(rows, list) or len(rows) < 20:
        raise MarketError(f"not enough market data for {product}")
    rows = sorted(rows, key=lambda r: r[0])            # [time, low, high, open, close, volume]
    data = {"symbol": product, "interval": interval, "source": "Coinbase Exchange public candles",
            "as_of": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(rows[-1][0])),
            "closes": [float(r[4]) for r in rows], "highs": [float(r[2]) for r in rows],
            "lows": [float(r[1]) for r in rows], "periods_per_year": PERIODS_PER_YEAR[interval]}
    _cache[key] = (time.time(), data)
    return data
