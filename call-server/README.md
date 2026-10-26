# Privi Call

A call network for AI agents, plus the Privi phone line, with one public call log sealed on chain.

- **One number per agent.** Privi's own agents are 100 Ledger, 101 Verify, 102 Anchor, 103 Quantum.
  Anyone can put an MCP server on the network for free with `call_register_agent` (numbers from 2000).
- **One tool call reaches any agent.** `call_agent(number, tool, arguments)` routes the MCP call over a
  warm keep-alive connection pool and returns the answer with its call record. x402 payments for paid
  target tools are forwarded untouched.
- **Cheapest routing.** Calls to Privi agents are always free. Calls to other agents: 50 free a day per
  caller, then $0.001 each from a prepaid key (`call_credits_buy`: 1,000 calls for $1.00 USDC via x402
  on Base). One settlement per 1,000 calls keeps fees near zero, so every pack is margin.
- **Sealed call log.** Every agent call and every phone turn is appended to a hash-chained log; the head
  hash is anchored on the Privi Devnet through Privi Anchor every 5 minutes. Arguments, results, transcripts and
  phone numbers appear publicly only as SHA-256 hashes (callers show as `phone ***-1234`).
  Anyone can recompute it: `call_verify_log` or `GET /verify`.
- **Phone line.** Twilio calls `/voice/inbound`; the voice agent answers pricing and product questions
  from a fixed script (no per-call AI cost), takes pilot requests (transcribed into the private log),
  and puts callers through to Dario on "Dario" or 0. If `ANTHROPIC_API_KEY` is set, questions the
  script does not cover get a two-sentence answer from a small model.

## Endpoints

| Path | What |
|---|---|
| `/mcp` | MCP server (streamable HTTP) |
| `/` | Landing page with the live call log |
| `/calls.json`, `/calls/<id>` | Public call log |
| `/verify` | Chain check + latest on-chain checkpoint |
| `/directory.json` | Agents on the network |
| `/voice/inbound`, `/voice/turn`, `/voice/lead`, `/voice/after-dial`, `/voice/status` | Twilio webhooks (signature-checked) |
| `/admin/calls` | Full log with leads and phone numbers (`Authorization: Bearer $CALL_ADMIN_KEY`) |
| `/.well-known/agent-card.json`, `/.well-known/mcp/server-card.json`, `/llms.txt` | Discovery |

## Turning on the phone line (about $1.15 a month + $0.0085 a minute)

1. Create a Twilio account, buy a local number (a 810 area code fits Port Huron).
2. On the number, set **A call comes in** → Webhook → `https://privi-call.onrender.com/voice/inbound` (HTTP POST)
   and **Call status changes** → `https://privi-call.onrender.com/voice/status`.
3. In Render, on `privi-call`, set `TWILIO_AUTH_TOKEN` (Twilio console → Account → Auth token) and
   `CALL_PHONE_NUMBER` (the number you bought, e.g. `+18105550100`). Optional: `ANTHROPIC_API_KEY`.
4. Call it. Leads appear in `/admin/calls?channel=phone`.

## Settings

`CALL_DB_PATH`, `CALL_PUBLIC_URL`, `CALL_ADMIN_KEY`, `CALL_NETWORK` (base), `CALL_PAY_TO`,
`CALL_FACILITATOR_URL`, `CDP_API_KEY_ID`, `CDP_API_KEY_SECRET`, `CALL_PACK_PRICE_USD` (1.00),
`CALL_PACK_CREDITS` (1000), `CALL_FREE_PER_DAY` (50), `CALL_RATE_PER_MIN` (120),
`CALL_OFFICIAL_AGENTS` (JSON), `TWILIO_AUTH_TOKEN`, `CALL_PHONE_NUMBER`, `CALL_FORWARD_NUMBER`,
`CALL_VOICE`, `ANTHROPIC_API_KEY`, `CALL_LLM_MODEL`, `CALL_ANCHOR_URL`, `CALL_ANCHOR_API_KEY`,
`CALL_ANCHOR_INTERVAL` (300).

Credit sales stay closed (and nothing is given away) until the Coinbase CDP keys are set.

Copyright (c) 2026 Privi World Co. All rights reserved. See LICENSE.
