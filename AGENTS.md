# AGENTS.md — how AI agents work in the Privi-Network repo

Read this first. It applies to every agent (Claude Code, Codex, Cursor, subagents) that changes this repo.
Owner: **Dario Canoy**, founder and sole principal of **Privi World Co**, Port Huron, Michigan ·
dariocanoy@priviflow.us · owner wallet `0x1990589FD200E043b8C6FD9ec5956c61b3071048`.

## What Privi is building

Privi is the trust layer for AI agents: remote MCP servers paid in USDC over x402, with every
important record sealed in a hash chain and anchored on chain. Two long-range bets sit on top of it,
each with its own playbook for agents:

| Bet | Playbook | Starts from |
|---|---|---|
| **Privi Call carrier** — a real phone company: Privi phone numbers, calling for people and AI agents, a sealed call log | [`company/telecom/`](company/telecom/README.md) | `call-server/` (live at privi-call.onrender.com) |
| **Privi Quantum Network** — quantum-safe links today, quantum key distribution and entanglement services as the hardware matures | [`company/quantum-networking/`](company/quantum-networking/README.md) | `quantum-server/` (live at privi-quantum.onrender.com) |

Company-wide context, people, accounts and decisions: [`company/README.md`](company/README.md).

## Repo map

| Folder | Service | Live URL (Render) |
|---|---|---|
| `ledger-server/` | Ledger, Guard, Scan, Passport, KYA, Mandates, Live, Fortress, Gov | privi-ledger.onrender.com |
| `mcp-server/` | Privi Verify (manufacturing lots) | privi-verify.onrender.com |
| `anchor-server/` | Privi Anchor (hash anchoring) | privi-anchor.onrender.com |
| `call-server/` | Privi Call (agent call network + phone line) | privi-call.onrender.com |
| `quantum-server/` | Privi Quantum (QAOA, ML-DSA-87 attestations, PQC scan) | privi-quantum.onrender.com |
| `discovery/` | A2A card, MCP manifest, llms.txt | privi-discovery.onrender.com |
| `sites/` | Product websites (built by `sites/build.py`) | priviflow.us subdomains |
| `guard-sdk/` | Python/JS clients and Claude Code hook | PyPI / npm |
| `production-network/` | Privi EVM chain (id 262144) | devnet |
| `render.yaml` | Render Blueprint for every service | — |

## Rules that are not negotiable

1. **Deploy on Render only.** Never deploy to Railway. New services go in `render.yaml` with a disk if they keep state.
2. **Work through pull requests.** Branch from `main`, open a PR, let Dario merge. Never push to `main`.
3. **Secrets never enter git.** Keys go in Render env vars (`sync: false` in `render.yaml`) or the
   `privi-coinbase-cdp` env group. Commit only `.env.example` files.
4. **Ask Dario before anything that spends money, signs a contract, files with a regulator, buys a
   phone number, ports a number, sends email on his behalf, or moves funds.** Prepare the work, then stop.
   The telecom and quantum playbooks list these stopping points.
5. **Branding.** New products are "Privi <Name>", a Privi World Co product.
   New service code carries `Copyright (c) 2026 Privi World Co. All rights reserved.` and the proprietary
   LICENSE used in `call-server/` and `quantum-server/` (the repo root stays MIT for existing code).
6. **Honest claims.** No claim of quantum advantage, carrier status, licences, certifications or
   customers that Privi does not have. Say what is a prototype.
7. **Seal what matters.** Records customers rely on go into a hash-chained store and are anchored through
   Privi Anchor every 5 minutes (see `call-server/src/privi_call/anchoring.py` for the pattern).
8. **Personal data.** Phone numbers, transcripts and call content appear publicly only as SHA-256 hashes
   or masked (`***-1234`). Full data stays behind an admin key.

## How each service is built (copy this shape)

- Python 3.11+, `pyproject.toml`, `src/<package>/`, `tests/` with pytest, a `Dockerfile`.
- FastMCP server on `/mcp` (streamable HTTP), plus `/health`, `/status`, a landing page, and discovery files
  (`/.well-known/agent-card.json`, `/.well-known/mcp/server-card.json`, `/llms.txt`).
- `server.json` for the official MCP Registry (`io.github.canoydario847-cloud/<name>`); bump its version
  to republish (`.github/workflows/mcp-registry-publish.yml`).
- Paid tools use x402 USDC on Base through the Coinbase CDP facilitator; sales stay closed until CDP keys exist.
- Add the service to `discovery/manifest.json` and to the README tables.

## Before you open a PR

- `pytest` passes in every folder you touched.
- `render.yaml` parses and new env vars are documented in the service README.
- The relevant `BACKLOG.md` item is ticked or updated, and any decision Dario must make is listed in the PR
  under **Needs Dario**.

## Specialist agents

Ready-made definitions live in [`.claude/agents/`](.claude/agents/): `telecom-engineer`,
`telecom-compliance`, `quantum-network-engineer`, `privi-reviewer`.
