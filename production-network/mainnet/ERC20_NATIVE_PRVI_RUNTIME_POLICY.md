# Native PRVI ERC-20 runtime safety — candidate engineering policy

**Scope:** Privi World Corp's **single-operator, four-validator** proposed Cosmos EVM chain. This engineering prototype is NOT a launched, externally audited, value-bearing mainnet. Distinct BNB PRIV remains separate and developer TEST remains permanently valueless.

## Threat

In pinned upstream Cosmos EVM `v0.7.3`, the x/erc20 module's default genesis enables `permissionless_registration`. Runtime x/erc20 keeper interfaces expose `GetParams`, `SetPermissionlessRegistration`, `GetTokenPairs`, `IsDenomRegistered`, and `SetTokenPair`. Native `aprvi` is proposed as **PRVI gas, staking, and bank supply denomination**. A token pair directly mapping that denomination could route through conversion logic and must not be treated as a separate source of free native supply.

See pinned implementation: [ERC-20 module parameter defaults](https://github.com/cosmos/evm/blob/v0.7.3/x/erc20/types/params.go), [runtime params](https://github.com/cosmos/evm/blob/v0.7.3/x/erc20/keeper/params.go), [token pair registry](https://github.com/cosmos/evm/blob/v0.7.3/x/erc20/keeper/token_pairs.go), [conversion mint paths](https://github.com/cosmos/evm/blob/v0.7.3/x/erc20/keeper/convert.go).

## Prototype controls — implemented in source, subject to CI and audit

1. **Static proposed genesis evidence audit** refuses absent `erc20` module, permissionless registration other than explicit `false`, and every token pair with `denom == aprvi`, including disabled pairs.
2. **Custom app InitChain preflight** validates decoded `erc20types.GenesisState` before any module genesis execution. It refuses permissionless registration and every token pair mapped to `aprvi`.
3. **Custom app live state check** runs after InitGenesis and before BeginBlock and after EndBlock, alongside immutable PRVI supply checks. It checks actual `app.Erc20Keeper.GetParams(ctx)` and both `IsDenomRegistered(ctx, aprvi)` and a full walk of `GetTokenPairs(ctx)`; any such state returns an error. It does not silently rewrite consensus state or grant runtime permission.
4. **Disposable CI adversarial tests** edit x/erc20 state after a valid valueless InitChain: enable permissionless registration, then insert a native APRVI token-pair entry bypassing its lookup index. A direct call to the **customized application BeginBlocker** must deny both conditions. Each fixture is restored and the valueless chain continues; no real financial issuance is involved.

## Reviewed source-pinned pre-mutation deny patch (build only)

The [pinned ERC-20 keeper source patcher](custom-app/patch_pinned_erc20_mutations.py)
now changes the disposable **exact** Cosmos EVM v0.7.3 checkout during CI, alongside the
custom app patcher. Source guards use exact-match anchors and refuse preexisting
ERC-20 source modifications. It does not change the production repository or VPS.

- `x/erc20/keeper/params.go`: `SetParams` refuses permissionless registration
  **before** changing `enable_erc20`; the direct
  `SetPermissionlessRegistration` setter returns an error before any store write.
  Governance calls through `MsgUpdateParams` propagate `SetParams` errors.
- `x/erc20/keeper/token_pairs.go`: `SetToken`, `SetTokenPair` and
  `SetDenomMap` refuse native `aprvi` before constructing/writing native
  mappings. Existing calls using these keeper methods cannot register this
  native denomination. Changes to setter signatures and all call sites
  require a full production review for swallowed errors and behavior changes.
- CI uses real custom-app InitChain fixtures, plus a runtime probe that checks
  all patched setters decline malicious inputs. The probe then **deliberately
  bypasses setters using raw temporary consensus KV writes**, to verify that
  BeginBlock's independent defense-in-depth check still refuses unsafe state.
- Source tests enforce that the deny statements precede state changes, check
  exact pinned source signatures and fail on unexpected source edits.

This narrows a serious same-block transient bypass for these specific methods;
it **does not prove that every executable route is covered**. No production
binary has been approved or deployed.

## Unsolved hard blockers

- Ordinary x/erc20 mutations now have build-only pre-write denials, but a user or module could still take an **unreviewed alternate keeper, raw KV, precompile, governance, or upgrade route** and create/remove a native pair or toggle permissionless registration within one block. Begin/end scans cannot necessarily see transient prohibited writes. A complete consensus-level mutation-route review and independent adversarial tests are still required.
- An unauthorized raw keeper copy, migration, governance module, VM precompile, upgrade or another native mint pathway could bypass these application boundary checks. All transitive SDK/IBC/EVM dependencies and upgrades must be audited against the exact release.
- State iteration is **O(token pairs) per boundary** and the bank cap reconciliation is **O(account balances)**. These prototype paths require realistic upper-bound benchmarks and a more efficient, auditable production design.
- The build-only test binary, including its throwaway keys/genesis, must never be deployed as a financial chain. Signed final binary and genesis, actual four-host permissioned validators, complete staging tests, external security review, and owner approvals remain unfulfilled.

**Verdict: FINANCIAL PRVI MAINNET NO-GO.** A passing developer test is not a claim that all conversion/mint bypasses are prevented.