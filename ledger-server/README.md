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

Action types: `tool_call`, `data_access`, `data_change`, `payment`, `message`, `decision`, `approval`, `error`, `other`. Outcomes: `success`, `failure`, `pending`, `blocked`.

## How the log stays honest

Each entry's SHA-256 fingerprint covers its contents **and the previous entry's fingerprint** in the same stream. Editing, deleting or reordering any entry breaks the chain from that point, and audits report the exact entry where it broke. Organizations only ever see their own streams; API keys are stored as hashes.

> Today the fingerprints are checked against this server's database. Anchoring stream heads on Base, so customers can prove integrity without trusting Privi, is next on the roadmap.

## Onboarding a customer

Create an organization with the admin key (set `LEDGER_ADMIN_KEY`):

```bash
curl -X POST https://<host>/admin/orgs \
  -H "Authorization: Bearer $LEDGER_ADMIN_KEY" -H 'Content-Type: application/json' \
  -d '{"name": "Acme Robotics"}'
# -> {"org_id": "org_...", "api_key": "plk_...", ...}  (the key is shown once)
```

The customer adds the server to their agent with header `Authorization: Bearer plk_...`, and tells it to call `ledger_record_action` after each meaningful action. They share their `org_id` and stream names with auditors, who call `ledger_audit_stream`.

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

- Anchor stream heads on Base for trustless verification
- Signed audit reports (PDF/JSON) for compliance reviews
- Subscription billing per organization
- Retention policies and exports to customer storage

## License

MIT © 2026 Dario Canoy, Privi World Co
