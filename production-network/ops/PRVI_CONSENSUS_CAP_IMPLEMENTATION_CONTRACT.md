# PRVI consensus hard-cap integration: implementation contract

**Status: engineering design / NOT DEPLOYED / MAINNET NO-GO.** This document is a review target for a Privi-customized fork pinned to Cosmos EVM v0.7.3. It does not change the running network.

## Invariants

1. Define native base denomination `aprvi` and a **lifetime** issuance ceiling of 1,000,000,000 PRVI. Confirm the denomination exponent and exact base-unit integer with independent reviewers before coding constants.
2. At genesis, initialize `lifetimeIssued` from the total native issuance represented by genesis accounts and module balances, with reconciliation to the bank supply invariant. Never count backed representations twice.
3. For every permitted native issuance, enforce `amount > 0`, integer bounds, and `lifetimeIssued + amount <= cap` atomically in consensus KV state. The counter is monotonically nondecreasing, including after burns.
4. Reject unauthorized mint paths, including x/mint, x/erc20, x/vm, IBC transfer, governance upgrades, and module account privilege changes, unless proven incapable of unbacked native issuance.
5. Bank send, escrow release, and staking reward transfers of already-issued units must not increment the issuance counter. Mint-based staking emissions must increment it or be disabled.
6. On any failed mint, roll back both the counter and all token-state changes in the same SDK transaction/state transition. Never store consensus state in a process-local cache, external database, or Render disk.
7. Ensure the cap cannot be increased through governance, runtime configuration, chain upgrade, or reinitialization without a separately reviewed hard-fork policy. Treat all upgrade migrations as untrusted until invariant checks pass.

## Required implementation checkpoints

- Fork and pin the exact Cosmos EVM and Cosmos SDK dependency graph; reproducible build + source checksums.
- Inventory every direct and indirect `MintCoins` call and all module minter permissions, including dependencies and conversion paths.
- Implement a persistent keeper and guard at the actual bank mint authority boundary, with explicit errors and no bypass through module interfaces.
- Test genesis allocation, cap exact hit, cap+1, overflow, burn/remint, concurrent transactions, conversion/IBC backing, inflation/staking, vesting, governance, upgrade and state sync.
- Run a valueless public multi-host testnet and demonstrate matching app hashes, RPC chain identities, failure recovery, and independently controlled validator keys.
- Obtain independent audit, signed binary/genesis artifacts, and the launch approvals required by `ops/MAINNET_LAUNCH_GATE.md`.

## Release gate

No PRVI financial genesis, production mint, validator key generation, or mainnet activation is authorized by this document. TEST stays valueless and BNB PRIV stays separate. All existing launch gates remain BLOCKED until evidence is attached.
