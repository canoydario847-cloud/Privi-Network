# PRIVI Base initial liquidity — recorded allocation and safe execution gate

**Recorded authorization/request:** 2026-10-26. The project owner requested to allocate up to **1,000,000 PRIVI and 1,000,000 USDC** on Base (chain 8453) for initial token liquidity; after real trading liquidity exists, submit accurate issuer applications to the markets discussed.

**Status: read-only preflight and instructions ONLY. NO transfer, purchase, token approval, liquidity position, deposit, exchange application or sale has occurred as part of this file.** Do not confuse the amount requested with the amount held by a wallet or available to deploy.

## Exact assets and limits

| Item | Asset |
| --- | --- |
| Network | Base, chain ID 8453 |
| PRIVI token | `0xA11626baF87524e61B5697634C7Ec48D26279D6C`; on-chain label Privi / PRIVI / 18 decimals |
| USDC token | `0x833589fcd6edb6e08f4c7c32d4f71b54bda02913`; confirm 6 decimals on-chain |
| Maximum token commitment | 1,000,000 PRIVI (1,000,000 × 10^18 token units) |
| Maximum USDC commitment | 1,000,000 USDC (1,000,000 × 10^6 token units); this is one million actual USDC, not hypothetical collateral |
| Project-declared owner wallet for preliminary balance read | `0x1990589FD200E043b8C6FD9ec5956c61b3071048` — not necessarily wallet to fund the position |
| Venue candidate | Uniswap v3 on Base, before considering Aerodrome. **Venue, fee tier and price range not yet signed off; no automatic transaction** |
| Requested inventory ratio | 1 PRIVI per 1 USDC if both units deposited at exact ratio and the chosen pool supports it. Does not establish a tradeable price, peg, floor, fair value or market capitalization. |
| Existing Privi fixed-price swap desk | `0x59d0fd923242e30e48c0d5486410c3c4039785e1`. **Do not send tokens to this contract just because it exists; its security, mechanics, funding and withdrawal method require review.** |

The pool, when approved and successfully funded, would represent substantial exposure to a potentially illiquid unreviewed token and 1M USDC at risk. Pool price can move sharply, with potentially permanent loss relative to holding either token; the owner must review risk and legal requirements before transferring any asset. Creating a market does not by itself mean buyers exist or justify any market price.

## Preflight completed first — no wallet changes

The automated read-only script `scripts/base_privi_market_verify.py` now checks actual PRIVI and USDC `balanceOf` for the project's recorded owner wallet plus its ETH-for-gas balance, in Base mainnet RPC. It compares the results to both requested minimums. If a different wallet will fund, provide its PUBLIC 0x address only; never share secret keys or seed phrases. Rerun with an explicitly selected `PRIVI_TREASURY_WALLET`.

**Approval gates before opening a real pool:**

1. Identify intended funded wallet and verify it controls 1M PRIVI + 1M genuine Base USDC + adequate ETH gas; read-only preflight alone is not authority to move assets.
2. Conduct independent review of token ownership/mintability, transfer taxes/blacklists/upgradeability, verified contract source and actual USDC contract.
3. Check current Uniswap Base pool state (all fee tiers and versions) and Aerodrome state, and whether any pool already exists. Choose one supported venue and only allocate these assets ONCE, not 1M/1M to *each* platform.
4. Obtain the owner's final explicit pool design selection, including **token addresses, chain, initial price, fee tier, price range/full-range, LP NFT recipient/custodian, transaction gas and maximum effective spend**, and review official protocol interfaces/addresses. Price cannot be implied to be externally accepted simply because ratio is 1:1.
5. If using Uniswap v3, through official `https://app.uniswap.org/`: connect the actual owner wallet, switch to Base, Pool > New > select the exact token contracts, choose a fee tier and price range appropriate for potentially volatile assets, confirm the ratio/pricing and minimum amounts, review token approvals carefully, and **have the owner sign** each approval and position transaction. A pool might need initialization; don't initialize with an arbitrary spot price.
6. Wait for on-chain success; capture the actual pool address, LP position token/NFT ID, transaction hashes and pool state, and independently verify reserves. Avoid "test trading" between wallets that would create misleading volume.
7. Only then undertake official data-aggregator listing applications. Real trading/volume, verified public project ownership and legitimate activity may be prerequisites; merely creating a pool or owner self-swaps cannot satisfy all listings.

**Never** give this automation access to private keys or unbounded token allowances. Large token approvals may be dangerous; verify spender contract and approved amounts in your wallet. Prefer manual wallet authorization with a separate secure hardware wallet/multisig for $1M USDC.

## Proposed application sequence AFTER confirmed liquidity

| Venue | Prerequisite / application | Proposed status |
| --- | --- | --- |
| Uniswap | Fund and confirm position from the owner's wallet in official Uniswap frontend | BLOCKED on verified funding + signer + contract/LP review |
| Aerodrome | Separate optional venue; if desired, split the stated budget before transacting; never double-spend allocation | Not executed |
| DEX Screener | Detect legitimate indexed DEX pairs after real pool activation and qualifying trade history (indexing not guaranteed) | No submission |
| GeckoTerminal | Discover pair on indexed supported DEX using contract/pair ID; optional token information form | Not submitted |
| CoinGecko | Official request only once actively trading on a CoinGecko-tracked exchange; real volume, market and holder info, project profile | Not submitted |
| CoinMarketCap | Official request after publicly actively traded on a CMC-tracked exchange with material volume, functional site/explorer | Not submitted |
| Coinbase Exchange | Formal asset issuer listing intake at https://www.coinbase.com/listings/apply; issuer KYC/KYB and discretionary review | Not submitted |
| Kraken | Formal review at https://www.kraken.com/get-listed; token technical/security/legal documents | Not submitted |

The separate proposed native Privi PRVI mainnet and BNB PRIV assets are not included. Public website listing page exists in source but publishing is blocked by Cloudflare API credentials: https://github.com/canoydario847-cloud/Privi-Network/issues/97. Resolve the owner-managed Cloudflare secret privately; do not paste it into chat or the repo.

## Ready-to-paste issuer form text (fact-based only, update after pool launch)

Project name: Privi / Privi World Co

Asset: Privi (PRIVI), ERC-20, **Base** network (8453), contract `0xA11626baF87524e61B5697634C7Ec48D26279D6C`.

On-chain total supply at 2026-10-26 checked block 53127005: 1,000,000,000 PRIVI; NOT equivalent to circulating supply.

Software use case: Optional token payments for the Privi AI-agent network's read-only/paid tools, as documented in the public source. Runtime activity and paid customer receipts must be separately verified.

Official project repo: https://github.com/canoydario847-cloud/Privi-Network

Public explorer: https://basescan.org/token/0xA11626baF87524e61B5697634C7Ec48D26279D6C

Issuer representative: Project founder, via private official issuer account; public contact: dariocanoy@priviflow.us

**Do not fabricate these required application fields:** trading pairs, market price, 24-hour genuine trading volume, circulating supply, verified website deployment, audit reports, issuer documents, contract control disclosures, linked project-owned social accounts, legal authorization by jurisdiction, external user counts, or pool lock status.

## Current evidence links

- Read-only Base verification action: https://github.com/canoydario847-cloud/Privi-Network/actions/runs/40388159271 (confirmed token deployed, desk deployed but zero reserves at that block).
- Project declared contract code: https://github.com/canoydario847-cloud/Privi-Network/blob/main/call-server/src/privi_call/privi_token.py
- Current live preflight (see Actions runs for this branch change): https://github.com/canoydario847-cloud/Privi-Network/actions/workflows/base-privi-market-verify.yml
