# PRVI native coin — Hey Jose users and usage only

**Selected economic design direction (2026-11-26): PRVI tracks verified Hey Jose active users AND verified Hey Jose completed usage.** The user explicitly rejected the USD dollar-index component and a USD-redeemable stablecoin design.

**Status: PROPOSAL / MAINNET NO-GO / NO LIVE PRICE PEG OR REDEMPTION.**
A token's market price cannot be maintained by counting users or API calls alone. Any promise of a fixed exchange rate would require an independently funded, audited mechanism and legal review. The proposed index is a transparent economic signal, **not** an enforceable exchange rate or automatic PRVI token price.

## Inputs — both exclusively derived from Hey Jose

1. **Verified active unique users:** independent, privacy-preserving count of distinct legitimate accounts with successfully completed use during the same defined reporting period. Deduplicate accounts/devices subject to privacy law; detect bots, Sybil registrations, false activity and promotions. Do not use raw signups, visitors or publicly identify individuals.
2. **Verified completed usage:** auditable successful service units, not mere message submissions or failed calls. Define which validated services and models count (e.g., completed agent jobs, successful authorized tool invocations, completed paid or approved requests); audit usage event IDs, replays, spam, service cost and fraud.

**These are the only components.** No USD dollar index, USD FX index, GDP, payroll index, USDC collateral price, dollar-redemption target, speculative estimates, personal-data valuation, or unrelated market metrics enter the proposed reference index.

## Example index for design tests only

Let:
- U0 = verified active unique users in a preapproved baseline period
- Ut = verified active unique users in the current matched period
- A0 = verified successful usage units in the baseline period
- At = verified successful usage units in the current matched period
- wU and wA = nonnegative weights totaling 1; **weights not yet approved**

A dimensionless activity reference may be computed as:

    I(t) = 100 × (Ut/U0)^wU × (At/A0)^wA

This formula is only a transparent illustration. It **does not mint, burn, collateralize, promise redemption or determine the market trading price** of PRVI. Even with perfectly verified data, the actual token price may rise, fall, or become illiquid, independently of the index.

**Example with fictional data only:** U0=100, Ut=120, A0=1000, At=1500, wU=0.5, wA=0.5 -> index approximately 134.164. That means activity-index growth relative to baseline, not $134.164/PRVI and not a $1 peg. Weight and reporting-window decisions are outstanding.

## Before any enforceable market "peg" is claimed

The user chose a **Hey Jose user-and-usage-linked economic design**. It is **not** truthful to advertise a guaranteed user-count-to-token-dollar exchange rate without an explicit rule plus credible audited sources of funds, liquidity and redemption, transparent settlement, pricing, and independent legal/market-risk review. Do not automatically call this a stablecoin or advertise a guaranteed price.

Prerequisites:
1. **Written metric definitions, index baseline and observation window**, with user privacy safeguards and fraud-resistant aggregation.
2. **Independent oracle/auditor** verifying unique active accounts, successfully completed usage, fraud exclusions, event reconciliation and corrections. No raw messages, email addresses, user IDs, IPs or personal data posted on-chain.
3. **Token economic mechanism selected and modeled**: fee demand, network incentives, carefully capped issuance if any, treasury budget and liquidity, market-maker assumptions, stress testing under abuse, growth/declines and outages. No unbacked issuance based solely on usage spikes.
4. **Legal/regulatory analysis** of PRVI sale, distribution, payments, rewards and any price-stabilization statements. No promise of a guaranteed financial peg without validated support.
5. **Strict mainnet release gates**: independent review of PoP consensus and chain binary, finalized nonconflicting production chain identity, signed genesis, durable supply cap, independent validators, public multi-host fault tests, audits, wallet and RPC readiness, and a signed explicit launch decision.
6. **Testnet-only oracle and ledger rehearsal** followed by independent finance/security approval; no automatic chain migration or wallet signing without authorization.

## Identity and supply separation

- Existing **Privi TEST devnet**: EVM chain ID 772626; permanently valueless.
- **Upstream Cosmos EVM demo**: EVM ID 262144; not an approved PRVI financial network.
- **Native PRVI financial chain**: production Cosmos and EVM IDs not yet finalized, mainnet not live.
- Existing proposed lifetime supply ceiling of **1,000,000,000 PRVI** is distinct from price, issuance or valuation. Previous 900M liquid/100M vested worksheet is a proposal requiring signed review, not evidence of issued tokens or on-chain claims.
- Native PRVI, BNB PRIV and TEST credits remain separate until an explicitly approved migration plan.

## Hey Jose capabilities (no financial side effects)

- \`GET /api/prvi/mainnet/plan\`: explicit mainnet **NO-GO**, and the selected user/usage-only economic reference.
- \`POST /api/prvi/mainnet/usage-index-preview\`: accepts **six explicitly supplied numeric scenario inputs**: \`usersBaseline\`, \`usersCurrent\`, \`usageBaseline\`, \`usageCurrent\`, \`usersWeight\`, \`usageWeight\`. It computes only the dimensionless activity index. Not backed by live analytics, oracle signatures or user verification.
- Old \`POST /api/prvi/mainnet/index-preview\` dollar-index route: responds **410 Gone**, preventing accidental reuse of the rejected formula.

All wallet signing, issuance, payments, bridges, redemption and mainnet launch switches remain **disabled**. No financial mainnet is launched by this decision.

## Sample illustrative input — NOT live measurements

    {"usersBaseline":100,"usersCurrent":120,
     "usageBaseline":1000,"usageCurrent":1500,
     "usersWeight":0.5,"usageWeight":0.5}

Results are an index of activity relative to the baseline **only**.

See [native mainnet gates](../production-network/ops/PATH_TO_LAUNCH.md) and [genesis review](../production-network/mainnet/GENESIS_INPUTS_AND_REVIEW.md). No "$1 per PRVI", reserve, USD FX or stablecoin promises are part of this selected design.
