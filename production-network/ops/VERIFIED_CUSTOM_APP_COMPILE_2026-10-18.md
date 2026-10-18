# Privi custom Cosmos EVM build evidence — 2026-10-18

## Verified result: custom source integration compiled successfully

[GitHub Actions CI #204](https://github.com/canoydario847-cloud/Privi-Network/actions/runs/39125057087), job ID `117668340502` named **Compile pinned custom Privi app with cap guard (NO FINANCIAL DEPLOY)**, concluded **SUCCESS**.

Actual GitHub log output after compiling the Go dependency graph:

```text
?    github.com/cosmos/evm/evmd          [no test files]
?    github.com/cosmos/evm/evmd/prvicap [no test files]
```

The compilation command was:

```sh
cd "$RUNNER_TEMP/.upstream-capbuild/evmd"
GOTOOLCHAIN=local go test -mod=mod -p 2 -run '^$' -timeout 20m . ./prvicap
```

This compiles both packages but **does not execute integration tests** (`-run '^$'`). The separate SDK-v0.54.3-compatible capkeeper unit job in this same run passed, as did offline patcher regression tests and the pinned v0.7.3 upstream mint-route source audit.

The source patch was applied to a **disposable** clean clone of upstream `cosmos/evm` tag `v0.7.3` at Git SHA `c3ae9067a7eadcdea55a5192226916deb44c71c4`. The patcher adds an `evmd/prvicap` package, mounts its dedicated Cosmos KV store, installs `BaseKeeper.WithMintCoinsRestriction` *before* the SDK/EVM/IBC keeper constructors and requires positive, capped `aprvi` bank genesis supply reconciliation before initialization is accepted. It writes no persistent public release artifacts or private keys.

### Explicit limitations

- **Compile success does not verify blockchain runtime behavior.** A custom Privi app has NOT been started with an approved native PRVI genesis, has not run a financial or public testnet and has not mined any real PRVI transaction.
- **Whole-chain mint restrictions are unproven.** Untested routes include alternate bank keeper copies, low-level balance setters, ERC-20 and IBC conversion, x/mint inflation, genesis ordering, state sync and binary upgrade; an independent code audit is required.
- The disposable four-validator smoke job in this CI workflow tests **unmodified upstream `evmd` with valueless `atest`**, not this customized app. Record its final conclusion separately.
- Four independently controlled validator operators have not been verified (**0/4**, onboarding deferred by owner), no multi-host public testnet, production release hash, signed genesis, completed security/legal audits or real-asset activation approval exists.
- BNB `PRIV` remains separate from proposed native `PRVI` and developer TEST/atest is permanently valueless.

**Financial PRVI mainnet: NO-GO / INACTIVE. No PRVI coins minted, distributed or sold.**

### Next milestone

Build and execute actual SDK `bank.BaseKeeper.MintCoins` tests against a bank keeper with the cap restriction installed. Then test full custom app initialization against a **valueless PRVI-shaped** genesis on a disposable local network, followed by state migration and all minter-route bypass tests. No financial genesis until production launch gates are satisfied.
