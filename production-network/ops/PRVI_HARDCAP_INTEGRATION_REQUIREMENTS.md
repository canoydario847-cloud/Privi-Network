# PRVI Financial Mainnet — Native Hard-Cap Integration Contract

**Status:** PROPOSED production integration requirements; a consensus-KV-backed cap keeper and source-pinned, build-only custom Cosmos EVM prototype exist and are tested, but **not deployed or production audited**. Financial mainnet **NO-GO**.

This document defines the **next technical acceptance gate**, not deployed or production-safe tokenomics. [The in-memory Go cap model](../mainnet/capmodel/cap.go) remains off-chain, while [the SDK-backed cap keeper](../mainnet/prvicap/keeper.go) is wired into an isolated **build-only** version of the pinned reference Cosmos EVM app through [a source patcher](../mainnet/custom-app/apply_prvi_cap.py). The latter has compile, SDK bank, consensus-state restart and ephemeral InitChain/FinalizeBlock checks, but **does not prevent minting on any deployed chain** because there is no financial Privi deployment and no complete module-bypass audit.

## Fixed policy proposal

| Parameter | Proposed rule |
| --- | --- |
| Asset | Native PRVI, separate from BNB Chain PRIV and permanently valueless developer TEST/atest |
| Maximum lifetime issuance | **1,000,000,000 PRVI** |
| Base precision | **18 decimal places**, subject to final signed specification |
| Proposed base denom | **aprvi**, subject to final audited binary/genesis review |
| Maximum base units | **1,000,000,000,000,000,000,000,000,000** (10^27) |
| Initial issuance | Actual genesis bank supply of aprvi, once validated and signed |
| Allowed later minting | **None by default** until a separately approved issuance mechanism, finite issuance budget, auditable authority and emissions schedule are finalized |
| Burning PRVI | Decreases outstanding supply but **never** decreases cumulative minted amount |
| Vesting unlock/staking delegation/fee distribution | Moves existing balances; must **not** increase cumulative minted PRVI |
| Genesis / lifetime supply check | Sum of all native PRVI issuance across genesis and every subsequent mint MUST remain <= 10^27 base units at every height |

The final production configuration may instead allocate all 1,000,000,000 PRVI at genesis. In that case the lifetime mint budget is zero for the chain's entire existence, including after burns or upgrades. An unapproved emissions rate, authority or change to the cap is **not acceptable**.

### Accounting invariants — consensus-critical

At genesis: \`lifetimeIssued = actual native bank.genesisSupply\`, \`burned = 0\`.

After an authorized mint of \`n > 0\`: \`lifetimeIssued' = lifetimeIssued + n\`, \`outstanding' = outstanding + n\`. Reject/abort the whole block-state transaction if \`lifetimeIssued' > 10^27\` or another invariant fails.

After burn of \`n > 0\`: \`burned' = burned + n\`, \`outstanding' = outstanding - n\`, \`lifetimeIssued' = lifetimeIssued\`. Do not reopen mint capacity.

At every committed state, \`outstanding = lifetimeIssued - burned\`, and real bank total supply of the approved native PRVI denom equals \`outstanding\`, after accounting for any module-specific supply behavior (which itself must be independently audited). A bank send, staking deposit, vesting unlock, governance change and fee transfer must not change cumulative issuance. State stores use deterministic arbitrary-precision integers; never floats or JavaScript numbers.

### Production integration tasks (all OPEN)

1. **Pinned custom binary**: the build-only prototype patches pinned Cosmos EVM v0.7.3 and mounts a persistent PRVI cap KV store, but a reproducible *production* release and a complete multi-module security review are **still missing**. Do not treat the unmodified upstream developer `evmd` or CI build artifact as production.
2. **Enumerate all mint routes** in *actual pinned source*: bank mint permissions, \`x/mint\` inflation, fee/rewards modules, governance authority, upgrades and migrations, and any EVM precompile/native module that can increase bank PRVI balances. Deny unspecified routes. A code comment claiming to limit minting is not a control.
3. **Atomically enforce** cap for *every* PRVI issuance route before \`bank.MintCoins\`, store cumulative ever-issued and current outstanding in the same cached state context / transaction. Never allow an unguarded minter or reset on height, module restart, governance proposal, migration, genesis export or app upgrade.
4. **Supply reconciliation**: verify whole-app genesis includes module accounts, staking, vesting, distribution and the bank supply; take deterministic before/after checkpoints. Ensure IBC vouchers, wrappers and separate BNB PRIV can never be misconstrued as native aprvi.
5. **Consensus tests**: genesis exactly at cap and below; +1 base-unit overflow; valid limited mint; simultaneous transactions; burn-and-remint attempt; staking/rewards/fees; slash/burn semantics; vesting unlock; upgrade, replay, export/import and state-sync; unauthorized module mint; withheld/invalid authority; numeric boundary tests including extremely large amounts.
6. **Adversarial integration tests** on a real independently operated, multi-host testnet. Publish actual traceable account/height evidence, not mock receipts.
7. **Independent security code review** confirms that the hard cap is effective in production state transitions and **cannot be bypassed** by any bank/SDK/native/EVM/module route. Review and sign the exact release+genesis hashes.
8. **Owner/counsel and launch governance approval** record who approved the final tokenomics, staking, vesting and allocations. Real financial activation is a separate, explicitly authorized event.

### Current evidence and gaps

- ✅ Read-only [initial genesis supply audit](../ops/genesis_supply_audit.py) checks a proposed genesis's bank supply sum and maximum at time zero only.
- ✅ [Go reference cap model](../mainnet/capmodel/cap.go) tests monotonic lifetime-issued accounting, no cap reset after burns, overflow failure, and concurrency using in-memory locks.
- ✅ **SDK-backed build-only cap keeper exists**. [Keeper source](../mainnet/prvicap/keeper.go) persists an immutable genesis supply record, denies guarded native mint operations and reconciles block-boundary bank supply and account balances. [Custom app patcher](../mainnet/custom-app/apply_prvi_cap.py) has in-CI InitChain/FinalizeBlock checks. These are **not** a production-audited, complete lifetime issuance guarantee or financial mainnet. The [mint-route inventory](MAINNET_MINT_ROUTE_INVENTORY.md) is partial and upstream scoped.
- ❌ No reviewed definitive emissions schedule, authenticated issuance/governance policy or audited staking/vesting implementation.
- ❌ No full audited Privi release/genesis pair, no four separate operational, uniquely keyed validator hosts, no public multi-host test network, no full independent production security review or final financial authorization. Architecture remains **one Privi World Corp-controlled operator running four nodes**, not four independently owned operators.

Tests for an off-chain state machine **do not satisfy gate 2** in [MAINNET_LAUNCH_GATE.md](../ops/MAINNET_LAUNCH_GATE.md). The launch verdict remains **NO-GO**.
