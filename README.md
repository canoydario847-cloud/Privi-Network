# Privi: the trust layer for AI agents

[![Listed on mcpservers.org](https://mcpservers.org/badge.svg)](https://mcpservers.org/servers/canoydario847-cloud/privi-network)

## Privi World paid B2B services — available today

Privi World Corp offers three **human-delivered service engagements** with independently verified live Stripe Payment Links. These services are separate from Privi's not-yet-activated prepaid API-credit checkout:

| Service | Price (USD) | Learn more | Stripe purchase |
| --- | ---: | --- | --- |
| Privi Guard Security Review | $99 | [Service details](https://privi-services.onrender.com/ai-agent-security-review/) | [Stripe Checkout](https://buy.stripe.com/28EcN4gN510y0ot8ZQ6J201) |
| Privi Agent Evidence Review | $149 | [Service details](https://privi-services.onrender.com/agent-audit-evidence-review/) | [Stripe Checkout](https://buy.stripe.com/28E7sK7cvfVsgnr2Bs6J202) |
| Privi Enterprise Integration Consultation | $249 | [Service details](https://privi-services.onrender.com/enterprise-mcp-consultation/) | [Stripe Checkout](https://buy.stripe.com/28E28qcwP6kSc7b2Bs6J203) |

**[Compare all services and contact Privi →](https://privi-services.onrender.com/)** · **[Public sales one-pager and organic campaign](privi-business-services/README.md)** · [14 ready-to-share posts](privi-business-services/social-posts.md)

Buyers should confirm scope and deliverable expectations before paying if needed; after payment, respond to the Stripe receipt email with project details to arrange service delivery. These are not subscriptions, audited certifications, or automatic API-key purchases. The seller is Privi World Corp.

## Privi Agent Survival & Premium — prepaid AI-agent utility gateway

**51 new premium analyzers** plus 32 standard survival utilities available through a commercial MCP connector. The premium tools cover agent authorization, SLO/incident triage, data quality, API unit economics, procurement and release readiness. Premium calls cost **5 prepaid credits** and ordinary calls cost **1 credit**; tool discovery is public, but free execution will be disabled in the paid-only release.

- [Live agent hub](https://privi-ai-21-gateway.onrender.com/agent-hub) · [Premium catalog](https://privi-ai-21-gateway.onrender.com/premium.json) · [Pricing/checkout status](https://privi-ai-21-gateway.onrender.com/pricing)
- **Remote MCP:** `https://privi-ai-21-gateway.onrender.com/mcp` · **[Official MCP Registry v0.7.1 (verified)](https://registry.modelcontextprotocol.io/v0.1/servers/io.github.canoydario847-cloud%2Fprivi-agent-survival/versions/0.7.1)**.
- [Public MCP directory metadata and listing guide](privi-agent-survival/README.md).
- [32 Agent Skills](https://privi-ai-21-gateway.onrender.com/skills/index.json) · [Live 51-premium website](https://privi-premium-tools.onrender.com).

**Infrastructure caution:** Some legacy Privi MCP URLs listed below belong to an older Render workspace affected by billing suspension. In particular, `privi-ledger.onrender.com` is **not** the validated Ledger recovery endpoint. The replacement `privi-ledger-mcp-recovery.onrender.com` is evaluation-only with temporary storage and must not be used for durable audit evidence. Use the verified Agent Survival link above for its separate hosted gateway.

**Commercial status:** The three human-delivered review/consultation services above use existing active Stripe-hosted payment links. The separate automated API-credit checkout is not accepting payments while durable storage, Stripe webhook credentials/tax configuration, Base confirmation and fulfillment tests remain unverified. Do not transfer funds without a verified order. The commercial gateway is separate from Privi Ledger's existing plans.

Remote MCP servers that make AI agents safer and accountable, paid in USDC through [x402](https://x402.org) with free tiers.
Built by **Dario Canoy**, Privi World Co, Port Huron, Michigan. Live status of every service: **[Privi Hub](https://privi-hub.onrender.com)**.

```json
{ "mcpServers": {
    "privi-ledger": { "url": "https://privi-ledger.onrender.com/mcp" },
    "privi-verify": { "url": "https://privi-verify.onrender.com/mcp" },
    "privi-anchor": { "url": "https://privi-anchor.onrender.com/mcp" },
    "privi-quantum": { "url": "https://privi-quantum.onrender.com/mcp" },
    "privi-call": { "url": "https://privi-call.onrender.com/mcp" } } }
```

| Product | What it does | Start with |
|---|---|---|
| **Privi Guard** | Checks what an agent reads for prompt injection and what it sends for leaked keys, card numbers and personal data. Returns allow / warn / block with a signed receipt anchored on-chain. 1,000 checks a month free, then 1 cent. [Try it](https://privi-guard-814f.onrender.com) | `guard_check`, [`pip install privi-guard`](guard-sdk/python), [`npm i privi-guard`](guard-sdk/js), [Claude Code hook](guard-sdk/hooks/claude-code) |
| **Privi Scan** | Safety grades and tamper-evident tool history for every public MCP server in the official registry. Catches tool poisoning and rug pulls. [Directory](https://privi-ledger.onrender.com/scan) | `mcp_server_check` (free) |
| **Privi Ledger** | Tamper-evident audit logs for agent actions: a Merkle transparency log, post-quantum co-signatures and on-chain checkpoints | `ledger_signup`, `ledger_record_action` |
| **Passport / KYA / Mandates** | Verifiable trust scores for agents, wallet-to-agent binding, and human-signed spending limits | `passport_gate`, `kya_check`, `mandate_check` (free) |
| **Privi Live** | Kill switch, wallet-signed approvals, trust feed over WebSocket, a metered MCP gateway (optionally Guard-screened) and paid agent-to-agent rooms | `live_info`, `live_kill`, `gateway_create` |
| **Privi Verify** | Manufacturing lot verification and chain of custody, pay per call | `privi_verify_lot` |
| **Privi Anchor** | Proof of existence: anchor document or output hashes on Base while native Privi financial mainnet is not launched | `anchor_hashes`, `anchor_verify` (free) |

| Folder | Service | MCP endpoint | MCP Registry |
|---|---|---|---|
| `ledger-server/` | Ledger, Guard, Scan, Passport, KYA, Mandates, Live, Fortress, Gov | `https://privi-ledger.onrender.com/mcp` | `io.github.canoydario847-cloud/privi-ledger` |
| `mcp-server/` | Privi Verify | `https://privi-verify.onrender.com/mcp` | `io.github.canoydario847-cloud/privi-verify` |
| `anchor-server/` | Privi Anchor | `https://privi-anchor.onrender.com/mcp` | `io.github.canoydario847-cloud/privi-anchor` |
| `quantum-server/` | Privi Quantum (research optimization tools) | `https://privi-quantum.onrender.com/mcp` | `io.github.canoydario847-cloud/privi-quantum` (verify registry status) |
| `call-server/` | Privi Call (agent-call routing) | `https://privi-call.onrender.com/mcp` | `io.github.canoydario847-cloud/privi-call` (verify registry status) |
| `guard-sdk/` | Privi Guard clients (Python, JS) and Claude Code hook | — | PyPI / npm `privi-guard` |
| `discovery/` | Agent discovery: A2A card, MCP manifest, llms.txt | `https://privi-discovery.onrender.com` | — |
| `sites/` | Product websites and the Privi Hub | — | — |
| `production-network/`, `jose-*` | Privi EVM chain (id 262144) and Jose Coin (JOSE) on Base | | |

**For AI agents:** [llms.txt](https://privi-discovery.onrender.com/llms.txt) · [A2A card](https://privi-discovery.onrender.com/.well-known/agent.json) · [MCP manifest](https://privi-discovery.onrender.com/.well-known/mcp.json) · server cards at `/.well-known/mcp/server-card.json` on each server.

Contact: dariocanoy@priviflow.us. Owner wallet: `0x1990589FD200E043b8C6FD9ec5956c61b3071048`. MIT licensed.

**Base PRIVI token reference (separate asset):** [Contract identity, wallet import and market-verification links](https://www.privishine.info/base-token.html) (on-chain state and trading availability must be checked). This is not the native PRVI mainnet coin or the separate BNB PRIV token.
