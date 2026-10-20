# Custom Privi Cosmos EVM app source integration — build-only milestone

**Status:** Source patch committed. Compiler and unit CI result must be verified separately. **NOT DEPLOYED**, **NO FINANCIAL MAINNET**, **NO REAL PRVI**.

## Changes

The script [apply_prvi_cap.py](../mainnet/custom-app/apply_prvi_cap.py) takes a **clean** copy of `cosmos/evm@v0.7.3`, verified at Git commit `c3ae9067a7eadcdea55a5192226916deb44c71c4`, inside a disposable folder named `.upstream-capbuild`. It will refuse any changed app source pattern, dirty checkout, unexpected tag or commit, pre-existing keeper package, or missing PRVI keeper source.

On that copy alone, the script:

1. Creates `evmd/prvicap` from the pinned SDK-backed [persistent cap keeper](../mainnet/prvicap/keeper.go) and [restriction adapter](../mainnet/prvicap/sdk_bank_adapter.go). Uses a dedicated Merkle KV `StoreKey`, not an ephemeral in-memory store.
2. Registers `prvicap.StoreKey` among the app's real `storetypes.NewKVStoreKeys`, to be mounted by the existing `app.MountKVStores(keys)`.
3. Adds `PriviCapKeeper` to the app's keeper fields.
4. Constructs `prvicap.New(runtime.NewKVStoreService(keys[prvicap.StoreKey]))` **before** other module constructors.
5. Creates the regular bank keeper, attaches its bank object store, and **then** calls `prvicap.RestrictedBank(baseBank, app.PriviCapKeeper)`. Assigns this restricted value to `app.BankKeeper` **before creating the staking, mint, EVM, IBC and ERC-20 keepers**.
6. Modifies `InitChainer` to require a real bank genesis entry, initialize module state, obtain the **declared** `aprvi` base supply and reconcile it with actual bank `GetSupply` before writing the immutable genesis-issued value. A zero-PRVI or default `atest` developer genesis is rejected.
7. Adds zero PRVI token recipients, **no** payment contract, **no** financial genesis file, **no** production chain identity, **no** keys, **no** public validator or launch command.

The separate [custom-app compile CI job](../../.github/workflows/privi-localnet-smoke.yml) checks syntax and compiles the modified actual `evmd` application and its `prvicap` package, with pinned Go 1.25.9 and the upstream SDK v0.54.3 dependencies. The [source rewrite unit tests](../mainnet/custom-app/test_apply_prvi_cap.py) check refusal on changed patterns and verify that bank injection happens before genesis initialization.

## Remaining engineering and security blockers

A successful application compile **does not** validate that PRVI is ready to run:

- **Genesis initialization order:** Real multi-module `InitGenesis` may rely on minting in other denominations while the cap keeper is still uninitialized. The current restriction intentionally fails closed before cap initialization, including for non-PRVI denominations. Actual candidate genesis integration tests are required to validate startup order and avoid bypassing the guard.
- **Direct SDK bank writes:** `UncheckedSetBalance`, native supply setters, state upgrades/migrations, IBC and ERC-20 token-pair handling and module account permission transitions must be independently enumerated, guarded or proved safe.
- **Bank keeper copy audit:** The SDK restriction creates a value-copy keeper. Every internal app module and constructor must use the restricted instance, and no subsequent unrestricted keeper can be built or injected. A source-level patch alone does not establish this property for every future module and upgrade.
- **Governance and upgrades:** Persistent cap record must survive export/import, state sync, genesis export, app upgrades, halted/resumed validators and future parameter governance without resetting or circumventing lifetime issuance. The PRVI cap record is not yet a complete registered Cosmos app module with stable upgrade/export behavior.
- **Full chain identity/tokenomics:** Reference `evmd` retains non-PRVI demo assumptions elsewhere (test denomination, EVM ID, inflation defaults, token pairs). These must be replaced and independently audited before *any* launch. This patch has **not** produced an audited Privi mainnet binary.
- **Testnet and consensus proof:** The existing four-validator CI run uses unmodified upstream `evmd` with valueless `atest`; it is **not a run of the modified PRVI application**. The modified application must be tested separately on a nonfinancial test chain after a carefully reviewed test genesis is available.
- **External authorization:** Four independently operated validators (currently **0/4 verified**, onboarding deferred), multi-host public testnet, release/genesis signatures, security review, legal requirements, operations/incident runbooks and signed activation decision remain outstanding.

**Strict decision:** mainnet launch gate 2 remains **BLOCKED**. No amount of green build-only CI replaces tests of the finalized production chain or the independent go-live gates.

## Module-facing unsafe native balance setter guard (development milestone)

The proposed custom app now supplies `prvicap.ModuleRestrictedBank` to
modules instead of the SDK raw `BaseKeeper` interface. In addition to
blocking post-genesis `aprvi` mints via the consensus cap keeper, the
module-facing `UncheckedSetBalance` method explicitly refuses native
`aprvi` mutations *before* touching bank state. A caller cannot use
`WithMintCoinsRestriction` or `WithObjStoreKey` on that wrapped module
dependency to obtain a fresh raw `BaseKeeper` copy. Bank construction
and object-store setup still happen before wrapping.

This is **not a complete security resolution**: the adapter embeds the
SDK raw keeper, which can still be extracted by Go type assertion. A
different or previously retained `BaseKeeper`, direct SDK bank collection
writes, IBC/EVM module changes, runtime upgrades, and within-block
unauthorized balance reallocation can bypass the wrapper. A real SDK
integration regression intentionally demonstrates that the original raw
keeper can still write untracked native balance. These outstanding paths
require an audited SDK-level mutation barrier, complete source graph review,
adversarial state-transition proofs, and independently verified release
before a financial mainnet.

