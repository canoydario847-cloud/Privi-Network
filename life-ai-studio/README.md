# Privi LIFE AI Studio — collaborative multi-agent workspace

**Status: working MVP implementation on a feature branch; not deployed, not a live native-PRVI payment system.** Built as a new stand-alone service in the Privi repository. The GitHub connector cannot create a separate repository, so this directory is organized to be extracted into its own repo without changing existing Privi services.

### What is built
- LIFE signup/login with scrypt password hashes, server-side sessions, and owner-isolated projects
- Multiple pages: Overview, My Projects, Code Studio, Agent Hub, Wallet, Membership, Privi Utility, Activity
- Unlimited separate project records (code, research, business, design, writing, automation)
- Parallel AI provider requests to OpenAI (Responses), Anthropic (Messages), xAI (Chat Completions), Hey Jose adapter, and a configured custom compatible adapter
- Shared versioned project files, parallel agent proposals, review queue, atomic human-approved merges, optimistic concurrency checks and merge conflicts; no automatic execution of untrusted AI-generated code
- LIFE member wallet ownership binding using EVM personal_sign challenge, expires and one-time nonce
- Metered utility credits + fractional platform fee accounting (microcredit precision) and internal authenticated idempotent debit endpoint for Hey Jose, LIFE backups, IoT, Privi Guard, Ledger, Anchor, Verify, Privi OS, AI metadata services
- Native PRVI **verification scaffold disabled by default**. Once an independently audited, live native PRVI EVM mainnet and payment policies exist, administrators can configure fixed pricing in native PRVI wei per credit and chain receipt verification. Blocks misconfigured/local demo/test/BNB/Ethereum networks, requires >=12 confirmations, wallet identity, treasury, value, receipt success, and unique transaction hash
- Does not mint PRVI, issue tokens, bridge BNB PRIV, or treat valueless TEST/PRVI_TEST as payment.

### Run locally
```bash
cd life-ai-studio
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# export configured variables (or use an env loader)
export PUBLIC_ORIGIN=http://localhost:8080 LIFE_COOKIE_SECURE=0
export LIFE_DB_PATH=./data/life-studio.sqlite3
# Supply real keys and model IDs *to the server environment*, not to Git:
export OPENAI_API_KEY=... OPENAI_MODEL=...
export ANTHROPIC_API_KEY=... ANTHROPIC_MODEL=...
export XAI_API_KEY=... XAI_MODEL=...
uvicorn app:app --host 127.0.0.1 --port 8080
```
Open http://localhost:8080. The AI providers require separate API access; a ChatGPT/Claude/Grok web subscription alone does not grant API usage. Hey Jose in the existing repo is currently a login/OAuth/plugin backend; configure JOSE_AGENT_URL only after an authenticated Jose inference endpoint exists. Agents that are not configured display as unavailable, not secretly simulated.

Development-only trial credits: `LIFE_DEV_TRIAL_CREDITS=10` with `LIFE_COOKIE_SECURE=0`. These credits are valueless test units and **cannot represent PRVI token purchase**. Do not set this in production.

Run tests: `pytest -q`.

### Native PRVI credit purchases (future launch gate)
`PRVI_MAINNET_PAYMENTS_ENABLED=0` means purchases always return HTTP 503. Configure and review these variables only after actual mainnet audits: `LIFE_COOKIE_SECURE=1`, `PUBLIC_ORIGIN` HTTPS origin, `PRVI_EVM_CHAIN_ID` (an independently verified production ID, not 262144 demo), `PRVI_RPC_URL` (trusted HTTPS RPC), `PRVI_TREASURY_ADDRESS`, `PRVI_WEI_PER_CREDIT` (approved treasury pricing), `PRVI_REQUIRED_CONFIRMATIONS>=12`. Never use unverified chain facts or asset conversion rates. Quotes expire; transfers require confirmed receipts. This handles only **native PRVI on the configured chain**, not arbitrary ERC-20s.

For serious financial production use, security-review and harden key management, receipt reorg and RPC failure handling, quote expiry policy, payment disputes/refunds, custody/tax compliance and pricing; use redundant trustworthy RPC providers and an independent on-chain audit. The existing repository's TEST EVM demo and PRVI_TEST simulator are valueless, not mainnet PRVI.

### Privi-wide utility charging integration
Each backend service (Hey Jose, LIFE backup, IoT, Guard, Ledger, Anchor, Verify, Privi OS, data labels, etc.) gets its own high-entropy server-side key in `PRIVI_SERVICE_KEYS_JSON`, for example:
```json
{"hey_jose":"<32+ random chars>","iot_ledger":"<another independent secret>"}
```
Service-to-service only; never place these in the browser. POST `/api/internal/charge` with `X-Privi-Service-Key`, body:
```json
{"user_id":"life_<member-id>","service":"hey_jose","idempotency_key":"jose-call-unique-request-id"}
```
The server verifies service identity, LIFE member, wallet binding, available credits, and idempotency, then debits atomically. Each product must separately adopt this endpoint; existing service endpoints are not silently modified or billed. Service keys should be kept in a secret manager. For production refunds and multi-step expensive jobs, add reserve/capture semantics and compensating events before integration. Do not charge legacy USDC x402 requests again.


### Working toward production (separate from disposable staging)
`GET /health` remains a lightweight **liveness** endpoint. `GET /api/production-readiness`
is a public, non-secret **release-gate checklist** and deliberately reports `ready:false`
until each gate is demonstrated. Never configure this readiness checklist as the
Render HTTP health path while LIFE is still in staging; that would turn known
launch blockers into unnecessary service outages.

LIFE now persists failed-login throttling in SQLite (five incorrect attempts per
email/client combination in a 15-minute window, then a 15-minute lockout);
this is defense in depth, not a substitute for edge rate limits, verified
enrollment, MFA, fraud monitoring or an independent security review.
LIFE's SQLite architecture is still single-instance and requires a separately
verified durable volume and backup/restore test. Horizontal production scale
needs a database migration and multi-worker safe queues; these are explicit
unmet checklist items. The staging service must remain a no-real-payment,
no-real-personal-data preview until the release gates are satisfied.

### Security and scaling notes
This is a **single-instance MVP** using SQLite. Use an encrypted durable disk/volume and backups. Before public deployment add rate limiting and account verification, email recovery/MFA, distributed persistent job queues, team RBAC/invitations, secret rotation, endpoint audit, monitoring, legal terms/privacy, paid membership renewals and PostgreSQL with row-level isolation. API calls have timeouts and provider keys remain server-side. The agent collaboration loop is reviewer-controlled, **not autonomous code execution**. Users can run different projects in different pages concurrently; proposals reference shared file versions and fail on stale merges.

### License & ownership
Privi World Co. Intended new repo name: `privi-life-ai-network`; original Privi sources: [Privi-Network](https://github.com/canoydario847-cloud/Privi-Network).

### Fee precision and network binding
Utility fees are recorded in **microcredits**, preserving fractions of credits; the browser displays them in decimal credit units. PRVI settlement configuration also requires `PRVI_GENESIS_BLOCK_HASH` to match block zero, not only a chain ID. Purchase quotes expire after 2 hours; mined transfer blocks must not predate the quote. Network administrators must independently verify all these settings; native-token purchases remain disabled by default.


## Team Up, Fast Lane, and multi-chain registry

- **Team Up**: choose 2–6 configured AI providers in a coding project and click
  "Team Up · Code Together". A parallel task round assigns frontend, backend,
  testing, security, documentation and integration responsibilities. Every agent
  receives the same approved project snapshot and an explicit role. Responses
  become *proposals*; no agent can silently overwrite files or execute code.
  Human review and versioned conflict detection still apply. This is one
  simultaneous round, not a claim of live multi-user text cursors.
- **Fast Answers**: race up to three configured providers concurrently and
  return the first usable answer, cancelling remaining tasks where possible.
  Cache identical queries for the same LIFE member, project, agent selection
  and shared-file versions for 180 seconds. Fast Lane is **classical concurrent
  scheduling**, with no QPU/quantum processor or speed guarantee. First result
  may be quicker than waiting for all, but provider API bills can still occur
  for cancelled requests. LIFE credits charge per dispatched model; exceptions
  are refunded. Cross-member cache reuse is prohibited.
- **Swap & Bridges**: read-only asset display and operator-reviewed ERC-20
  registry via `PRIVI_REVIEWED_ASSETS_JSON`. The PRVI native asset requires
  separate chain/genesis verification. **Zero live bridge routes, zero swap
  execution or token approvals**; `POST /api/networks/swap/quote` fails 503.
  An AI vendor API does not imply a proprietary blockchain or native crypto
  token. Do not describe unaffiliated GROK, CLAUDE or CHATGPT-ticker tokens as
  official vendor payment assets.

The next *separate* release gate for swaps would require independent smart
contract audits, two-chain proofs/finality handling, canonical wrapped asset
registry, independent relayers, liquidity, rate/oracle limits, replay protection,
user slippage limits, MEV controls, and jurisdiction/compliance review.
Do not route user assets to a bridge before those conditions are met.

**Endpoints:** `POST /api/projects/{project_id}/run-team` supports
`mode="team_up"`; `POST /api/projects/{project_id}/fast-answer` accepts
`question` and `providers`; `GET /api/networks/assets` lists registered
assets; `POST /api/networks/swap/quote` rejects all live swaps.

**Testing:** `pytest -q` covers joint concurrent code proposals, distinct
roles, human merge requirement, fastest-provider racing, fallback, scoped
cache, refunds, and fail-closed swap/token policy.

## Disposable Render staging preview
With `LIFE_STAGING_ONLY=1`, `/api/auth/demo` creates a throwaway sandbox identity,
synthetic non-custodial display address and 60 **valueless** trial credits. Browser
shows a staging warning, blocks real wallet linking and normal signup/login,
and exposes three explicitly simulated demo coding agents for Team Up or Fast Lane.
No provider API keys are configured and no swaps or PRVI purchases can be made
(even if payment environment variables were accidentally set). Demo data lives
in ephemeral SQLite, so preview state resets on restart or redeploy. Do not use
real emails, passwords, personal files, live wallet credentials or customer data.
This is a UI/functional demonstration, not a public membership launch.
\n## Privi Cognitive Signatures — code authorship and royalty metering
© 2026 Privi World Co (this original platform module); underlying code rights
remain governed by each contributor's agreement and each component's license.

Every approved code file save and human-approved agent merge now adds an immutable
`cog_events` record plus EVERY current line in `cog_lines`. Each line carries
its exact text, SHA-256, first observed agent attribution and UTC timestamp.
Unchanged lines preserve their earlier recorded attribution through version
merges. Generated but unapproved agent code receives a separate proposal
attestation before the human approves it. The signed canonical event includes
the file version, full content SHA-256, per-line manifest SHA-256, previous event
hash, run ID/agent, timestamp and LIFE generation credits.

Set `PRIVI_COGVATIVE_ED25519_SEED` to a secure random, server-side 32-byte
Ed25519 seed encoded as 64 hex digits in a secure environment/secret manager.
In real (non-sandbox) mode, signing is **required** and writes fail closed
without the key. Staging explicitly labels unkeyed records HASH-ONLY / UNSIGNED.
Do not commit or expose signing secrets. Back up keys and plan rotation.

The API shows `prvi_deploy_wei=null` until a *verified real native mainnet
contract creation receipt*, initiated by the user's bound wallet, is linked
after confirmations. Gas is `gasUsed * effectiveGasPrice` wei. That receipt
proves a PRVI-chain deployment occurred but NOT that deployed machine code
was built from the attested source. Before settlement can be called complete,
reproducible build and bytecode verification remain required.

`POST /api/projects/{project_id}/cogvative/code-use` charges exactly ONE
LIFE utility credit once per idempotency key and attributes 40% of the charge
as pending agent microcredits pro-rata by signed source lines. Privi's existing
10% service fee remains separately accounted (not added to the one-credit
price). An agent wallet may be registered only after an EVM signed wallet
challenge; this proves wallet CONTROL, not affiliation with an AI provider.
Royalties are bookkeeping, not redeemable PRVI, and payouts are disabled.
A potential **1 PRVI per call** tariff is stored as a NON-LIVE proposal,
not charged on-chain. Licensed platform API access is the only metered boundary:
Privi cannot automatically charge for copied/off-platform code use.

**Legacy whole-repository backfill:** `python life-ai-studio/tools/backfill_git.py
--root . --output cogvative-git-backfill.jsonl` inventories every accessible
Git-tracked UTF-8 line (other than binary and secret-named files) using
`git blame --line-porcelain`. It outputs line hashes and historical Git
author/commit/times in a downloadable Actions artifact; all historical AI
identities are marked UNKNOWN/UNVERIFIED, deploy PRVI cost remains UNKNOWN.
Historical data is not retroactively forged into signed creation events.

**Endpoints:** `/api/cogvative/about`,
`GET /api/projects/{project_id}/cogvative`,
`GET /api/projects/{project_id}/cogvative/event/{event_id}`,
`GET /api/projects/{project_id}/cogvative/proposals`,
`GET /api/projects/{project_id}/cogvative/royalty-balances`,
`POST /api/projects/{project_id}/cogvative/code-use`,
`POST /api/projects/{project_id}/cogvative/{event_id}/deployment`,
`POST /api/projects/{project_id}/cogvative/{agent}/wallet/challenge`,
`POST /api/projects/{project_id}/cogvative/{agent}/wallet/link`.


## BNB PRIV token payments — distinct from native PRVI

The BNB Smart Chain **PRIV** token identified by the founder is distinct from the
proposed native Privi **PRVI** coin. Candidate user-supplied address (not
independently verified in this release): `0xbf154Ff2577F4B85db7B2ee910Db5880D06e0f64`.
Do not treat ticker/name alone as identity. An operator must independently
verify the contract, the token's transfer behavior, merchant treasury and the
smallest-unit price before enabling payments.

The LIFE API implements optional direct ERC-20/BEP-20 transfer payment
`POST /api/payments/bnb-priv/quote` and
`POST /api/payments/bnb-priv/redeem` on **BNB mainnet chain ID 56**. Status:
`GET /api/payments/bnb-priv/status`. No custody of purchaser keys,
browser-signed **transfer() only**, never allowance or infinite approvals.

The gateway is **off by default** and deliberately incompatible with
`LIFE_STAGING_ONLY=1`. Enabling requires `BNB_PRIV_PAYMENTS_ENABLED=1`,
`LIFE_COOKIE_SECURE=1`, a trusted HTTPS mainnet RPC, an independently
approved token contract and exact SHA-256 of its currently deployed runtime
bytecode, token decimals, treasury address, fixed price in smallest-token
units per LIFE credit and at least 12 confirmed blocks. Every quote checks
the actual network ID, bytecode fingerprint and decimals. Redemption verifies
the matched quote, member-linked wallet, exact token contract, direct ERC-20
transfer(address,uint256) input, zero native value, matching Transfer event,
canonical block and receipt success, transaction timestamp, depth, replay
protection, and immutable ledger idempotency before crediting LIFE membership.

Price is in units of PRIV, **not USD**. No sale, liquidity, conversion price,
redemption value, investor return, or current market listing is guaranteed.
Real customer payouts and deposits must be monitored separately. A secure,
durable production database and customer support/refund procedures are still
required. Never submit real payments to staging, a test wallet or an
unverified merchant address.

### Existing USDC paid service
The `ledger-server` code already documents Privi Ledger's USDC-on-Base
x402 paid audit tools and a $29 USDC/30-day Pro plan. Real receipt settlement
and a merchant-owned payout address need to be verified from the running
service independently; source documentation is not proof of revenue.
Customer-facing landing: `https://privi-ledger.onrender.com/mcp`.
