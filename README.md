# Privi: the trust layer for AI agents

Remote MCP servers that make AI agents safer and accountable, paid in USDC through [x402](https://x402.org) with free tiers.
Built by **Dario Canoy**, Privi World Co, Port Huron, Michigan. Live status of every service: **[Privi Hub](https://privi-hub.onrender.com)**.

```json
{ "mcpServers": {
    "privi-ledger": { "url": "https://privi-ledger.onrender.com/mcp" },
    "privi-verify": { "url": "https://privi-verify.onrender.com/mcp" },
    "privi-anchor": { "url": "https://privi-anchor.onrender.com/mcp" } } }
```

| Product | What it does | Start with |
|---|---|---|
| **Privi Guard** | Checks what an agent reads for prompt injection and what it sends for leaked keys, card numbers and personal data. Returns allow / warn / block with a signed receipt anchored on-chain. 1,000 checks a month free, then 1 cent. [Try it](https://privi-guard-814f.onrender.com) | `guard_check`, [`pip install privi-guard`](guard-sdk/python), [`npm i privi-guard`](guard-sdk/js), [Claude Code hook](guard-sdk/hooks/claude-code) |
| **Privi Scan** | Safety grades and tamper-evident tool history for every public MCP server in the official registry. Catches tool poisoning and rug pulls. [Directory](https://privi-ledger.onrender.com/scan) | `mcp_server_check` (free) |
| **Privi Ledger** | Tamper-evident audit logs for agent actions: a Merkle transparency log, post-quantum co-signatures and on-chain checkpoints | `ledger_signup`, `ledger_record_action` |
| **Passport / KYA / Mandates** | Verifiable trust scores for agents, wallet-to-agent binding, and human-signed spending limits | `passport_gate`, `kya_check`, `mandate_check` (free) |
| **Privi Live** | Kill switch, wallet-signed approvals, trust feed over WebSocket, a metered MCP gateway (optionally Guard-screened) and paid agent-to-agent rooms | `live_info`, `live_kill`, `gateway_create` |
| **Privi Verify** | Manufacturing lot verification and chain of custody, pay per call | `privi_verify_lot` |
| **Privi Anchor** | Proof of existence: anchor any hash on the Privi chain | `anchor_hashes`, `anchor_verify` (free) |

| Folder | Service | MCP endpoint | MCP Registry |
|---|---|---|---|
| `ledger-server/` | Ledger, Guard, Scan, Passport, KYA, Mandates, Live, Fortress, Gov | `https://privi-ledger.onrender.com/mcp` | `io.github.canoydario847-cloud/privi-ledger` |
| `mcp-server/` | Privi Verify | `https://privi-verify.onrender.com/mcp` | `io.github.canoydario847-cloud/privi-verify` |
| `anchor-server/` | Privi Anchor | `https://privi-anchor.onrender.com/mcp` | `io.github.canoydario847-cloud/privi-anchor` |
| `guard-sdk/` | Privi Guard clients (Python, JS) and Claude Code hook | — | PyPI / npm `privi-guard` |
| `discovery/` | Agent discovery: A2A card, MCP manifest, llms.txt | `https://privi-discovery.onrender.com` | — |
| `sites/` | Product websites and the Privi Hub | — | — |
| `production-network/`, `jose-*` | Privi EVM chain (id 262144) and Jose Coin (JOSE) on Base | | |

**For AI agents:** [llms.txt](https://privi-discovery.onrender.com/llms.txt) · [A2A card](https://privi-discovery.onrender.com/.well-known/agent.json) · [MCP manifest](https://privi-discovery.onrender.com/.well-known/mcp.json) · server cards at `/.well-known/mcp/server-card.json` on each server.

Contact: dariocanoy@priviflow.us. Owner wallet: `0x1990589FD200E043b8C6FD9ec5956c61b3071048`. MIT licensed.
