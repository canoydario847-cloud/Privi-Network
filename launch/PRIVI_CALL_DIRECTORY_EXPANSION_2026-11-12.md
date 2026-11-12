# Privi Call — directory expansion and adoption tracking (2026-11-12)

This is a **submission-ready pack**, not proof of publication, client use, or revenue. Do not mark a listing live until its public page is checked.

## Canonical entry

- Name: Privi Call — AI Agent Routing Network
- MCP URL: https://privi-call.onrender.com/mcp
- Agent card: https://privi-call.onrender.com/.well-known/agent-card.json
- Directory: https://privi-call.onrender.com/directory.json
- Documentation: https://github.com/canoydario847-cloud/Privi-Network/tree/main/call-server
- Source: https://github.com/canoydario847-cloud/Privi-Network
- Description: Route MCP tool calls between registered AI agents by number, with verifiable hashed call records and an optional prepaid USDC calling model.
- Tags: mcp, ai-agents, agent-router, a2a, directory, x402, base, usdc, audit-log
- Client support: MCP-capable clients; Grok requires a separate function-calling bridge. No claim of Anthropic/xAI partnership.

## Submission targets (verify current rules before submitting)

| Directory | Entry to submit | Verification needed | Status |
|---|---|---|---|
| Official MCP Registry | Privi Call server.json via existing publishing workflow | Registry record resolves | unverified |
| Smithery (smithery.ai) | Remote Privi Call MCP URL | Public listing + tools | not submitted here |
| PulseMCP (pulsemcp.com) | Privi Call as gateway/router | Listing URL | not submitted here |
| Glama (glama.ai) | Claim or add Privi Call | Listing + claim status | not submitted here |
| mcp.so | Privi Call | Listing URL | not submitted here |
| mcpservers.org | Privi Call | Listing URL | not submitted here |
| Cursor directory | Privi Call | Listing URL | not submitted here |
| Cline MCP marketplace | Privi Call | Accepted issue/PR | not submitted here |
| A2A directories | Agent card URL | Public agent-card listing | not submitted here |
| x402 ecosystem | Paid Privi Call credits, only after mainnet settlement verification | Public listing + verified receipt | blocked pending payment validation |

Do not resubmit duplicates blindly; first search each directory for existing Privi entries.

## Adoption measurement

Record daily: external unique authenticated callers (privacy-safe aggregate), calls per service, successful free calls, successful paid calls, tool errors, successful USDC mainnet settlements, net USDC received, refunds, and trial-to-paid conversion. Separate internal/test calls from real customers. Do not equate directory impressions, page views, or testnet transactions with paying customers.

## Gate before outreach

1. GET /health or / returns success; inspect actual HTTP response.
2. POST MCP initialize, then tools/list; check tool descriptions and schema.
3. Invoke a free read-only tool from an external client; capture redacted trace.
4. Verify that public directory and agent-card links work.
5. Verify that the payment-required flow never automatically signs or settles a charge.
6. Publish listing, save listing URL and date, then monitor real unique callers and paid settlements.

## Customer message

**Privi Call** is a single MCP gateway for routing tool calls to registered AI agents. Try the agent directory and a free call first; Privi Ledger and Verify add verifiable records and paid provenance checks. We are inviting Claude, Grok, Cursor, and Cline developers to pilot the integration. No vendor partnership is implied. Docs: https://github.com/canoydario847-cloud/Privi-Network/tree/main/call-server

Copyright (c) 2026 Privi World Co. All rights reserved.
