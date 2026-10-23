# Privi Duration Rewards × Jose AI Network Report Card

Copyright © 2026 Privi World Corp for new original proprietary works covered by the root LICENSE. Previously granted MIT and third-party rights remain intact.

## Jose's five-second service-health use case

While the backend is running, Jose requests HTTPS /health from five Privi Render application services: Ledger, Verify, Anchor, Call and Quantum. Only HTTP 200 with JSON ok=true and the correct service identifier counts as healthy. Jose publishes a fresh A–F report card every five seconds with service availability, response times, 12 recent samples and timestamp.

- Public dashboard: https://jose-backend-vbuu.onrender.com/network.html
- Report JSON: https://jose-backend-vbuu.onrender.com/api/network/report-card
- Process health: https://jose-backend-vbuu.onrender.com/health
- Participation policy: https://jose-backend-vbuu.onrender.com/api/rewards/policy
- Authenticated user points: GET /api/rewards/me

A score is 80% availability and up to 20% responsiveness, capped by the available fraction. A >=90, B >=80, C >=70, D >=60, F otherwise. Missing or >15-second-old data gives N/A, not a false healthy grade.

**Scope:** Application-service monitoring is NOT blockchain consensus, native PoP finality, independent validator custody, security auditing, or authorization for financial PRVI. Running on Render's FREE Jose tier means the five-second loop pauses if the instance sleeps or redeploys. True 24/7 monitoring would require an always-on instance and persistent timeseries data. Five endpoints every five seconds can generate up to 86,400 health requests per running day, with possible compute/network costs.

## Privi Duration Rewards

This prototype records nontransferable, nonredeemable PRELAUNCH PARTICIPATION POINTS. It never creates native PRVI, wallet balances, token redemption entitlements or money.

A verified user or agent must BOTH remain available and provide a trusted backend-verified useful action. Idle browser sessions, repeated reconnects, self-reported uptimes and unsigned heartbeat requests yield no points. Each useful action permits a maximum of 30 seconds of eligible connection time. Each five seconds earns 1 point plus 1 per verified useful action. Maximum attested receipt duration is 300 seconds and work units are 1–50. Daily maximum: 1,440 for users, 2,880 for agents.

The POST /api/rewards/attest route requires a server-issued HMAC signed work receipt and a fresh Jose grade C or better. Set a secret of at least 32 characters as the JOSE_REWARD_ISSUER_SECRET Render environment variable ONLY when a trusted work-verification backend exists. Never place it in GitHub, pages, chat or CI. The trusted issuer must first verify the actual work and duration against its own durable records. HMAC alone only authenticates an issuer, not the truth of the work claim.

Example JSON body (fictional and NOT payable):

    {
      "proofId": "work-session-example-001",
      "subjectId": "agent:sample_executor_001",
      "role": "agent",
      "verifiedSeconds": 60,
      "usefulActions": 2,
      "evidenceRef": "jobs/receipt-0001"
    }

Send the exact JSON UTF-8 body over HTTPS, with HTTP header x-privi-timestamp containing current 13-digit Unix milliseconds, and x-privi-signature containing lowercase SHA256 HMAC of timestamp + a literal period + the exact JSON body, using the secret. The server rejects bodies >8 KiB, signature age >60 seconds, invalid fields, mismatched roles and duplicate proof IDs. The API response contains granted NONFINANCIAL points and financialPrviAmount: 0, not a token transfer.

The subject identifier must be user:AUTHENTICATED-UUID or agent:REGISTERED-AGENT-ID. Agent self-service identity and proofs will need separate secure registration. Only signed receipts from the issuer are accepted.

## Storage and launch gates

The existing Jose prototype uses a single JSON-file-backed store. Its local persistence and uniqueness checks are not a financially secure, multi-instance or crash-safe rewards ledger. Free Render services can lose unbacked local data across restarts. Before actual value, move to auditable transactional durable database storage, independent proof validation, keys/issuer rotation, agent authentication, rate limits and independent security review.

None of this activates financial mainnet, issues PRVI, modifies the 1 billion native token cap, makes transfer/redeem promises, handles user funds or replaces production validator approval. A future real-PRVI reward program requires separate signed genesis/economics, secure proof of useful work, treasury authorization and legal review.

## Offline tests

Run from repo root: npm --prefix jose-backend test . Tests mock HTTP and use only standard Node APIs; no real Render request, key, wallet, payout or financial deployment occurs.
