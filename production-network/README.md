# Privi Network — Cosmos EVM Testnet Foundation

**Status: development scaffold. NOT a production mainnet or live public testnet.**

This project adds a Cosmos SDK + CometBFT + Cosmos EVM foundation **alongside** (not replacing) the existing educational JavaScript Privi explorer. No BNB Chain PRIV tokens or staking contracts are changed, and no real assets are moved.

## Components

- Upstream `cosmos/evm` `v0.7.3`, running the **evmd reference implementation**. This is not yet a Privi-customized audited binary; upstream Cosmos EVM is pre-1.0.
- Four-validator Docker **local testnet** bootstrap using upstream's `testnet init-files`, a proposed Cosmos chain ID `local-4221`, and a health-check script.
- A public multi-host testnet *launch runbook* in [ops/PUBLIC_TESTNET.md](ops/PUBLIC_TESTNET.md). Four containers on one machine are not independent validators. No public testnet is deployed by this PR.
- A conservative read-only BNB Chain PRIV ERC-20 Transfer event snapshot tool and migration planning document. It creates **no bridge, claim, lock, burn or mint**.

## Local four-validator demo

Requires Git, Make and Docker with running Docker daemon.

```bash
bash production-network/testnet/bootstrap-local-4.sh
# Then, after nodes are ready:
python3 production-network/testnet/health_check.py \
  --rpc http://localhost:26657 --rpc http://localhost:26667 \
  --rpc http://localhost:26677 --rpc http://localhost:26687
```

The script pins upstream release `v0.7.3`, builds upstream's environment and generates **developer-only** keys under `.upstream-evm/.testnets`. It refuses to overwrite existing state. Stop with `cd production-network/.upstream-evm && docker compose down`. Test RPC at `http://localhost:8545`, CometBFT RPC at `http://localhost:26657`; verify both `eth_chainId` and Cosmos chain ID. The numeric EVM chain ID and mainnet native denomination remain **unfinalized**.

## Source PRIV asset

Reported BNB Chain token: `0xbf154Ff2577F4B85db7B2ee910Db5880D06e0f64` (chain ID 56). Historical supply, token behavior, balances and staking ownership must be independently verified before any future optional migration. Read [migration/MIGRATION_PLAN.md](migration/MIGRATION_PLAN.md). Existing BNB PRIV remains unchanged.

## Strict launch gates

- [ ] Audited chain customizations, governance, native fee/staking denomination, controlled tokenomics and upgrade plan.
- [ ] Four separately operated validators, secure keys/sentries/peering, signed genesis, backing up without double signing, fault-recovery drills.
- [ ] Actual public testnet running independently operated nodes; monitoring, faucet, RPC abuse protections and explorer.
- [ ] Live health/consensus checks, MetaMask and Solidity/EVM testing, testnet-only assets.
- [ ] Independently audited BNB holder distribution, migration rights, escrow/burn backing and contracts *if* future migration is chosen.
- [ ] External code and infrastructure audit, independent validators and incident runbooks before **any** financial mainnet.

Do not deploy this directory over the current Railway JavaScript prototype. Docker localnet secrets, mnemonics and chain state must never be committed. See upstream https://github.com/cosmos/evm/tree/v0.7.3.
> **Important:** the local demo uses upstream Cosmos ID `local-4221` and expected EVM numeric chain ID `4221`. This is **not** a custom Privi-denominated network or an RPC endpoint for the existing Railway `privi-dev-1` server. See [testnet/WALLET_AND_VALIDATORS.md](testnet/WALLET_AND_VALIDATORS.md) and [ops/LEGACY_PERSISTENCE.md](ops/LEGACY_PERSISTENCE.md).
