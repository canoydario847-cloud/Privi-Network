# PRVI Financial Mainnet — Pinned Cosmos EVM Mint-Route Inventory

**Finding:** Cosmos EVM v0.7.3 reference app has multiple native mint authorities.
**Status:** REVIEW REQUIRED / FINANCIAL MAINNET NO-GO. This scan is an **off-chain code inspection**, not a cap keeper or a code audit.

## Pinned upstream source evidence

Repo: [cosmos/evm](https://github.com/cosmos/evm/tree/v0.7.3), tag **v0.7.3**, reviewed as a *developer reference*, not a production PRVI binary.

| Entry point | Verified file | Why it matters |
|---|---|---|
| Bank keeper factory | [evmd/app.go](https://github.com/cosmos/evm/blob/v0.7.3/evmd/app.go) | Bank keeper is built with \`bankkeeper.NewBaseKeeper\`; the proposed Privi cap model is **not injected** here |
| Cosmos mint keeper and module | [evmd/app.go](https://github.com/cosmos/evm/blob/v0.7.3/evmd/app.go) | The reference app builds \`mintkeeper.NewKeeper\`, registers \`mint.NewAppModule\`, and schedules \`minttypes.ModuleName\` among begin-block modules |
| Default minting settings | [evmd/genesis.go](https://github.com/cosmos/evm/blob/v0.7.3/evmd/genesis.go) | \`NewMintGenesisState\` obtains \`minttypes.DefaultGenesisState\` then points its denomination to the reference example asset; it does not implement the PRVI lifetime cap |
| EVM ERC-20/native conversion | [x/erc20/keeper/convert.go](https://github.com/cosmos/evm/blob/v0.7.3/x/erc20/keeper/convert.go) | \`k.bankKeeper.MintCoins\` is called during a conversion; must determine whether any approved PRVI native denom can be minted by a redeem/convert route |
| Privileged module accounts | [evmd/config/permissions.go](https://github.com/cosmos/evm/blob/v0.7.3/evmd/config/permissions.go) | \`authtypes.Minter\` permission is assigned to **x/mint**, **IBC transfer**, **x/vm**, and **x/erc20** modules in the reference app |

The standalone Privi Go cap model does NOT wrap any of these keepers. This is the reason PRVI mint-control Gate 2 remains **BLOCKED**, despite developer-network and model unit test successes.

## What the automated source scan does

- It parses \`evmd/\` and \`x/\` non-test \`.go\` files with the standard-library Go AST parser; it is not a permissive grep.
- Reports selected keeper constructors, mint-module registration/defaults, and direct \`MintCoins\` call sites inside these upstream folders.
- Enumerates minter module accounts from the literal \`maccPerms\` map.
- Compares discovered call sites and minter accounts with a tightly reviewed **v0.7.3 allowlist**.
- Rejects added/deleted/directly modified mint call sites, added/removed minter permissions, missing files, source syntax errors or a checkout not exactly tagged v0.7.3.
- CI also runs mock tests proving the scanner **fails closed** on newly introduced mint calls and minter permissions.
- Its success output includes \`financial_mainnet_verdict: NO_GO\` and \`production_cap_enforcement: NOT_IMPLEMENTED\` even when the scan matches expectations.

See [scanner implementation](../mainnet/mintscan/scan.go), [negative regression tests](../mainnet/mintscan/scan_test.go) and [mainnet readiness workflow](../../.github/workflows/privi-localnet-smoke.yml).

## Scope limits — additional investigation is mandatory

- This scan **does not include the dependency implementations** of Cosmos SDK \`x/mint\`, \`x/bank\`, \`x/staking\`, \`x/distribution\`, IBC ICS-20, or separately vendored libraries. It cannot claim all actual native minting operations have been found.
- It is vulnerable to indirect calls, renamed interfaces, dynamic wrappers and a substituted SDK dependency; audits must use the **exact module versions and reproducible source graph**.
- It does not prove whether ERC-20 conversion creates **backed** derivative units or **unbacked** net issuance. That requires token-pair, escrow, denomination and full banking invariants, particularly if PRVI is registered as a native pair.
- It does not prove that a mint module is actively inflationary under finalized genesis parameters, only that it is installed and configured with a mint denom.
- Tokens wrapped through IBC are not necessarily native PRVI; official launch rules must differentiate voucher denomination paths and avoid double counting without allowing native supply inflation.
- An allowlisted mint path is **not a permitted real PRVI issuance route**. All native \`aprvi\` issuance must be disabled or atomically guarded by a consensus-integrated immutable 1B *lifetime* issuance budget, irrespective of burns.
- No authorized launch, current financial PRVI issuance, on-chain PRVI mint/cap enforcement, four independently verified operators, or public multi-host testnet is established by this source inventory.

## Next actual implementation

1. Create a reviewed **custom Privi Cosmos SDK app fork** based on exact pinned Cosmos EVM sources. Do not use \`evmd\` default genesis/permissions.
2. Make a bank or mint-guard keeper that owns **persistent** \`lifetimeIssuedNativeAprvi\` consensus state and covers every on-chain bank issuance route; specify whether \`aprvi\` starts entirely at genesis or permits a reviewed emissions budget.
3. Explicitly remove/deny unauthorized native minter permissions in x/mint, x/vm, x/erc20 and ICS-20, then test all token-pair/voucher scenarios. Never silently treat backed conversion as free issuance.
4. Test cap+1 atomic rollback, burn-remint attempted bypass, staking rewards, vesting, governance changes, module account migration, binary upgrade, state sync, query proofs, and repeat identical genesis state.
5. Have independent reviewers audit the exact production source, cap keeper, binary checksum and genesis and confirm the distinct PRVI chain and base denom IDs.
6. Deploy only to a **valueless multi-host public testnet** first; independent validator recruitment remains deferred until the owner provides operators. **Financial mainnet stays NO-GO.**
