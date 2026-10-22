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
