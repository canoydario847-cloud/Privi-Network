# Privi Ledger MCP

**Tamper-evident audit logs for AI agents.** Every company running agents needs to prove what those agents did: what data they touched, what they paid for, what they changed, and that nobody rewrote the record afterwards. Privi Ledger gives any MCP-capable agent a place to log each action, and gives auditors a way to verify the log, paid per check in USDC on Base via [x402](https://github.com/x402-foundation/x402).

Works with Claude, ChatGPT, Cursor, VS Code and custom agents. Built by [Privi World Co](https://github.com/canoydario847-cloud) on the same record technology as [Privi Verify](../mcp-server).

**Live (testnet):** `https://privi-ledger-production.up.railway.app/mcp`

## Tools

| Tool | Access | What it does |
|---|---|---|
| `ledger_pricing` | free | Prices, network, action types, how to get a key |
| `ledger_check_receipt` | free | Confirms an action receipt (`entry_hash`) exists and when; reveals no contents |
| `ledger_audit_stream` | $0.02 (x402) | Integrity audit of an agent's log: intact or not, where it broke, counts, time span, head hash. No action contents |
| `ledger_record_action` | org key | Append an action; returns the entry and its `entry_hash` receipt |
| `ledger_read_stream` | org key | Read your own entries with an integrity check |
| `ledger_list_streams` | org key | Your streams and entry counts |
| `ledger_compliance_report` | org key | Audit-ready report of agent activity for a period, sealed on the Privi chain |
| `ledger_report_pdf` | org key | The sealed report as a finished PDF (also at `GET /reports/<id>.pdf` with the org key) |
| `ledger_handshake_offer` / `_accept` / `_reject` / `_inbox` | org key | Privi Handshake: two-sided records of dealings between companies |
| `ledger_handshake_verify` | free | Public check of a handshake and its on-chain seal; never reveals terms |
| `ledger_verify_report` | free | Proves a report is unaltered and was issued by Privi Ledger; checks its on-chain seal |

Action types: `tool_call`, `data_access`, `data_change`, `payment`, `message`, `decision`, `approval`, `error`, `other`. Outcomes: `success`, `failure`, `pending`, `blocked`.

## How the log stays honest

Each entry's SHA-256 fingerprint covers its contents **and the previous entry's fingerprint** in the same stream. Editing, deleting or reordering any entry breaks the chain from that point, and audits report the exact entry where it broke. Organizations only ever see their own streams; API keys are stored as hashes.

> Stream heads are anchored on the Privi blockchain every few minutes (see On-chain checkpoints), so integrity can be proven without trusting Privi.

## Plans (self-serve)

| Plan | How | Includes |
|---|---|---|
| Free | `ledger_signup` (no key needed) | Every tool, up to 500 entries per month |
| Pro | `ledger_upgrade_pro`, $29 USDC per 30 days via x402 | Unlimited entries; each payment adds 30 days |
| Enterprise | Created by Privi (`/admin/orgs`) | Unlimited; billed by agreement |

Any company, or an AI agent acting for one, can sign up, start logging, and upgrade without talking to anyone. Payments go straight to `LEDGER_PAY_TO`, and each purchase is recorded in the organization's own `privi-billing` stream. `ledger_plan` shows usage and renewal. Set `LEDGER_FREE_MONTHLY` and `LEDGER_PRICE_PRO_MONTH` to change the limits.

## Onboarding a customer

Create an organization with the admin key (set `LEDGER_ADMIN_KEY`):

```bash
curl -X POST https://<host>/admin/orgs \
  -H "Authorization: Bearer $LEDGER_ADMIN_KEY" -H 'Content-Type: application/json' \
  -d '{"name": "Acme Robotics"}'
# -> {"org_id": "org_...", "api_key": "plk_...", ...}  (the key is shown once)
```

The customer adds the server to their agent with header `Authorization: Bearer plk_...`, and tells it to call `ledger_record_action` after each meaningful action. They share their `org_id` and stream names with auditors, who call `ledger_audit_stream`.

## Compliance reports

`ledger_compliance_report` turns an organization's agent logs into evidence for SOC 2 reviews, customer security questionnaires and AI-regulation record keeping. For any period it reports actions by type, actors, failures, blocked actions, human approvals, log integrity and on-chain status. It also lists **findings** an auditor would raise, such as broken integrity, logs not yet anchored, failed actions, or payments and data changes with no human approval recorded. The result comes as JSON plus a ready-to-share Markdown version.

Each report is **sealed**. Its SHA-256 hash, taken over canonical JSON, is anchored on the Privi blockchain through Privi Anchor. Anyone holding the report can run `ledger_verify_report`, which recomputes the hash, confirms Privi Ledger issued exactly that content, and checks the anchor on chain. Editing even one number, such as hiding a failure, makes verification fail.

## Privi Handshake

A dealing between two companies, such as a payment, a data transfer, a delivery or an agreement, gets recorded by **both** of them, with neither able to deny or rewrite it alone.

1. Company A's agent calls `ledger_handshake_offer` with the other company's `org_id` and the terms. A's log records the offer.
2. Company B's agent sees it in `ledger_handshake_inbox` and calls `ledger_handshake_accept`, or `ledger_handshake_reject` with a reason.
3. On acceptance, B's log records the same terms with A's entry hash, A's log records the confirmation with B's entry hash, and a pair hash binding the terms and both entries is anchored on the Privi blockchain.
4. Anyone can run `ledger_handshake_verify` to see both parties, the status, whether both entries still exist, and the on-chain seal, without seeing the terms.

Handshakes only work between organizations on Privi Ledger.

## On-chain checkpoints

Every 5 minutes the server anchors the latest fingerprint of each stream that changed on the Privi blockchain through [Privi Anchor](../anchor-server). Audit results include `onchain_checkpoint`: the anchored position, transaction, and Merkle proof, plus an `anchor_verify` call anyone can run. If stored history no longer matches what was anchored, the audit fails even when every local hash was recomputed consistently. Set `LEDGER_ANCHOR_KEY` (an Anchor API key) to turn it on; `LEDGER_ANCHOR_INTERVAL` changes the period (seconds, default 300).

## Payments

Same x402 v2 MCP flow as Privi Verify: an unpaid call returns `PaymentRequired`; the agent retries with a signed USDC authorization in `_meta["x402/payment"]`; the server verifies, runs the audit, settles, and returns the receipt in `_meta["x402/payment-response"]`. Funds go straight to `LEDGER_PAY_TO`.

## Run, test, deploy

```bash
pip install -e ".[dev]"
cp .env.example .env
pytest
privi-ledger-mcp            # HTTP :8000, MCP at /mcp
privi-ledger-mcp --stdio    # local clients; set LEDGER_LOCAL_ORG_KEY
```

The `Dockerfile` runs on Railway with a volume at `/data`. Start on `base-sepolia`; switch to `base` only with a production facilitator.

## Roadmap

- Subscription billing per organization
- Retention policies and exports to customer storage

## License

MIT © 2026 Dario Canoy, Privi World Co
