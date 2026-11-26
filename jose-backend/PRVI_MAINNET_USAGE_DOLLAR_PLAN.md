# Hey Jose on PRVI mainnet — future architecture and usage/dollar model

**Status: DESIGN PROPOSAL / NO-GO / NOT DEPLOYED.** Updated 2026-11-26.
Owner: Privi World Corp. Not a genesis change, price quote, token issuance,
reserve attestation, investment projection, or launch authorization.

## Product decision
Long-term plan: **Hey Jose will use native PRVI financial mainnet** for approved
agent-call fees, service access, and ledger receipts, but only after the chain
and app independently pass release gates. Until then Jose continues on existing
hosting. Privi Devnet TEST stays permanently valueless.

The proposed economic research considers two inputs:
1. **Verified Hey Jose usage** — independently auditable aggregate successful
   billable service units. Filter out retries, bots, test accounts, failures and
   promotional traffic. Number of signups alone is insufficient.
2. **The dollar index** — a reproducible, identified and timestamped index.
   One candidate is the Federal Reserve H.10 nominal broad USD index, tracking
   USD versus trading-partner currencies. This is NOT the dollar's face value
   or a $1 redemption guarantee. Specific index, vintage, cadence and provider
   require a separate approval.

## A reference index is NOT a price peg
An illustrative dimensionless reference index is:

    I(t) = 100 * (verified_usage_t / verified_usage_0)^w_usage
              * (dollar_index_t / dollar_index_0)^w_dollar

Nonnegative weights must sum to one and both inputs need compatible periods.
Weight, base period and data source are not approved yet. A hypothetical index
does not mechanically determine or guarantee PRVI market price, backing,
liquidity, exchange rate, token supply, redemption, staking rewards or yield.

Three distinct possible products require separate decisions:
- **Utility token with index-aware disclosure:** PRVI pays for agent services,
  and verified usage/dollar metrics are published. Token market price floats.
  A separately approved fee or bounded reward-budget policy could use the
  metrics while preserving the lifetime supply cap. DO NOT call this a peg.
- **True USD payment stablecoin:** a separate issuer, reserve, redemption,
  licensing, supervision and audit framework. Hey Jose usage is not collateral.
- **Index-linked redemption promise:** another potentially regulated financial
  product with custody/liquidity obligations; it is NOT selected by default.

The user has not yet specified a binding valuation formula or approved one of
these mechanisms, dollar series, base period, and weights. No peg is active.

## Current network identity and safeguards
- Proposed native PRVI lifetime hard maximum: 1,000,000,000 whole PRVI,
  not a claim of issued supply or market value.
- Production Cosmos and EVM chain IDs: **TBD** pending unique-network review.
- Numeric EVM 262144 belongs to an upstream developer demo in the repository;
  PRVI TEST devnet 772626 is valueless and NOT the financial mainnet.
  The founder's proposed chain number cannot be activated without verified
  unique production genesis identity and signed release approval.
- Current gate: **NO-GO**, see
  [PATH_TO_LAUNCH](../production-network/ops/PATH_TO_LAUNCH.md),
  [MAINNET_LAUNCH_GATE](../production-network/ops/MAINNET_LAUNCH_GATE.md),
  [GENESIS_INPUTS_AND_REVIEW](../production-network/mainnet/GENESIS_INPUTS_AND_REVIEW.md).
- Launch requires audited consensus and chain binary, persistent lifetime
  supply cap, signed genesis and hashes, independent validators, publicly
  exercised multi-host testnet/recovery, RPC/wallet/explorer validation,
  legal/security reviews and an explicit signed GO record.
- No operator-controlled switch alone can authorize financial transactions.

## Engineering sequence
1. **Usage measurement:** Meter completed Jose requests in a privacy-safe
   server accounting system. Unique IDs, timestamps, successful outcome,
   anti-replay, exclusion rules, corrections and reconciliation required.
   Never publish prompts, user IDs, emails, IPs, secrets or personal data on-chain.
2. **Signed aggregate attestation:** Independent operator quorum signs
   aggregate usage windows, with schema/version, correction policy, fraud
   filters, rate limits, privacy review and audit trails.
3. **Dollar-series oracle:** Choose one authoritative index and vintage,
   base date, update cadence and source terms. Verify authenticity,
   freshness, revision and data-lag policies, fallbacks and circuit-breakers.
4. **Tokenomics and legal design:** Approve weights, cap-safe fee/reward policy,
   reserves if any, budget, disclosures, stress testing and legal review.
   Separate public index disclosures from token-price or peg promises.
5. **Testnet-only wallet adapter:** User-approved scoped transactions, chain
   and genesis pinning, replay protection, transaction preview and receipts.
   Isolate TEST, BNB PRIV and native PRVI, and never request seed phrases.
6. **Mainnet integration:** Only after independent chain GO, signed release
   artifacts, audits, identity check and app-specific GO, enable audited
   PRVI payment functionality through a newly reviewed rollout.

## Safe design-only Jose backend interfaces
- GET /api/prvi/mainnet/plan — explicit NO-GO, no network identity, and
  payments/signing/minting/bridging/pegs disabled.
- POST /api/prvi/mainnet/index-preview — same-origin arithmetic on six
  user-provided finite numeric observations; no wallet, chain, market data,
  feed verification, reserves or token price. This is a hypothetical scenario,
  not a quote or mint/burn policy.

Illustrative request only:

    {
      "usageBaseline": 1000,
      "usageCurrent": 1250,
      "dollarIndexBaseline": 100,
      "dollarIndexCurrent": 102,
      "usageWeight": 0.5,
      "dollarWeight": 0.5
    }

The result is an abstract index around 112.916, NOT $112.916 per PRVI.

## Legal and reference sources
- [U.S. payment stablecoin issuer requirements](https://uscode.house.gov/us/usc/119-120/t12/s5903/)
- [OCC 2026 stablecoin implementation](https://www.occ.treas.gov/news-issuances/bulletins/2026/bulletin-2026-50.html)
- [Federal Reserve H.10 USD index series](https://www.federalreserve.gov/releases/H10/summary/default.htm)

A nonfinancial index study never constitutes mainnet or stablecoin approval.
