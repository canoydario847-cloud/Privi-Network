# Privi MCP servers: filled-out directory submissions (2026-11-15)

All six servers are live on the **official MCP Registry** (publish run #54, 2026-11-15 19:47 UTC, all jobs green).
Anything that indexes the official registry (PulseMCP, GitHub MCP page, some aggregators) picks them up on its own.

Everything below is copy-paste ready for the directories that need a human sign-in, a form or a pull request.
Endpoints are the current ones from `*/server.json` on `main` (after #297).

Shared fields (same for every form):

- **Maintainer / author:** Privi World Co (Dario Canoy), dariocanoy@priviflow.us
- **GitHub repo:** https://github.com/canoydario847-cloud/Privi-Network
- **License:** see repo `LICENSE`
- **Transport:** Streamable HTTP (remote, hosted)
- **Pricing:** Paid. Buy page https://privi-hub.onrender.com/pay/ (USDC on Base, or invoice). No free tier.
- **Logo:** `assets/` in the repo (Cline needs a 400x400 PNG)

---

## 1. Per-server form values

### Privi Quantum
- Registry ID: `io.github.canoydario847-cloud/privi-quantum` (v0.13.1)
- URL: `https://privi-quantum-vvmj.onrender.com/mcp`
- Source: `quantum-server/`
- Short description (≤100 chars): Quantum on IonQ/IBM/Braket: spending mandates, signed benchmarks, paid PQC CBOM, advantage receipts.
- Long description: Remote MCP server for agents working with quantum hardware and post-quantum cryptography. It runs jobs on IonQ, IBM and Amazon Braket under spending mandates, returns signed benchmark and advantage receipts, and produces a paid post-quantum cryptography bill of materials (CBOM). It also includes `genius_stablecoin_check`, which checks a stablecoin's GENIUS Act issuer status and latest sealed reserve report ($0.01 per call).
- Categories/tags: security, cryptography, post-quantum, quantum computing, compliance, stablecoin, x402

### Privi Verify
- Registry ID: `io.github.canoydario847-cloud/privi-verify` (v0.5.1)
- URL: `https://privi-verify-s4jb.onrender.com/mcp`
- Source: `mcp-server/`
- Short description: Manufacturing lot verification and chain of custody for AI agents, paid per call in USDC (x402).
- Categories/tags: manufacturing, supply chain, verification, provenance, x402, USDC

### Privi Anchor
- Registry ID: `io.github.canoydario847-cloud/privi-anchor` (v0.5.1)
- URL: `https://privi-anchor-zsbk.onrender.com/mcp`
- Source: `anchor-server/`
- Short description: Hash anchoring and proof-of-existence on chain for AI agents and apps. Paid API key required.
- Categories/tags: blockchain, timestamping, proof-of-existence, audit, Base

### Privi Call
- Registry ID: `io.github.canoydario847-cloud/privi-call` (v0.3.1)
- URL: `https://privi-call-e3rb.onrender.com/mcp`
- Source: `call-server/`
- Short description: One number per AI agent: route MCP calls to any agent, every call sealed in an on-chain log.
- Categories/tags: agent-to-agent, routing, communication, audit log

### Privi Agent Survival & Premium
- Registry ID: `io.github.canoydario847-cloud/privi-agent-survival` (v0.7.1)
- URL: `https://privi-ai-21-gateway.onrender.com/mcp`
- Website: https://privi-ai-21-gateway.onrender.com/agent-hub
- Source: `privi-agent-survival/`
- Short description: 32 agent utilities and 51 premium analyzers. API key required; automated checkout not active.
- Categories/tags: agent reliability, developer tools, security, data quality, observability

### Privi Ledger (recovery evaluation)
- Registry ID: `io.github.canoydario847-cloud/privi-ledger` (v0.14.2)
- URL: `https://privi-ledger-aqe5.onrender.com/mcp`
- Short description: Evaluation-only ledger MCP. Temporary storage; not durable audit evidence. Payments disabled.
- Note: its own metadata says evaluation-only, so **don't list it in paid directories** until the durable Ledger is back.

Connector JSON (swap the URL per server):

```json
{
  "mcpServers": {
    "privi-quantum": { "url": "https://privi-quantum-vvmj.onrender.com/mcp" }
  }
}
```

---

## 2. Directory by directory

| # | Directory | How | What to paste |
|---|---|---|---|
| 1 | Official MCP Registry | done (CI) | — |
| 2 | mcpservers.org | already lists Anchor + Ledger; submit the rest at https://mcpservers.org/en/submit | Name, GitHub subfolder URL, short description from section 1 |
| 3 | Glama | sign in with GitHub at https://glama.ai/mcp/servers, "Add server", point at the repo (`glama.json` is already in the root) | Repo URL; claim with `canoydario847-cloud` |
| 4 | mcp.so | https://mcp.so/submit (GitHub sign-in) | Name, repo subfolder URL, short + long description, tags |
| 5 | Smithery | https://smithery.ai/new: "Deploy/Add remote server" with an external URL | Server URL; name and description from section 1 |
| 6 | MCP Market | https://mcpmarket.com/submit | Repo URL + description |
| 7 | mcp.directory | site submit form | Repo URL + description |
| 8 | LobeHub | https://lobehub.com/mcp → Submit | Repo URL |
| 9 | cursor.directory | https://cursor.directory/mcp → Submit (GitHub sign-in) | Name, connector JSON, description |
| 10 | Cline Marketplace | new issue at https://github.com/cline/mcp-marketplace/issues/new/choose | Text in section 3, plus 400x400 PNG |
| 11 | punkpeye/awesome-mcp-servers | fork, add a line under "Security" (Quantum) and "Developer Tools" (Agent Survival), open PR | Lines in section 4 |
| 12 | punkpeye/awesome-remote-mcp-servers | same, remote list | Lines in section 4 |
| 13 | Docker MCP Catalog | PR to https://github.com/docker/mcp-registry using their remote-server wizard (`task wizard`) | URL, name, description; no secrets in the PR |
| 14 | Kilo Marketplace | PR adding `mcps/privi-agent-survival/MCP.yaml` (already prepared in `privi-agent-survival/submissions/kilo-marketplace/`) | that file, URL updated |
| 15 | TensorBlock awesome-mcp-servers | "Add MCP Server" issue form | `privi-agent-survival/submissions/tensorblock-entry.md` |

---

## 3. Cline marketplace issue text

**Title:** Add Privi Quantum (remote MCP: PQC CBOM, quantum jobs, GENIUS stablecoin check)

**Body:**

- Repo: https://github.com/canoydario847-cloud/Privi-Network/tree/main/quantum-server
- Remote URL: https://privi-quantum-vvmj.onrender.com/mcp (Streamable HTTP)
- Official MCP Registry: io.github.canoydario847-cloud/privi-quantum
- What it does: runs quantum jobs on IonQ, IBM and Braket under spending mandates; signed benchmark and advantage receipts; paid post-quantum cryptography bill of materials; `genius_stablecoin_check` for stablecoin issuer status.
- Pricing: paid (USDC on Base or invoice), https://privi-hub.onrender.com/pay/
- Setup: add the connector JSON above to Cline's MCP settings; paid tools need a key from the buy page.
- Logo: attached (400x400 PNG)

---

## 4. awesome-list lines

```
- [canoydario847-cloud/Privi-Network (Privi Quantum)](https://github.com/canoydario847-cloud/Privi-Network/tree/main/quantum-server) ☁️ - Remote MCP for post-quantum cryptography inventories (CBOM), quantum jobs on IonQ/IBM/Braket with signed receipts, and GENIUS Act stablecoin issuer checks. Paid.
- [canoydario847-cloud/Privi-Network (Privi Agent Survival)](https://github.com/canoydario847-cloud/Privi-Network/tree/main/privi-agent-survival) ☁️ - Remote MCP gateway with 32 agent reliability utilities and 51 premium analyzers. API key required.
- [canoydario847-cloud/Privi-Network (Privi Anchor)](https://github.com/canoydario847-cloud/Privi-Network/tree/main/anchor-server) ☁️ - On-chain hash anchoring and proof-of-existence for agents. Paid API key.
```

(punkpeye's list asks for the Glama badge after Glama indexes the server. Do step 3 first.)
