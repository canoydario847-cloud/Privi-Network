# Privi Call — commercial launch checklist (2026-11-12)

Owner: Privi World Corp. Status: launch plan, not a production certification.

## Customer promise
One authenticated gateway for AI-agent tools: MCP discovery, call routing, metering, signed receipts, and USDC-compatible billing. Compatible clients may include Claude, ChatGPT, Grok, and custom agents; no provider endorsement or integration is implied.

## First sellable offer
**Privi Call pilot:** $99/month proposed, includes onboarding, one configured agent integration, usage dashboard, and a defined allowance to be set after load/cost testing. Overage billing must remain disabled until limits and pricing are disclosed. Offer a manual invoice/payment link only after confirming working service and terms.

## Go-live gates
- [ ] GET health, MCP handshake and authenticated tool call pass on deployed call-server.
- [ ] Reject invalid keys, prevent replay, apply per-tenant rate limits and redact secrets in logs.
- [ ] Meter only successful billable requests; idempotent event IDs, reconciliation, refund/credit policy.
- [ ] Generate independently verifiable signed receipts; do not claim native mainnet anchoring before verification.
- [ ] Verify wallet ownership and actual USDC payment receipt on Base before crediting account.
- [ ] Publish privacy, retention, acceptable-use, support, and incident-response terms.
- [ ] Run one external-client end-to-end call and a small paid pilot before advertising production SLAs.

## Distribution
Submit accurate, independently verified listings to MCP registries; publish copy/paste client configs and A2A card; make demo and pricing visible on Privi Hub. No automated spam or unsupported 'official partner' claims.

## Weekly operating scorecard
Active developer keys; successful authenticated calls; p95 latency; error rate; paying customers; invoiced USD; confirmed received USDC; refunds; cost per 1,000 calls; gross margin.

## Outreach (permission-based)
Subject: Pilot Privi Call for your AI agents
We're offering a small pilot for teams using multiple AI agents. Privi Call aims to unify MCP tool access, authenticated routing, metered usage and verifiable receipts. Would you be open to a 15-minute technical fit check? We'll share a working endpoint and limits before any payment.
