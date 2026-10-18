# Jose Coin (JOSE) contracts

Two contracts on Base:

| Contract | What it does |
|---|---|
| `JoseToken` | The JOSE coin. Fixed supply, created once at deployment and sent to the treasury wallet. No owner, no minting, no pausing, no blacklist, no upgrades. |
| `JosePayments` | Lets people spend JOSE on **Jose AI credits** (`buyCredits`) and **Jose Market orders** (`payOrder`). It never holds funds: JOSE goes straight from the payer to the treasury (credits) or to the seller plus a fee to the treasury (market). The Jose backend reads its events to add credits or mark orders paid. |

Tested with Foundry: 16 tests, including fuzz tests that check supply never changes and market payments always add up.

## Setup

```bash
# Foundry: https://book.getfoundry.sh/getting-started/installation
./install.sh          # fetches pinned OpenZeppelin 5.1.0 and forge-std
forge test            # all tests must pass
```

## Deploy

Deploy **from your own wallet** (a hardware wallet with `--ledger`, or an encrypted keystore with `cast wallet import`). Never paste a private key into a file, a chat or this repo.

Choose the numbers first:

| Setting | Meaning | Example |
|---|---|---|
| `JOSE_SUPPLY` | Total coins, ever. Can't be changed after deploy. | `5000000000` (5 billion) |
| `JOSE_TREASURY` | Wallet that receives the whole supply and all payments. Use a multisig (e.g. Safe) for real funds. | `0x1990…1048` |
| `JOSE_OWNER` | Admin of JosePayments (price, fee, pause). Defaults to the treasury. | |
| `JOSE_CREDIT_PRICE` | JOSE per AI credit, in base units (18 decimals). | `500000000000000000` = 0.5 JOSE |
| `JOSE_MARKET_FEE_BPS` | Jose Market fee. Max 1000 (10%). | `250` = 2.5% |

**1. Base Sepolia (free test network) first.** Get test ETH from a Base Sepolia faucet, then:

```bash
export JOSE_SUPPLY=5000000000 JOSE_TREASURY=0xYourWallet JOSE_CREDIT_PRICE=500000000000000000
forge script script/Deploy.s.sol --rpc-url base_sepolia --broadcast --ledger
```

Try a credit purchase and a market order end to end with the Jose backend before going further.

**2. Base mainnet.** Same command with `--rpc-url base`, plus `--verify --etherscan-api-key <key>` so the code is public on Basescan. Deployment costs a few dollars of ETH on Base.

## Making JOSE buyable

The contracts don't sell JOSE. After deployment, the usual route is:

1. Create a JOSE/ETH or JOSE/USDC pool on Uniswap (app.uniswap.org → Pool, network Base) from the treasury wallet, depositing JOSE plus ETH or USDC. Anyone can then swap for JOSE.
2. Submit the token logo and details to Basescan and to token lists (CoinGecko, Uniswap token list) so wallets show it.
3. Add the "Add JOSE to MetaMask" button on the Jose site using `wallet_watchAsset` with the token address, symbol `JOSE` and 18 decimals.

Selling JOSE that the company created, including by seeding a pool, can be treated as a securities offering depending on how it's marketed and who buys. Get counsel's written sign-off on the sale plan before step 1.

## Backend integration

- **AI credits:** the site asks the user to `approve(JosePayments, cost)` on JOSE, then calls `buyCredits(accountId, credits, maxCost)` where `accountId = keccak256(userId)`. The backend watches `CreditsPurchased` events, waits for enough confirmations, and adds `credits` to that account.
- **Jose Market:** the backend creates a random `orderId`; the buyer calls `payOrder(orderId, seller, amount)`. The backend watches `OrderPaid` and releases the order. Each `orderId` can be paid only once.
- Admin: `setPricePerCredit`, `setMarketFeeBps` (max 10%), `setTreasury`, `pause`/`unpause`. Ownership moves in two steps (`transferOwnership` then `acceptOwnership`) and can't be renounced.

## Before real money

- Independent smart-contract audit of both contracts.
- Treasury and owner on a multisig, not a single phone wallet.
- Final supply number and allocation plan written down (team, treasury, liquidity, community) and published.
