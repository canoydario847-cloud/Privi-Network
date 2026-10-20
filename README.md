# Privi Network

Verifiable infrastructure for AI agents — pay, prove, and audit on-chain. Built by **Dario Canoy**, Privi World Co, Port Huron, Michigan.

**For AI agents:** start at [https://privi-discovery-production.up.railway.app/llms.txt](https://privi-discovery-production.up.railway.app/llms.txt) · A2A card: [https://privi-discovery-production.up.railway.app/.well-known/agent.json](https://privi-discovery-production.up.railway.app/.well-known/agent.json) · MCP manifest: [https://privi-discovery-production.up.railway.app/.well-known/mcp.json](https://privi-discovery-production.up.railway.app/.well-known/mcp.json)

| Folder | What | MCP endpoint | Registry |
|---|---|---|---|
| `ledger-server/` | Privi Ledger — tamper-evident audit logs, compliance reports, Handshake, Gov AI inventory, Quantum-Ready | `https://privi-ledger-production.up.railway.app/mcp` | `io.github.canoydario847-cloud/privi-ledger` |
| `mcp-server/` | Privi Verify — paid manufacturing lot verification (x402, USDC on Base) | `https://privi-verify-production.up.railway.app/mcp` | `io.github.canoydario847-cloud/privi-verify` |
| `anchor-server/` | Privi Anchor — hash anchoring / proof-of-existence on the Privi chain | `https://privi-anchor-production.up.railway.app/mcp` | `io.github.canoydario847-cloud/privi-anchor` |
| `discovery/` | Discovery hub — agent card, MCP manifest, llms.txt, schema.org | `https://privi-discovery-production.up.railway.app` | — |
| `production-network/`, `jose-*` | Privi EVM chain (id 262144) and Jose Coin (JOSE) on Base | | |

Contact: see the discovery hub. Owner wallet: `0x1990589FD200E043b8C6FD9ec5956c61b3071048`. MIT licensed.
