# Privi Call carrier — pricing method

Goal from Dario: as cheap as possible while still making money.

## Rule

`price = upstream cost × (1 + margin) + payment overhead`, rounded to a clean number, with:
- margin floor 30% on usage, 50% on numbers (numbers are the sticky part);
- payment overhead near zero by selling prepaid packs settled once per pack over x402 (as `call_credits_buy` does);
- a free tier small enough that abuse costs little (today: 50 agent calls a day; Privi's own agents always free).

## Current price points (live)

| Item | Price | Notes |
|---|---|---|
| Agent-to-agent call (non-Privi target) | $0.001 (1,000 for $1.00 USDC) | `CALL_PACK_PRICE_USD`, `CALL_PACK_CREDITS` |
| Calls to Privi agents | free | |
| Phone line cost to Privi | about $1.15/month per number + $0.0085/min (Twilio, per `call-server/README.md`) | verify before quoting |

## To decide (STOP: Dario)

Proposed shape for agents to model with real upstream costs, then present as options:
- **Privi Number**: monthly price per local number, including the sealed log and the AI receptionist script.
- **Minutes**: inbound/outbound per minute, prepaid packs.
- **AI receptionist with LLM fallback**: per-minute surcharge covering model cost.
- **Compliance export** (sealed call history PDF via Ledger reports): included on paid plans.

Agents put the cost model in `company/telecom/research/unit-economics.md` (or a Sheets artifact) with each
input's source and date.
