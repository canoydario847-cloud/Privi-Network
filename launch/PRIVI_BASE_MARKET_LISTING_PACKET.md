# Privi (PRIVI) on Base — exchange listing and trading-readiness dossier

**Prepared 2026-10-26 | Project: Privi World Co | Contact: dariocanoy@priviflow.us**

**Status: listing preparation, not a market launch.** This file does not establish that a pool exists, a swap is fillable, an exchange approved the asset, or that token sales are authorized in any jurisdiction.

## Verified Base state at block 53,127,005 (2026-10-26 19:35 UTC)

A public Base JSON-RPC read-only CI run at [this GitHub Actions execution](https://github.com/canoydario847-cloud/Privi-Network/actions/runs/40388159271) returned **success** and confirmed the following **at that block only**:

- Bytecode present: PRIVI ERC-20 and the reported PRIVI/USDC swap desk.
- On-chain ERC-20 name **Privi**, symbol **PRIVI**, decimals **18**, total supply **1,000,000,000 PRIVI** (not verified circulating supply).
- Swap desk base token and USDC quote match the proposed pair; paused = false.
- Both the swap desk's available PRIVI and its USDC reserve were **zero**. Its configured price is **1 USDC per PRIVI**, but this is NOT a market price and cannot be filled at the observed reserves.
- No Uniswap v3 or Aerodrome **classic** pool returned for the examined PRIVI/USDC and PRIVI/WETH pairs. **Uniswap v4, Aerodrome Slipstream, and other market types were not scanned**; this is not proof no market exists anywhere.

These observations are a dated snapshot. All reserves, listings, circulating supply, and any eventual trading activity must be checked again before public sale or venue application. No price/availability is guaranteed.

## Identity from the Privi-Network source code

| Field | Project-declared value or validation |
| --- | --- |
| Asset type | ERC-20 on Base mainnet, chain ID 8453 |
| Contract | 0xA11626baF87524e61B5697634C7Ec48D26279D6C |
| Project code label | PRIVI, 18 decimals — confirm with on-chain contract |
| Contract explorer | https://basescan.org/token/0xA11626baF87524e61B5697634C7Ec48D26279D6C |
| Swap desk referenced in code | 0x59d0fd923242e30e48c0d5486410c3c4039785e1 |
| Desk asset pairing in code | PRIVI / Base USDC; current balances, pricing and paused status not independently verified |
| Source | https://github.com/canoydario847-cloud/Privi-Network/blob/main/call-server/src/privi_call/privi_token.py |
| Investor or customer demand, volume, pool liquidity | UNKNOWN — never invent data |
| Supply and holder distribution | UNKNOWN — verify on chain |
| Contract owner, mint privileges, audit, legal classification | UNKNOWN — require due diligence |
| Public token information page | https://www.privishine.info/base-token.html — verify deployment first |

This is NOT BNB PRIV and NOT the proposed native PRVI Cosmos EVM coin. The current devnet TEST assets remain valueless.

## Verification checklist before proposing a trade

1. Check Base chain ID is 8453, then call eth_getCode against both the exact token and swap-desk addresses. Confirm the deployed contract's name(), symbol(), decimals(), totalSupply() and that published verified source, if any, matches the address.
2. Analyze mint, burn, freeze, blacklist, owner/upgrader, fee and transfer restrictions. Obtain an independent contract security review; document token-holder and treasury allocations/vesting without inventing anything.
3. Read swap desk base, quote, price scale, paused status, actual available token reserve and USDC reserve. A displayed fixed price is not proof that either side of a swap is executable.
4. Check actual pool contracts on Uniswap / Aerodrome, including Uniswap v4 where applicable. Verify real reserves, slippage, buy/sell route, current block and timestamp. Existing Privi code reports v3/Aerodrome pools but does not by itself establish v4 market state.
5. Never create fake volume or use wash trades. If liquidity is absent, a wallet holder must explicitly approve what tokens and paired capital to deposit, the pricing, venue, fees, slippage and LP custody. Depositing liquidity has financial risk and is NOT a free listing.
6. Publish the exact verified address and public proof of issuer control on an official website and connected social account. Keep sensitive KYB and signers' keys off public GitHub.
7. Obtain independent legal/regulatory advice before marketing token sales to customers in the U.S. or worldwide.

## Venue plan and verified official submission routes

| Platform | How a real listing or discovery works | Status |
| --- | --- | --- |
| Uniswap, https://app.uniswap.org/ | Permissionless Base liquidity pools; actual liquidity and owner wallet transactions needed before swaps can fill | Not independently verified; no liquidity transaction executed |
| Aerodrome, https://aerodrome.finance/ | Base liquidity pool subject to wallet funding and liquidity-provider risks | Not independently verified; no liquidity transaction executed |
| DEX Screener, https://docs.dexscreener.com/token-listing | Automatic indexing once a supported pool exists and at least one transaction occurs | Not independently verified |
| GeckoTerminal, https://support.coingecko.com/articles/6697868326-how-do-i-list-my-token-on-geckoterminal | Look up token by exact Base contract after legitimate trading on a tracked pool | Not independently verified |
| CoinGecko, https://partner.coingecko.com/request-form/new | Active listing needs trading on a tracked exchange; owner verification post and complete market/asset details | Not submitted |
| CoinMarketCap, https://coinmarketcap.com/request/ | Official new asset request, supported active market and independently verifiable data | Not submitted |
| Coinbase Exchange, https://www.coinbase.com/listings/apply | Issuer intake plus technical/legal/security, ownership, company/UBO and market review | Not submitted |
| Kraken, https://www.kraken.com/get-listed | One issuer application per token, including tokenomics, security, liquidity, ownership and legal information | Not submitted |

**Important:** Coinbase Wallet compatibility does not equal trading on Coinbase Exchange. A tracker is not a trading exchange. A public contract page is not an approved centralized exchange listing. A crypto exchange is not guaranteed to support every country or user.

## Application facts that can be stated today

Project: Privi World Co. Founder: Dario Canoy (per repository). Application subject: project-declared ERC-20 PRIVI token on Base, not native PRVI. Public software use case: AI-agent routing, audit records and verification. The source includes a read-only token market interface and optional PRIVI payment logic for MCP service calls when configured; actual runtime activation must be independently checked. There is NO confirmed real price, token utilization or trading volume in this dossier.

Complete before submitting: incorporated entity and authorized issuer verification, smart contract validation/audit, signed public issuer confirmation, logo, current operating website, supply and vesting schedule, distribution, listing pair links and real volume/liquidity, detailed token utility, audited financial controls as applicable, team/UBO data shared privately with venues, legal opinion and geographic restrictions.

## Sample notice only — do not claim a listing

Privi World Co's public source code references 0xA11626baF87524e61B5697634C7Ec48D26279D6C as the PRIVI token on Base. Always verify metadata and liquidity independently. This asset is not BNB PRIV or the planned native PRVI coin. We do not promise exchange access, a price, liquidity, profit or investment returns.

## Approval gates

- [ ] Token chain contract, circulating supply, permissions, and balances confirmed.
- [ ] Legal and issuer review complete; only permitted jurisdictions marketed to.
- [ ] If creating or funding a liquidity pool: wallet owner approves exact tokens, USD-equivalent capital, price, slippage and fees, after independent contract/security review.
- [ ] Real market exists and is active; record pair address and real daily trade/volume; never manufacture volume.
- [ ] Publisher logs every actual venue submission, official form reference ID, approval or rejection honestly.
- [ ] Do not include private credentials or KYB files in a public repo.
