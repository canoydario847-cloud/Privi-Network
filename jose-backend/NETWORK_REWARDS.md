# Jose AI Privi Report Card & Duration Rewards (beta)

Copyright © 2026 Privi World Corp — original new work under the prospective rights policy in the repository root `LICENSE`; preserve rights already issued under `LICENSE-MIT-PRIOR` and all third-party notices.

## Use case and working software

Jose checks fixed, built-in HTTPS Privi HTTP health endpoints once every **five seconds while the Node process is awake**:

- Ledger, Verify, Anchor, Call, Quantum, Discovery.
- Each cycle makes parallel server-side GET requests with a 3-second per-service timeout and does not accept arbitrary user-supplied URLs.
- `GET /api/network/report-card` returns latest success/failure, latency, observed uptime percentages, a bounded rolling ten-minute window, and a grade.
- `/network-report.html` displays a browser dashboard, service cards and recent history. The page refreshes from the server every five seconds.
- The grade becomes A/B/C/D/F only after three recent cycles, goes `N/A` on stale/insufficient data, and is scoped to HTTP **service availability**. It is NOT mainnet PoP consensus, node finality, token issuance, SLA certification, independent operator custody, or a chain-wide uptime metric.
- Jose's briefing is **deterministic text** based on measured endpoints; it does not currently call an LLM model, and no unsupported AI capability is implied.

Grading weights: 80% observed request success rate, 10% sub-1.5-second fraction among successful probes, and 10% current responding-service fraction. Letter boundaries A≥95/B≥85/C≥70/D≥55/F below 55. A result is a bounded, recent observation; it does **not** establish 99.9% contractual uptime.

## Duration and API-call participation accounting

The `/api/rewards/` endpoints require either an authenticated Jose user session or a configured high-entropy agent Bearer token:

| Endpoint | Behavior |
| --- | --- |
| `GET /api/rewards/policy` | Public beta-credit limits and disclaimer |
| `GET /api/rewards/me` | Current account's nonfinancial credits and recent activity |
| `POST /api/rewards/heartbeat` | Accounts for *elapsed server time* between 10–30-second spaced authenticated heartbeats, when at least five of six checked services are healthy; no offline/backdated time |
| `POST /api/network/inspect` | Authenticated read of server-verified current report. Eligible once per minute per account and only with a healthy fresh grade; earns two beta credits |

- **Presence:** one nonfinancial credit for 60 cumulative qualified seconds, up to 240 minutes per UTC day.
- **Network inspections:** two nonfinancial credits per eligible inspection, up to 30 per UTC day.
- Repeated calls, duplicate browser tabs, unauthenticated users, large heartbeat gaps, stale network checks and severe outage results do not accelerate accrual.
- Only server time counts. Users/agents cannot report their own duration, grade, call success, timestamp, or score.
- Beta credits are **not PRVI**, not transferable, not redeemable, no market value, no guaranteed allocation and no settlement mechanism. No wallet or mint integration is active.
- **Critical distinction:** participation alone does not make a blockchain node healthier. Infrastructure grading deliberately excludes user and agent logins. An eventual network contribution reward must depend on audited, independently provable useful work (real validator/sentry availability, authenticated peer relay, validated distinct fault domains or other productive service), with anti-Sybil measures and signed receipts before financial incentives become eligible.
- Before enabling real PRVI incentives: independent legal/security review, one-billion native issuance-cap controls, treasury-funded rewards budget (no inflation by default), ownership/KYC policy if applicable, proof-of-work-quality and anti-Sybil enrollment, double-claim prevention, escrow/settlement audits, per-participant caps and revocation/appeal rules.

## Agent authentication

Set `JOSE_AGENT_TOKEN_HASHES` in the **Jose backend** Render environment to comma-separated `agentId:sha256hexOfHighEntropyToken` entries. Example IDs `agent1`, `auditor_bot`. Generate a random 32+ byte token **locally** and privately store the token only in the agent's secret store; put only its SHA-256 hex fingerprint in Render. Do NOT put the token, environment secret or hashed account mapping into GitHub commits or chat. Rotate it when compromised.

Agent request example (use the agent's existing private environment variable, never paste its value):

```bash
curl --fail-with-body -X POST \
  -H "Authorization: Bearer $JOSE_AGENT_TOKEN" \
  https://jose-backend-vbuu.onrender.com/api/network/inspect
```

Invalid bearer credentials do not fall back to browser cookie auth. Browser POSTs require same-origin `Origin` verification. No anonymous reward claims or user-supplied amount endpoint exists.

## Reliability, storage and deployment limits

The current Jose Render service is a **free public Node web service** with auto-deploy enabled from `main` and a JSON-backed state store. **A free/sleeping instance cannot guarantee 24/7 five-second checks**. The in-memory rolling report history resets on restart, and beta-credit persistence requires `DB_FILE` to reference a directory writable to **durable disk**; otherwise a redeploy/restart may lose credits. This beta is single-process only; do not enable multi-instance writes without moving state into a transactional, durable DB. No independent alerting, data retention SLA, or streaming telemetry is configured.

For production-grade Jose NOC: pay for an always-on service or separate background worker and a durable managed database, use a private-vantage/fault-domain checker, run an externally anchored uptime monitor, instrument real native Privi RPC/PoP finalized-block metrics, notify on-call via trusted channels, and verify metrics across more than one provider. A Render deploy must be independently verified live after CI passes.

## Reproduction

From the repository:

```bash
node --test jose-backend/test/*.test.js
node jose-backend/src/server.js
```

The tests mock network responses and do NOT mint PRVI, access production keys, or activate any blockchain. Existing BNB PRIV and valueless TEST remain separate from future native PRVI.
