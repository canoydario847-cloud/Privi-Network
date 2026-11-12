# Claude + Grok adoption playbook (Privi Verify)

Owner: Privi World Co. Status: integration guide, **not evidence of adoption or revenue**.

## Claude: remote MCP

Privi Verify advertises a Streamable HTTP MCP endpoint at `https://privi-verify.onrender.com/mcp`. In a Claude client that supports remote MCP connectors, add this URL as a custom connector, then discover tools and invoke `privi_pricing` (free). Next call `privi_lookup_fingerprint` with a known demo fingerprint if available. The paid `privi_verify_lot` tool requires an x402-compatible payment flow; do not assume the Claude client signs x402 payments automatically. For Claude Code, configure the remote HTTP MCP server using its current supported MCP settings, then inspect the discovered tools.

## Grok: function-calling bridge

Grok's function-calling API does **not** automatically connect to arbitrary MCP endpoints. Build a server-side bridge under Privi's control that (1) defines narrow JSON-schema functions for pricing and verification, (2) receives Grok tool calls, (3) validates input, (4) invokes Privi MCP with the proper MCP session/transport and authentication, (5) returns structured results to the model. Keep xAI credentials server-side. Never expose write API keys or wallet signing keys to the model. Do not automatically approve payments.

Suggested function definitions:

- `privi_pricing()`: returns available tools and price schedule; no payment.
- `privi_verify_lot(lot_code: string)`: requires explicit customer payment authorization and a compatible x402 payment client before execution.

## Conversion funnel

1. Verify GET /health and MCP initialize + tools/list from an external network; capture timestamp, HTTP status, tool list and redacted trace.
2. Test Claude discovery and one free call; record success or failure.
3. Test Grok bridge with one free call; record success or failure.
4. Run a **testnet** paid call with explicit approval and capture transaction receipt. Do not label testnet transactions as revenue.
5. Publish an example, invite Claude and Grok developers to test it, and ask for permission before publishing customer names.
6. Only enable Base mainnet billing after wallet, facilitator, settlement, replay protections and refunds are independently checked.

## Metrics

Track by provider/client: successful calls, unique authenticated developers, error rate, payment-required responses, settled **mainnet** USDC payments, net USDC received and refunds. Treat vendor adoption by Anthropic or xAI as **unconfirmed** until independently documented.

## Current project entry points

- MCP service: `mcp-server/README.md`
- Call directory/gateway: `call-server/README.md`
- Guard Claude Code hook: `guard-sdk/hooks/claude-code`

Copyright (c) 2026 Privi World Co. All rights reserved.
