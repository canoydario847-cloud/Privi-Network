# Privi public multi-validator testnet runbook (NOT DEPLOYED)

The 4-node upstream Docker quickstart is a **single-machine developer example**. It is not public, independently operated, or fault-domain resilient. Do not expose its developer keys or call it production.

## Public testnet preparation

1. Recruit >=4 genuinely independent validator operators, each controlling their own machine, region, infrastructure and validator signing keys. Four equally weighted validators offer tolerance of one Byzantine/offline validator if >2/3 voting power continues participating.
2. Select a reviewed Cosmos EVM release (scaffold currently pins v0.7.3) and freeze full dependency checksums. Upstream `evmd` is an example chain; production modifications need audits.
3. Choose and review a unique Privi Cosmos chain ID (NOT upstream demo `local-4221`), an **independently tested numeric EVM chain ID**, native gas/stake denom with 18 decimals, valueless testnet faucet allocation, fee rates, epoch/governance and slashing parameters. Current demo does not finalize these economics.
4. Conduct an offline genesis ceremony: each validator operator independently generates signing and P2P keys; send **public keys and signed gentxs only**, not private keys. Coordinator publishes a single reviewed genesis file and SHA-256 digest; every participant confirms it before launch.
5. Deploy one validator node plus independent sentries per operator. Secure 26656 P2P via allowlists or trusted peer networking; don't expose validator remote signer, database, admin or unrestricted API ports. Put 26657 and EVM 8545 RPC behind dedicated monitored rate-limited gateway nodes.
6. Store validator state on encrypted persistent disks; test secret rotation, snapshot/restore, monitoring and no-double-sign recovery. A single Railway region with four containers remains a correlated failure domain.
7. Verify actual validator **voting-power set** using CometBFT `/validators` and `/commit` rather than counting RPC endpoints. All validators should have separate consensus addresses and collectively commit blocks with >2/3 voting power.
8. Check Cosmos consensus and EVM block heights, `eth_chainId`, receipts, smart contracts, JSON-RPC methods, wallet compatibility, fee handling, testnet staking, explorer indexing, upgrades and failure recovery.
9. Open read-only public RPC and explorer with abuse limits and uptime alarms, publish chain metadata and faucet. Do **not** fund users with live BNB PRIV or move real assets.

## Proposed domains — NOT LIVE

- `rpc-testnet.priviflow.us`
- `explorer-testnet.priviflow.us`
- `status-testnet.priviflow.us`

DNS and TLS must be configured **after** real infrastructure exists. Existing JavaScript prototype Railway service stays separate. Production mainnet is prohibited until code/infrastructure audits and independent validator acceptance.
