# Privi go-to-market (first revenue)

Status as of 2026-10-21 (from /stats): Ledger 0 calls in 30 days; Verify 4 calls, all
today (own tests). Revenue so far: none from outside users. Goal of the next 30 days:
**one paying customer, ten real integrators.** Don't claim traction publicly until it exists.

## What people will actually pay for (ranked by shortest path to cash)

1. **Verify per-call (x402, already live).** Pay-per-call, no signup. Revenue = calls x price.
   Needs discovery only: Bazaar listing + MCP directories. Cost to buyer: cents. Volume play.
2. **Ledger Pro ($29 USDC / 30 days).** Buyer: a developer shipping agents who needs a
   signed, anchored audit trail (EU AI Act Art. 12 record-keeping, customer security reviews).
   Pitch: "tamper-evident log of what your agent did, verifiable by a third party, 5 min setup."
3. **Gateway Pro.** Buyer: anyone running a public MCP server who wants metering, rate
   limits, a wallet-proof (KYA) gate and audit log in front of it. Free tier: 1,000 calls/mo, 2 gateways.
4. **Design partners (enterprise plan, negotiated).** 3 to 5 teams building agent payments/
   mandates. Offer: free enterprise for 90 days in exchange for a case study + feedback.

## Directory listing copy

**One line (<=100 chars):**
Tamper-evident, anchored audit trail + agent identity (passports, mandates) for AI agents, via MCP.

**Short description:**
Privi gives AI agents a verifiable record. Ledger writes co-signed (Ed25519 + ML-DSA-87),
Merkle-logged, on-chain-anchored entries; Passports and Mandates bind an agent to an accountable
owner and a spending limit; Live streams events over WebSocket/SSE with human approvals and a
kill switch; Gateway puts metering, rate limits and a KYA gate in front of any MCP server.
Free tier, Pro $29 USDC/30 days, pay-per-call tools via x402.

**Tags:** mcp, audit-log, agent-identity, x402, usdc, compliance, eu-ai-act, merkle, websocket

Submit to: Smithery, PulseMCP, Glama, mcp.so, Cursor directory, Cline marketplace,
x402 ecosystem page, Coinbase Bazaar (already via extension). Needs your logins.

## Outreach target lists (find 20 each, personalize, 1 message per person)

- **Teams publishing x402/MCP tools:** they need metering + trust. Offer a free Gateway in
  front of their server and a Verify badge. Search GitHub for `x402` + `mcp` repos, issues
  asking about auditing or rate limiting.
- **Agent-framework authors (LangGraph, CrewAI, OpenAI Agents SDK users):** offer a
  5-line integration PR that logs tool calls to Ledger. Open it as a PR on their examples repo.
- **Compliance-minded builders:** people writing about EU AI Act logging obligations,
  IETF agent audit-trail drafts (e.g. draft-sharif-agent-audit-trail). Offer interop and a pilot.
- **Fintech / payments agent startups:** Mandates + human approval gate is the wedge.

## Message templates (edit, then you send; I do not send on your behalf without your yes)

**Builder (cold, short):**
> Hi <name>, I saw <repo/post>. I built Privi, an MCP server that gives an agent a
> co-signed, publicly verifiable audit trail (anchored on-chain) plus spend mandates with human
> approval. Free tier. Would a 5-line integration into <their project> be useful? Happy to open the PR.
> priviflow.us — Dario

**Design partner:**
> Hi <name>, we're onboarding 3 design partners for Privi (agent audit trail, mandates, kill
> switch, live approvals). Enterprise plan free for 90 days; in return, 30 min feedback and an
> optional named case study. Interested?

## 14-day plan

| Days | Action | Owner |
|---|---|---|
| 1 | Rotate Coinbase CDP key; add live.priviflow.us + remaining custom domains | Dario |
| 1 | Run 2 Bazaar test payments so listings index | Dario |
| 1-2 | Submit to Smithery, PulseMCP, Glama, mcp.so, Cursor, Cline | Dario (logins), copy above |
| 2-3 | Search Console (Google/Bing); GitHub repo topics + homepage | Dario |
| 3-7 | Open 10 integration PRs / issues with a working example | Claude drafts, Dario approves |
| 3-7 | 20 personalized outreach messages | Claude drafts, Dario sends |
| 7-14 | Convert 1 design partner; ship their feedback | both |
| 14 | Review /stats; double down on whichever channel produced calls | both |

## Metrics to watch
`/stats` on each service (tool calls by tool), plan upgrades (ledger_upgrade_pro receipts),
gateway count/usage (`gw_usage`), Live connections. Only report numbers from these.

## Investor note
Interest-only page is fine; do not collect money or imply securities offerings without counsel.
Lead with real usage numbers once they exist; today there are none to show.
