# Privi Risk

**Don't bet the bank.** The pre-trade risk desk for crypto and market traders and AI trading agents.
A Privi World Co product · Copyright (c) 2026 Privi World Co. All rights reserved.

Endpoint (MCP, streamable HTTP): `https://privi-risk.onrender.com/mcp`

```json
{ "mcpServers": { "privi-risk": { "url": "https://privi-risk.onrender.com/mcp" } } }
```

Most accounts aren't blown up by bad calls but by position size, leverage, and liquidation
prices that sit inside the stop. Privi Risk is the check to run before every trade.

## Tools

| Tool | Price | What it answers |
|---|---|---|
| `risk_position_size` | free | How many units so a stop-out loses exactly X% (fees included); 1R/2R/3R targets; for leverage: margin, liquidation price, and a hard **LIQUIDATION BEFORE STOP** warning |
| `risk_of_ruin` | free | 10,000 Monte Carlo futures of your plan: odds of hitting your drawdown limit (e.g. a prop-firm 10%) or ruin, ending-equity range, Kelly, half-Kelly, and the **max safe risk per trade** |
| `risk_market_check` | free | Live volatility, ATR (with a 2×ATR stop suggestion), max drawdown, VaR and Expected Shortfall at 95/99% for any Coinbase pair, or any market from your own prices |
| `risk_pretrade_report` | **$0.10 USDC** (Base, x402) | All checks for one trade and a **GO / REDUCE / NO-TRADE** verdict with every reason, signed Ed25519 + ML-DSA-87 and anchored on the Privi blockchain |
| `risk_verify` | free | Checks a report's signatures, hash and on-chain anchor |
| `risk_status` | free | Prices, payment network, keys, anchoring |

**Who pays for the report:** prop-firm traders proving they followed risk rules, funds and
desks that need a pre-trade compliance record, and AI trading agents whose owners require
every trade to be risk-checked before money moves (pairs with Privi Mandates).

Payment is x402 v2 over MCP: call without payment to get the `PaymentRequired` terms, sign, and
retry with `_meta["x402/payment"]`. Invalid trades are rejected **before** any charge.

HTTP: `/health`, `/status`, `/keys`, `/reports/<id>`, `/.well-known/mcp/server-card.json`.

## Method

- Sizing: `units = (account × risk%) / (|entry − stop| + fee × (entry + stop))`. Isolated-margin
  liquidation: long `entry × (1 − 1/lev + mm)`, short `entry × (1 + 1/lev − mm)`. Exchange formulas
  vary slightly; use your exchange's maintenance margin.
- Ruin: fixed-fractional Monte Carlo, 10,000 paths; Kelly `f* = W/L − (1 − W)/R`; max safe risk is the
  largest risk with ≤5% chance of the drawdown limit (bisection, common random numbers).
- Market: historical-simulation VaR and Expected Shortfall on log returns; ATR(14) from true range.

## Disclaimer

Risk analytics for education and planning, not financial advice. Markets can gap through stops.

## Run locally

```
pip install .
RISK_DB_PATH=./risk.db privi-risk-mcp     # http://localhost:8000/mcp
pytest                                     # 8 tests
```

Environment: `RISK_DB_PATH`, `RISK_PUBLIC_URL`, `RISK_PAY_TO`, `RISK_NETWORK` (base | base-sepolia),
`RISK_FACILITATOR_URL`, `CDP_API_KEY_ID`, `CDP_API_KEY_SECRET`, `RISK_PRICE_PRETRADE_REPORT`,
`RISK_ANCHOR_URL`, `RISK_ANCHOR_API_KEY`, `RISK_SIGNING_SEED`, `RISK_RATE_PER_MIN`.
Without a payout wallet or CDP keys the free tools still run and the paid report says it isn't open yet.

## Ownership

Privi Risk is proprietary software of Privi World Co (see `LICENSE`). Built by Privi World Co,
Port Huron, Michigan · Dario Canoy, founder · dariocanoy@priviflow.us · https://priviflow.us
