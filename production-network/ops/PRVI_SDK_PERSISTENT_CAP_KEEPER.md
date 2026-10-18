# PRVI persistent consensus-store cap keeper — SDK integration prototype

**Status: SOURCE IMPLEMENTED, NOT APP-WIRED, NOT DEPLOYED, NOT AUDITED.** All real financial mainnet launch gates remain **NO-GO**. This repo does **not** issue PRVI and does **not** activate validators.

## Target (pinned exact SDK interface)

- Cosmos EVM developer reference: \`cosmos/evm@v0.7.3\`, SDK \`github.com/cosmos/cosmos-sdk@v0.54.3\`, \`cosmossdk.io/core@v1.1.0\`.
- Proposed native base denomination: \`aprvi\`, 18 proposed decimals, maximum **1,000,000,000 PRVI** (10^27 base units). These are subject to final genesis and legal review.
- **Conservative issuance policy:** Genesis distributes no more than 1B; **NO new PRVI minting after genesis**, even if some PRVI burns. Existing PRVI is moved via normal bank send/staking/vesting operations, not newly minted.
- [\`prvicap/keeper.go\`](../mainnet/prvicap/keeper.go) uses \`corestore.KVStoreService\`, a module-owned, Merkle-backed, durable consensus KV store when provided by the Cosmos SDK runtime. It persists a **single, immutable lifetime issuance record**, checked on reads for canonicality/cap bounds. It fails closed when missing or corrupted.
- Genesis initialization must reconcile the exact approved native PRVI supply with \`BankKeeper.GetSupply(ctx,"aprvi")\`; only after validation is that initial amount stored.
- [\`prvicap/sdk_bank_adapter.go\`](../mainnet/prvicap/sdk_bank_adapter.go) is compile-checked against SDK v0.54.3 \`bankkeeper.BaseKeeper.WithMintCoinsRestriction\` and \`banktypes.MintingRestrictionFn\`. It rejects native \`aprvi\` from **every call to MintCoins made through a keeper instance with the guard attached**. It does not alter non-PRVI denom permission policy.
- A read-only \`Reconcile\` function detects supply growth above genesis issuance or maximum but does **not** prove intra-block safety or detect bypasses such as unguarded direct balance setters.

### Wiring in a future reviewed Privi fork (NOT YET DONE)

1. Fork pinned \`cosmos/evm\`; register a **dedicated persistent \`prvicap\` store key** in the app's committed \`KVStoreKeys\`, with deterministic initialization/migration and checkpoint tests. **Never** use ephemeral memory stores or process-level locks as consensus accounting.
2. Initialize \`PrviCapKeeper\` from \`runtime.NewKVStoreService(keys["prvicap"])\` after keys have been mounted. Construct base bank keeper normally; BEFORE handing it to **any other module** (including mint, ERC-20, IBC transfer, VM, staking, distribution and governance), replace it with \`app.BankKeeper = prvicap.RestrictedBank(app.BankKeeper, app.PrviCapKeeper)\`.
3. **Critical:** \`WithMintCoinsRestriction\` returns a **value copy**, not a global SDK interceptor. Unrestricted keeper copies, alternative account/bank setters, externally constructed keepers, module migrations and code compiled against the original base keeper can bypass it. Review each app keeper injection and all ways that supply changes.
4. At genesis, have the native bank module initialized *first*, then \`PrviCapKeeper.InitGenesis(ctx, reviewedAllocation, app.BankKeeper)\`; ensure the cap keeper is registered in module init order before any x/mint/VM/IBC/EVM message processing. Any missing or duplicate cap state is **fatal**. When upgrading existing state, never silently initialize/reset the cap.
5. Disallow native PRVI issuance in **x/mint**, **x/erc20 conversion**, **IBC transfer**, **x/vm precompile** and **SDK bank** paths; exhaustively audit whether other methods (\`UncheckedSetBalance\`, genesis import/export, state migration, direct store changes, supply arithmetic and upgrades) can create unauthorized PRVI even with \`MintCoins\` guarded.
6. Do not import the v0.7.3 default \`evmd\` demo genesis, EVM chain ID \`262144\`, \`atest\` fee denom, test keys, or minter/inflation settings as financial Privi configuration.
7. Implement and pass **real SDK bank transaction tests** (not just keeper stubs): verify a native PRVI \`MintCoins\` attempted by *each* module fails atomically, x/mint cannot trigger inflation for \`aprvi\`, ERC-20 conversions cannot create unbacked native units, native supply reconciles after burns/staking/fees, and export/import plus upgrade cannot reset lifetime issuance. Test both supported and unsupported app startup orders.
8. Run a public, **valueless**, genuinely multi-host independent validator testnet, repeat failure and upgrade drills, obtain independent security review, signed release/genesis and counsel/owner go-live authorization before financial mainnet.

### SDK unit tests

[\`prvicap/keeper_test.go\`](../mainnet/prvicap/keeper_test.go) contains fake-consensus-store unit tests for valid and invalid genesis, bank amount mismatch, immutable restart state, incorrect reinitialization, native mint rejection, mixed denom rejection, burned supply and remint refusal, missing/corrupt KV state, database errors and over-issuance detection. These are **not** public chain tests; the fake KV store emulates the \`corestore.KVStore\` interface.

Run in \`.github/workflows/privi-localnet-smoke.yml\` under the separate \`sdk-prvi-capkeeper\` job, using Go 1.25.9 and Cosmos SDK v0.54.3. This job verifies compile-time signature compatibility, NOT correct integration into a Privi Cosmos EVM app.

**Go/no-go:** SDK-bound keeper source existence and unit CI success do **not** clear mainnet gate 2 until the real app fork, whole-system mint-route coverage, audited immutable state transitions and approval gates have been independently demonstrated. Independent validators remain **0/4 verified** (onboarding deferred by owner). TEST/atest is permanently valueless; BNB PRIV is a separate existing asset.
