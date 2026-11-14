# Native PRVI financial mainnet: executable mint-route acceptance gates

Status: REQUIRED, NOT SATISFIED. This is a review checklist, not evidence of passing tests or authorization to launch.

## Threat model

The SDK bank adapter uses `BaseKeeper.WithMintCoinsRestriction`, which returns a keeper **value copy**. A module holding the original keeper, or a separate keeper constructed later, can bypass a restriction attached only to `app.BankKeeper`. Source-marker screening, unit mocks, and build-only CI cannot establish app-wide monetary enforcement.

## Required tests in the actual pinned Cosmos EVM application fork

1. **Keeper alias bypass:** Before wrapping the bank keeper, deliberately retain an unrestricted alias in a test-only module. Attempt `MintCoins(ctx, moduleName, sdk.NewCoins(sdk.NewCoin("aprvi", positiveAmount)))` through that alias. The test must demonstrate the vulnerability on the unprotected wiring and must pass only after the application eliminates or blocks that path. No test-only bypass may ship in production.
2. **Every module mint route:** Enumerate every injected bank keeper, including mint, ERC-20, EVM, governance, IBC and migrations. For each authorized module identity, attempt native `aprvi` issuance and assert an error, unchanged bank supply, unchanged recipient balances, unchanged cap state and no events claiming a successful mint. Non-PRVI behavior must still follow SDK permissions.
3. **Mixed-denomination atomicity:** Attempt a single mint containing `aprvi` and another denomination. Assert the entire operation fails without partial writes.
4. **Burn and remint:** Burn native PRVI, then attempt to reissue the same amount. Assert rejection and immutable cumulative issuance; outstanding supply may decrease, lifetime issuance must never decrease.
5. **Restart and migration:** Export/import and restart the actual multistore; verify the issuance record is preserved exactly. Missing, malformed, duplicate or over-cap records must fail closed. Upgrades must not silently reset state.
6. **Genesis consistency:** Compare approved `aprvi` allocations to bank total supply and persisted lifetime issuance in the initialized app. Reject mismatches, excess genesis supply, wrong denomination and test/demo chain configuration.
7. **Bypass inventory:** Exercise direct balance/supply setters, genesis import, ERC-20 conversions, precompiles and module migrations that can affect `aprvi`. Assert conservation at transaction and block boundaries, not only on startup.
8. **Consensus determinism:** Run identical adversarial transactions against at least four independently operated valueless testnet validators; compare app hashes, rejection results, restart state and upgrade outcomes.

## Evidence required for acceptance

For each test, attach the exact source commit, test command, CI run URL, logs, app binary digest, SDK/Cosmos EVM dependency versions and proof that the tested code is wired into the production candidate. Independent security review must sign off on the keeper-injection inventory and bypass tests. No release, merge or financial launch is authorized by this document.

## Current gate

NO-GO: the persistent cap keeper is documented as source-implemented but **not wired into a production app**. The existing successful CI is build/unit evidence only. Production validators remain unverified.
