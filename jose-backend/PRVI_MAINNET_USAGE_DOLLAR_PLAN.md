# Hey Jose and native PRVI — USD-redeemable payment stablecoin target

**Design selection: GENUINELY REDEEMABLE USD PAYMENT STABLECOIN.**
**Launch status: NO-GO / NOT ISSUED / NOT BACKED / NOT REDEEMABLE.**
Updated 2026-11-26. Owner: Privi World Corp.

This decision supersedes the previous plan to make PRVI's token price float with a
formula tied to Hey Jose usage and an FX-dollar index. The project is now
**targeting** a par redemption model: after all requirements are met, an
eligible holder should be able to redeem one issued PRVI for USD 1.00 under
legally approved and disclosed redemption procedures. This document is
a design selection, NOT evidence that Privi can issue or honor such a claim.

## Selected economics and clear separation of usage metrics

- **PRVI target:** one issued PRVI represents an obligation redeemable for
  **USD 1.00** by a legally permitted issuer, subject to its legally compliant
  procedures. Secondary-market prices can temporarily deviate from $1 even
  with a redemption mechanism.
- **Backing:** maintain at least $1 of eligible, properly valued and controlled
  reserve assets for each $1 of outstanding PRVI stablecoins at all times,
  subject to any additional liquidity, capital and risk requirements. Eligible
  reserves may include USD cash, appropriate bank deposits, short-dated U.S.
  Treasuries and other specifically permitted instruments. **Hey Jose usage,
  personal data, AI work, promised income, uncollateralized PRVI, and
  unbacked PRIV tokens are not eligible dollar reserves.**
- **Issuance:** never create circulating, treasury, founder, validator,
  vested, locked or staked payment stablecoins without an equal legally
  eligible reserve claim and full authorization. This includes genesis
  balances: being initially locked does not turn issued tokens into unissued
  tokens. No automatic mint as a reward for Jose user growth.
- **Redemption:** an authorized issuer must provide published, reasonably
  accessible redemption instructions, onboarding/screening, processing-time
  disclosures, liquidity contingency management and lawful token retirement /
  supply reconciliation on redeemed units. There is currently **no such
  operating program or verified treasury**.
- **Hey Jose usage:** measure verified aggregate service consumption for
  **operational planning and customer analytics only**, not as price
  collateral or backing. If Jose accepts PRVI for payment after launch, its
  service fee could be denominated in USD, with approved PRVI payment mechanics;
  such transactions must be authorized and audited independently.
- **The dollar index:** the Federal Reserve's nominal broad dollar index
  measures exchange value of USD versus currencies. **It does not change the
  $1 redemption obligation and cannot maintain backing.** Keep any H.10 usage
  as a separately labeled nonfinancial economic research chart. It must never
  set redemption amount, peg, collateral, or new mint quantity.
- **No yield promise:** do not promise issuer-paid staking interest or yield
  on payment stablecoin holdings. Validator incentives and fees must be
  reviewed as an independently funded operating expense; creating unbacked
  reward coins is inconsistent with par-redemption economics.

## Supply implications for the previously proposed allocations

The founder's earlier engineering target included a proposed **maximum of
1,000,000,000 PRVI** and a worksheet with 900 million liquid plus 100 million
vested units. **A maximum token cap is not an initial issuance instruction.**

If one billion PRVI were **issued**, the project would need at least
**USD 1 billion in eligible reserves** plus additional required liquidity,
capital and operational safeguards. Even an issuance of 900 million liquid
PRVI would entail at least USD 900 million of qualifying reserves; vesting
does not waive backing if the other 100 million tokens are also issued.

No approved reserve funding, issuer authorization or signed genesis has
been evidenced. Therefore do **not** encode that historical 900M/100M
allocation as real stablecoin genesis balances or advertise outstanding PRVI.
The issuer may instead design an **unissued issuance ceiling** of up to
one billion, subject to legal advice and a chain-enforced lifetime cap.
Unissued capacity is not a token balance.

## Regulatory and operating gates (must pass before launch)

1. Identify a qualifying issuer entity and jurisdiction. The GENIUS Act
   generally requires a permitted payment stablecoin issuer under federal
   or qualifying state oversight. **Privi World Corp's corporate form and
   software business status do not establish eligibility**. Its treatment
   as a nonfinancial company requires specific legal analysis.
2. Retain U.S. stablecoin regulatory counsel and assess the GENIUS Act,
   applicable federal/state law, issuer ownership restrictions, banking
   agreements, AML/KYC, OFAC sanctions and international distribution.
   OCC's final rule and GENIUS Act take effect January 18, 2027; being
   pre-effective does not waive other currently applicable laws.
3. Establish properly documented reserve custody, qualified custodians /
   insured depository relationships where applicable, reserve segregation,
   asset-eligibility and valuation rules, concentration limits, a liquidity
   policy, banking settlement and operational recovery.
4. Build an issuance and redemption system in which each issued PRVI
   is fully reconciled with eligible reserves and liabilities. Independent
   reserve reconciliations, regular disclosure/attestations, periodic
   examinations and incident/insolvency plans must be in place.
5. Implement robust cryptographic controls (separation of duties,
   authorized mint/burn, independent signer quorum, dual approvals, audit
   logs, circuit breakers, rate limits, sanctions screening, privacy).
6. Pass the existing native PRVI chain launch gates: independently audited
   PoP integration in real node binary, verified lifetime hard cap,
   unique production chain IDs, signed genesis, four independent validator
   operators, public multi-host testnet/recovery evidence, external
   security reviews, approved wallet/RPC/explorer, signed explicit GO.
7. Validate the combined financial and technical release in a nonfinancial
   test environment first. Only then may the authorized issuer seek
   approval to start **fully backed** issuance and redemption.
   Neither a code commit nor a passing CI run constitutes any approval.

## Existing Hey Jose endpoints — remain inert

- GET /api/prvi/mainnet/plan: returns the selected proposed design and
  explicitly reports no issuer, reserves, approval, active peg, redemption,
  minting, payment or mainnet connectivity.
- POST /api/prvi/mainnet/index-preview: preserves a historical mathematical
  research calculator. Its result is a dimensionless normalized reference
  with zero effect on issuance, token price, backing or redemption. The
  previously proposed usage/dollar-index formula is now **out of scope
  for the selected stablecoin redemption mechanism**.
- No production smart contracts, genesis accounts, customer wallets, bank
  reserves, tokens or payment flows are altered by this decision.

## Project identifiers
- Existing **Privi Devnet**: EVM chain 772626, TEST, valueless, separate.
- **Upstream Cosmos EVM demo**: EVM chain 262144, NOT assigned PRVI mainnet.
- Financial native PRVI mainnet: Cosmos ID and EVM ID **unapproved / TBD**;
  the actual identity must be independently validated and signed.

## Authorities consulted (November 2026)
- OCC GENIUS Act final rule bulletin:
  https://www.occ.gov/news-issuances/bulletins/2026/bulletin-2026-50.html
- OCC application/waiver bulletin:
  https://www.occ.gov/news-issuances/bulletins/2026/bulletin-2026-51.html
- Congressional Research Service summary:
  https://www.everycrsreport.com/files/2026-08-20_IN12553_0b329134f6be0cc12f78017358552f4053d52c5e.html
- Privi mainnet gates:
  ../production-network/ops/PATH_TO_LAUNCH.md

**This product decision is not a legal assessment, a promise to pay,
an active stablecoin peg, an investor solicitation, or permission to issue.**
