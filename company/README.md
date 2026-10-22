# Privi World Co — company context for agents

## People and contact

- **Dario Canoy** — founder and sole principal. Decides everything that spends money, signs, files or ships to `main`.
- Public email: dariocanoy@priviflow.us · Phone (forwarding target of the Privi line): +1 313-413-8532
- Mailing address: 1920 24th St, Port Huron, MI 48060 (St. Clair County, Michigan)

## Accounts and infrastructure

| What | Where | Notes |
|---|---|---|
| Code | GitHub `canoydario847-cloud/Privi-Network`, `canoydario847-cloud/Privi-DAO` | PRs only |
| Hosting | Render (Pro workspace), Blueprint `render.yaml` | Railway is frozen; do not deploy there |
| Domain | priviflow.us (DNS at IONOS, Google Workspace email) | Up to 15 custom domains on Render |
| Payments | x402 USDC on Base via Coinbase CDP facilitator | Pay-to: owner wallet |
| Chain | Base for the PRIVI token and anchors until the Privi chain mainnet; Privi EVM devnet id 262144 | |
| Voice | Twilio (phone line webhooks in `call-server/`) | Number purchase is Dario's |
| Discovery | MCP Registry, discovery hub, IndexNow | Directory sign-ins are Dario's |

## Funding in motion (autumn 2026)

Raising a $50K pre-seed. Applications: NSF SBIR Project Pitch, Alliance DAO (submitted); Michigan Rise
Pre-Seed Fund III, Techstars Anywhere (apply by Nov 18, 2026 per Dario's notes), a Midwest accelerator.
The telecom and quantum playbooks each list grants that fit (see their `FUNDING` sections).

## Playbooks

- [`telecom/`](telecom/README.md) — Privi Call becomes a phone company.
- [`quantum-networking/`](quantum-networking/README.md) — Privi Quantum Network.
- [`templates/AGENT_TASK.md`](templates/AGENT_TASK.md) — how to write a task an agent can pick up cold.
- [`DECISIONS.md`](DECISIONS.md) — decisions Dario has made, newest first. Agents append; never rewrite.
