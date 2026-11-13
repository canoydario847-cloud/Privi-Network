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
  hash is anchored on Base through Privi Anchor every 5 minutes. Arguments, results, transcripts and
  phone numbers appear publicly only as SHA-256 hashes (callers show as `phone ***-1234`).
  Anyone can recompute it: `call_verify_log` or `GET /verify`.
- **Phone line.** Twilio calls `/voice/inbound`; the voice agent answers pricing and product questions
  from a fixed script (no per-call AI cost), takes pilot requests (transcribed into the private log),
  and puts callers through to Dario on "Dario" or 0. If `ANTHROPIC_API_KEY` is set, questions the
  script does not cover get a two-sentence answer from a small model.

## Privi Call Gateway: every kind of agent can call (v0.2.0)

MCP is one door. The gateway adds the rest on the same server and the same sealed call log.

| Who | How |
|---|---|
| Any AI agent or framework (OpenAI, Claude, Gemini, LangChain, CrewAI, plain code) | REST, described by `/openapi.json`: `GET /v1/agents`, `GET /v1/agents/<number>/tools`, `POST /v1/call`, `POST /v1/call/<number>/<tool>` |
| AI voice and phone agents (Vapi, Retell, ElevenLabs, OpenAI Realtime, Twilio bots) | Copy the tool kit from `/kits/<platform>.json`; all three functions post to one webhook, `POST /v1/hook` |
| Human call-center agents | `/console`: pick a service, fill in the details, run the check, read back the sealed record |

Every request is paid, two ways:

- **Pay per call, no sign-up.** A request without payment gets HTTP 402 with the x402 terms (body and
  `PAYMENT-REQUIRED` header). Repeat it with the signed payment in `PAYMENT-SIGNATURE` (or `X-PAYMENT`);
  PRIVI goes in `X-PRIVI-PAYMENT`. Price: `CALL_PRICE_PER_CALL` (default $0.01).
- **Prepaid key.** `POST /v1/keys` (x402) returns a `pck_...` key holding `CALL_PACK_CREDITS` requests for
  `CALL_PACK_PRICE_USD`. Send `Authorization: Bearer pck_...`; each request spends one credit, failed calls are
  refunded, `GET /v1/balance` shows what is left. Voice platforms and the console use keys, because they cannot
  sign x402 payments.

A target tool's own x402 price is separate: pass that payment as `target_payment` in `POST /v1/call`.
The kits are templates built from each platform's published tool format; test one call on the platform
before giving it to a customer.

## NEW — Privi Agent Access ($1 AI-agent signup)

A self-service **AI-agent-only entry point**, separate from the existing public gateway and free
community directory. Each qualifying AI agent pays **$1.00 USDC on Base once**, registers a
working public HTTPS MCP endpoint, and receives a secret API key with **1,000 Privi Call gateway
requests included**. The key remains associated with that registered agent; when the included
requests run out, the agent may buy another prepaid pack through the existing x402 endpoint.
This is **not unlimited compute**, does **not charge $1 per month**, and downstream third-party
tools may impose their own fees.

| Route | Purpose |
|---|---|
| GET /v1/agent-access | Public machine-readable $1 plan details |
| POST /v1/agent-access/signup | Verify the AI agent's MCP tools/list; issue an x402 payment request; after confirmed USDC settlement, atomically register the agent and issue credentials |
| GET /v1/agent-access/status | Key-protected membership, network number and remaining credits |
| POST /v1/agent-access/call | **Registered agents only**; routes a tool call and spends one prepaid credit on success |

**How an agent signs up:**

1. Expose a public HTTPS MCP endpoint that responds to tools/list and has at least one tool.
   Submit JSON with name, endpoint and description to
   POST https://privi-call.onrender.com/v1/agent-access/signup.
2. Receive HTTP 402 with the Base USDC x402-v2 requirements ($1 = 1,000,000 atomic units).
   Sign a compatible payment and repeat the **same request** with PAYMENT-SIGNATURE header.
3. **Only after successful settlement**, the server returns an agent number, one-time secret
   pck_ API key and 1,000 gateway credits. Save the key outside public code.
4. Call POST /v1/agent-access/call with Authorization: Bearer pck_KEY and
   JSON containing number, tool and arguments. Check balance at GET /v1/agent-access/status,
   and top up via POST /v1/keys.

A human operator may configure or own an AI agent, but this product is **for agent-to-agent
integrations**, not direct human chat. Requiring a functioning MCP endpoint and a secret key
enforces the **agent-service integration**, not mathematical proof that software is autonomous.
No provider (Claude, OpenAI, Grok) is automatically registered or paying merely because its
client is compatible. Invalid agent endpoints are rejected **before** payment processing;
duplicate payment transaction IDs cannot enroll a second agent.

Payment setup requires working CDP_API_KEY_ID, CDP_API_KEY_SECRET, CALL_PAY_TO,
and persistent CALL_DB_PATH. If payment settlement is unavailable, signup returns 503 and
does **not** provision accounts. Do not announce live paid access before an actual production
end-to-end payment, registration and tool call has been verified.

## Outreach checks (v0.3.0)

Three records anyone placing calls has to keep, and one go / no-go answer before dialing. Each list belongs to a prepaid call key (`pck_...`). Phone numbers are stored only as salted SHA-256 hashes plus the last four digits.

| Feature | Tools | What it does |
|---|---|---|
| Do-Not-Call list | `call_do_not_call` (check / add / remove) | Your own list of people who asked not to be called |
| Calling hours | `call_hours_check` | Whether it is between 8 a.m. and 9 p.m. where the called person is (47 CFR 64.1200(c)(1)), and when the window opens next. The window can be narrowed for stricter state rules |
| Consent records | `call_consent_record`, `call_consent_revoke`, `call_consent_check` | Who agreed to marketing calls, an AI voice, call recording or texts; hash-chained so records cannot be back-filled unnoticed. Revoking everything also adds the number to the do-not-call list |
| Pre-call check | `call_precheck` | All three in one answer: go / no-go with blockers and warnings |

> These check your own records only. They do not check the National Do Not Call Registry or state rules, and they are not legal advice.

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
