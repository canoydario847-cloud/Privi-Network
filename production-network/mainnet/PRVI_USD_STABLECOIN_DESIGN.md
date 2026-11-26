# Native PRVI — USD payment stablecoin selected design (NO-GO)

Status: **DESIGN SELECTED; NO ISSUER APPROVAL, NO VERIFIED RESERVES,
NO LIVE MAINNET, NO ISSUANCE, NO REDEMPTION.**
Updated: 2026-11-26.

The proposed native PRVI asset is intended to be a genuinely
**USD 1.00 redeemable payment stablecoin**. This supersedes the
previous proposed usage/dollar-FX-index floating-price mechanism.

This design is NOT a statement that the asset can currently be minted,
sold, bought back or redeemed at par. A declared peg is not a functional
redemption obligation, nor is a dollar-index formula valid collateral.

## Selected constraints for the mainnet engineering team

- Proposed target: **USD 1.00 cash redemption per issued PRVI**, implemented
  by a legally permitted payment stablecoin issuer through disclosed procedures.
- Maintain **at least USD 1.00 of regulator-eligible, properly valued
  reserve assets per issued token** at all times, plus applicable
  additional capital, liquidity and loss-absorption controls.
- Reserve assets and liabilities must be separately controlled, audited,
  reconciled, screened and independently attested. AI usage, data value,
  forecast future payments, native token market cap, unbacked USDC claims
  and speculative investments are not qualifying par-dollar reserves.
- All minting of PRVI stablecoins requires authenticated deposits and
  reserve proof, permitted issuer sign-off, a production chain GO record,
  and full double-entry issuance accounting. No unconstrained mint,
  signer bypass, fee-funded unbacked emission, staking-inflation shortcut
  or oracle-based auto-issuance.
- Holder redemption processes, payout rails, customer onboarding,
  payout timeframes, fees, queue limits, token retirement/burn,
  reconciliation and insolvency protections must be independently
  designed and approved before token issuance.
- Usage of Hey Jose is for aggregate operational analytics, not
  collateral, token value guarantees, mint triggers, payout formulas
  or redemption amount. The Federal Reserve USD FX index likewise
  does not determine USD 1.00 redemption.
- Token cap, target 900M liquid + 100M vested genesis allocations and
  validator rewards **must be redesigned** around only fully backed
  issued balances. If all 1,000,000,000 tokens were issued, a minimum of
  USD 1,000,000,000 in eligible reserves would be required. A locked
  or vested token is still issued and must be backed if it exists as a
  circulating liability. Unissued token capacity can remain unused
  without needing to invent unsupported reserve assets.
- Stablecoin issuer authorization must be reviewed for Privi World
  Corp as a potentially nonfinancial firm, including GENIUS Act
  ownership constraints. Do not infer that a registered corporation
  is a permitted payment stablecoin issuer. GENIUS Act / OCC final rule
  effective date: **January 18, 2027**.
- Contract and chain design should prohibit economic issuance until
  both legal issuer authorization and complete native PRVI launch
  authorization are evidenced. Existing mainnet safety gates continue.

## Independent hard-blockers

1. Permission from the appropriate payment stablecoin regulator for an
   eligible issuer (or lawful alternative structure), plus counsel review.
2. Verifiable custodian, bank/payout relationships and eligible fully
   funded reserves with independent assurance.
3. Published operational redemption policy and tested legal, accounting,
   AML/KYC and sanctions controls.
4. Audited issuance/redemption contracts and controls with fail-closed
   mint/burn; no privileged backdoor or silent inflation.
5. Signed and independently validated PoP financial mainnet release,
   hard lifetime supply cap, genesis, validators, testnet/fault recovery,
   audited wallet/RPC and explicit GO.
6. Independent final **GO** for the combined chain + issuer program.

The economic selection alone grants no authority to change genesis, issue
tokens, advertise a current $1 claim, or deploy a dollar peg. Legacy PRVI,
BNB PRIV and Privi TEST remain distinct; no automatic migration permitted.

References:
- ../ops/PATH_TO_LAUNCH.md
- GENESIS_INPUTS_AND_REVIEW.md
- ../../jose-backend/PRVI_MAINNET_USAGE_DOLLAR_PLAN.md
- https://www.occ.gov/news-issuances/bulletins/2026/bulletin-2026-50.html
- https://www.occ.gov/news-issuances/bulletins/2026/bulletin-2026-51.html
