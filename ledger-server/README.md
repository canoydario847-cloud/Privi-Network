# Privi Ledger MCP

**Tamper-evident audit logs for AI agents.** Every company running agents needs to prove what those agents did: what data they touched, what they paid for, what they changed, and that nobody rewrote the record afterwards. Privi Ledger gives any MCP-capable agent a place to log each action, and gives auditors a way to verify the log, paid per check in USDC on Base via [x402](https://github.com/x402-foundation/x402).

Works with Claude, ChatGPT, Cursor, VS Code and custom agents. Built by [Privi World Co](https://github.com/canoydario847-cloud) on the same record technology as [Privi Verify](../mcp-server).

**Live (testnet):** `https://privi-ledger.onrender.com/mcp`

## Tools

Real-time tools (`live_*`, `approval_*`, `trust_events`, `gateway_*`, `room_*`) are described under *Privi Live* below.

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

## Privi Gov AI Inventory (OMB M-25-21)

Federal agencies must keep an inventory of their AI use cases, publish the releasable ones as a machine-readable file, and show minimum risk practices for high-impact AI. That requirement comes from OMB Memorandum M-25-21 and OMB's guidance on 2025 agency AI reporting. Privi Ledger covers the whole loop:

| Tool | What it does |
|---|---|
| `gov_ai_usecase_save` | Add or update a use case in the guidance's reporting fields. Every change is a new version, written to the agency's tamper-evident `ai-inventory` log |
| `gov_ai_inventory` | Current inventory |
| `gov_ai_inventory_check` | Flags what a review would flag: missing required fields, PII without a Privacy Impact Assessment, and high-impact AI in pilot or deployment missing any minimum practice (testing, impact assessment, independent review, monitoring, operator training, fail-safe, appeals, public feedback) or without a recently active activity log as monitoring evidence. Practices waived by a written CAIO determination are respected |
| `gov_ai_inventory_export` | CSV of releasable use cases for agency.gov/ai, with its SHA-256 sealed on the Privi chain |
| `gov_ai_verify_export` (free) | Proves a published inventory file is exactly what the agency exported |

The inventory links to agents' Privi Ledger activity logs (`monitoring_streams`), so "ongoing monitoring" is backed by real, tamper-evident records.

> Field names follow OMB's published reporting fields. Confirm them against OMB's current template before submitting. This tool supports compliance work; it is not legal advice or an OMB-approved system.

## Privi Quantum-Ready (post-quantum migration)

Executive Order 14409 (June 2026) requires federal key establishment to move to post-quantum cryptography by **Dec 31, 2030**, and digital signatures by **Dec 31, 2031**. OMB M-26-15 asks every agency for a migration plan built on a cryptographic inventory (CBOM), prioritizing High Value Assets, high-impact systems and data that must stay sensitive past 2030, plus TLS 1.3 support by Jan 2, 2030.

| Tool | What it does |
|---|---|
| `gov_pqc_classify` (free) | Classifies algorithms and cipher suites: quantum-vulnerable (RSA, ECDH, ECDSA, EdDSA, DH, DSA, MQV), post-quantum (ML-KEM, ML-DSA, SLH-DSA), hybrid, symmetric/hash, or unknown |
| `gov_pqc_system_save` | Records one system's cryptographic assets (from people, scanners or agents). Versioned and written to a tamper-evident `pqc-inventory` log |
| `gov_pqc_inventory` | Current inventory |
| `gov_pqc_plan` | Ranked migration queue with per-asset deadlines and NIST replacements, progress metrics, and findings: targets past the deadline, TLS below 1.3, priority assets with no target date, unrecognized algorithms |
| `gov_pqc_export` | The CBOM plus plan as one JSON document, sealed on the Privi chain |
| `gov_pqc_verify_export` (free) | Proves an exported document is unaltered |

> The rules follow public summaries of EO 14409 and OMB M-26-15. Confirm them against the official texts and NIST IR 8547 before relying on them. This tool supports compliance work; it is not legal advice.

## Privi Passport (trust credentials for AI agents)

The feature no one else can copy: a **signed, on-chain-anchored credential that says how much an AI agent can be trusted**, scored 0-1000 from evidence only Privi Ledger holds.

| Component | Max | Evidence |
|---|---|---|
| history | 300 | verified entries and days of activity |
| integrity | 250 | every hash chain still verifies (all or nothing) |
| anchoring | 150 | share of streams whose on-chain checkpoint matches the record |
| reliability | 100 | 1 - failure rate |
| oversight | 50 | human approvals on sensitive actions |
| compliance | 100 | a sealed compliance report exists and is clean |
| handshakes | 50 | deals other Privi organizations confirmed |

Grades: A >= 850, B >= 700, C >= 550, D >= 400, E below. Valid 30 days.

- `passport_issue` (org key; free on Pro/enterprise, `$LEDGER_PRICE_PASSPORT` via x402 on the free plan) - Ed25519-signed by the server, hash anchored on the Privi chain, every component itemised.
- `passport_verify` (free) - signature, content, expiry, revocation, chain anchor, **and a live re-score**: if the agent's history is tampered with after issue, the passport fails.
- `passport_gate` (free) - one-call allow/deny with your minimums (`min_score`, `min_grade`, `require_anchored`); send your own key and the decision is written to your log as due-diligence evidence.
- `passport_list`, `passport_revoke` (org key).
- Public: `GET /passports/<id>` (JSON + live verification), `GET /passports/<id>/badge.svg` (embeddable badge), `GET /.well-known/privi-passport.json` (issuer public key).

Why it compounds: agents that gate on passports push their counterparties onto Privi Ledger; every logged action, report and handshake raises the score; a better score wins more deals. Set `LEDGER_PASSPORT_SIGNING_KEY` (32-byte hex Ed25519 seed) to pin the issuer key across redeploys; otherwise one is generated and stored in the database.

## Privi KYA (Know-Your-Agent for blockchain wallets)

As AI agents become the main senders of on-chain transactions, every chain, DeFi protocol, exchange, stablecoin issuer and x402 facilitator needs one answer before accepting a transaction: **is this wallet operated by an audited agent, and how trustworthy is it right now?** Privi KYA answers it, and only Privi can, because the answer is the Passport.

- `kya_challenge` + `kya_bind_wallet` (org key) - bind a wallet to your Passport by signing a Privi challenge **with the wallet** (EIP-191 personal_sign, recovered in pure Python; no web3 dependency). A binding without a signature is only *declared*.
- `kya_check <address>` (free) - resolves the wallet to its organization and live Passport; returns allow/deny with reasons, the current score and grade, and a **Privi-signed KYA attestation valid 60 minutes** that a facilitator can cache and verify offline. Send your key and the decision is logged as evidence.
- `kya_wallets`, `kya_unbind_wallet` (org key) - rotated or compromised keys are denied immediately.
- **Connect wallet page:** `GET /kya/connect` — paste the org key, connect MetaMask, sign once; done. No code needed.
- Public: `GET /kya/<address>` (JSON verdict + attestation; `?min_score=&min_grade=&require_signed=`), `GET /kya/<address>/badge.svg`.

Integration pattern for a chain or protocol: before accepting an agent transaction, `GET /kya/<from>`; require `allow: true` (and optionally `proof: "signature"`); keep the `attestation` + `signature` as your compliance record.

## Privi Fortress (defense-grade integrity controls)

Engineering controls aligned with CNSA 2.0 and NIST SP 800-53 (AU-9 protection of audit information, AU-10 non-repudiation, AC-5 separation of duties, SC-13 cryptographic protection). They are not a certification (no FIPS 140-3 validation, FedRAMP or DoD Impact Level authorization is claimed).

- **Post-quantum co-signatures.** Passports, compliance reports, mandates, KYA and mandate attestations, tree heads and evidence bundles are signed with Ed25519 **and ML-DSA-87** (NIST FIPS 204; the CNSA 2.0 parameter set). Keys: `fortress_keys`, `/.well-known/privi-passport.json`. Pin the seed with `LEDGER_PQ_SIGNING_KEY` (32-byte hex) or one is generated and stored.
- **Transparency log.** Every entry from every organization is a leaf in one RFC 9162 Merkle tree (the Certificate Transparency design). `ledger_tree_head` returns a dual-signed tree head, anchored on the Privi chain every `LEDGER_STH_INTERVAL` seconds (default 900); `ledger_inclusion_proof` proves an entry is in the log and `ledger_consistency_proof` proves the log only grew between two heads. HTTP: `/log/sth`, `/log/inclusion?hash=`, `/log/consistency?first=&second=`. All free.
- **Two-Person Integrity.** `fortress_tpi_policy` names the officers' wallets and how many must approve (at least 2). `fortress_tpi_request` returns an approval page (`/tpi/<id>`); each officer signs with their own wallet, the same officer cannot approve twice, outsiders are refused, and any officer can veto. `fortress_tpi_execute` consumes the authorization once. Every step is logged.
- **Air-gapped evidence bundles.** `ledger_evidence_bundle` exports entries, the hash chain, an inclusion proof, the signed tree head, the on-chain checkpoint and Privi's keys, dual-signed. `python verify_bundle.py bundle.json` (download at `/tools/verify_bundle.py`) checks all of it with no network access.

## Privi Mandates (human-authorized agent spending)

Signed proof that a person authorized an AI agent to spend, which any merchant or payment facilitator can check before taking the agent's money.

1. `mandate_create` (org key) drafts the terms: budget, per-payment cap, allowed payees (0x addresses or domains), expiry, purpose. It returns a `sign_url`.
2. The human opens `/mandates/<id>/sign`, reads the plain-English terms, and signs once with their wallet (EIP-191; free, no transaction). The terms hash is countersigned by Privi and anchored on the Privi chain, and the approval is logged.
3. Before each payment the agent calls `mandate_spend`, which enforces the caps, payee list, expiry and remaining budget atomically and writes the payment (or the blocked attempt) to the agent's tamper-evident log.
4. Merchants and facilitators call `mandate_check` or `GET /mandates/<id>/check?amount=&payee=` (free) and get allow/deny with reasons plus a Privi-signed attestation.
5. The human revokes from the same page with one signature, or the organization calls `mandate_revoke`.

Public: `GET /mandates/<id>` (terms, signatures, budget, recent spends).

## Privi Live (real-time: streams, human approvals, kill switch, gateway, rooms)

Everything here runs over WebSocket and server-sent events, backed by one durable event log (7 days of replay).

**Streams** (`live_info` lists them): `wss://…/live/ws`, `GET /live/events` (SSE), `GET /live/trust/recent`, dashboard at `/live`.
- Channels: `trust` (public: passports issued / revoked / re-scored, wallets bound, mandates activated or revoked, transparency-log heads anchored), `mandate:<id>`, and `org` (private: a live tail of your audit log, approvals, kill switch, rooms).
- WebSocket frames: `{"type":"auth","key":"…"}`, `{"type":"subscribe","channels":["trust","org"],"replay":20,"filter":{"address":"0x…","types":["passport."]}}`, `{"type":"kill","stream_id":"agent|*"}`, `{"type":"ping"}`. Server frames: `{"type":"event","event":"passport.score_changed","id":N,"channel":"trust","at":"…","data":{…}}`, `heartbeat`.
- API keys never go in URLs: use `Authorization: Bearer` (SSE/HTTP) or the first WebSocket frame.
- Free and anonymous subscribers see the public channels delayed by `LIVE_FREE_DELAY_S` (default 300 s); Pro and enterprise get them in real time. A background watcher re-scores every live passport every `LIVE_TRUST_INTERVAL` seconds (default 120) and announces score or state changes (valid → broken / expired).

**Human approvals.** `approval_policy_set` makes `mandate_spend` pause on payments over a threshold: it returns `approval_required` with an `approve_url`; the mandate's principal signs an approve/deny message with their wallet (EIP-191), then the agent calls `mandate_spend` again with `approval_id`. An approval is for exactly one payment (mandate, amount and payee must match), valid 10 minutes after it is granted, usable once. `approval_request` / `approval_wait` do the same for any action. The organization's API key can only *cancel*, so an agent cannot approve itself.

**Kill switch.** `live_kill` (or `privi kill`, the `/live` dashboard, or a WebSocket frame) stops `mandate_spend`, the organization's gateways and room messages for one agent or all of them on the very next call, and pushes `agent.killed` to the live channel. Audit logging is never blocked. `live_resume` lifts it.

**Gateway.** `gateway_create` puts any public HTTPS MCP server behind `/gw/<id>/mcp` (and `wss://…/gw/<id>/ws`, the same JSON-RPC over one persistent connection). Privi rate-limits each caller, can require a Passport (`min_score`: the caller proves a KYA wallet with a fresh `personal_sign` over `Privi Gateway <id>\nTimestamp: <ts>`), meters every `tools/call`, writes each call to your log, and forwards the request unchanged, including x402 payment headers, so the upstream's own paywall keeps working. The kill switch stops it instantly. Upstreams that resolve to private, loopback or link-local addresses are refused. Free plan: 1,000 metered calls and 2 gateways; Pro: unlimited calls, 50 gateways. Per-tool stats: `gateway_stats`.

**Rooms.** `room_open` creates a live, hash-chained conversation between two organizations' agents (`wss://…/rooms/<id>/ws`; invite by org id or one-time join code). Optionally charge the guest per message, paid under their human-signed Mandate (budget, cap, payee list, approval policy and kill switch all apply). Closing a room seals the transcript: signed with Ed25519 and ML-DSA-87, anchored on the Privi chain, and written into both organizations' logs. `room_verify` (free) checks a transcript against the seal. Privi enforces and records the per-message charge; moving the money is between the two parties.

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
