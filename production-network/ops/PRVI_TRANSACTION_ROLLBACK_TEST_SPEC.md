# PRVI transaction rollback integration test — implementation contract

**Status: test design only; not yet executed. Financial mainnet: NO-GO.**

## Why this test is required

Keeper unit tests with a fake KV store verify rejection paths, but do **not** prove that an actual Cosmos SDK / Cosmos EVM transaction uses a cached state context and discards all writes on error. A passing ephemeral four-validator smoke test also does not prove this property.

## Build-only test harness

1. Pin the same reviewed Cosmos SDK v0.54.3 and Cosmos EVM v0.7.3 revisions as the custom Privi app. Build the disposable patched SDK module in a CI temporary directory, not the Go module cache or a production host.
2. Initialize an isolated in-memory app with a deterministic **valueless** genesis and PRVI-like native test denom; never connect this harness to mainnet RPC or production signing keys.
3. Register a **test-only** message handler that, within a single SDK transaction, writes a sentinel KV key and a test account balance using the supported bank keeper path, then returns a deliberate sentinel error. The handler must not be linked into production binaries.
4. Submit a signed transaction via the real transaction execution pipeline (including ante handler and message router). Check its response reports failure, finalize/commit the block, then query **committed** balances, supply, sentinel key, cap keeper snapshot, and app hash.
5. Repeat for a multi-message transaction: the first message succeeds and writes, the second deliberately fails. Verify **all** writes from that transaction are discarded.
6. Repeat with a deliberate panic in the test-only handler, if supported by the pinned execution pipeline. Confirm the app's documented panic handling and no persisted partial state. Do not assume every panic is recoverable.
7. Add a control transaction that succeeds and is committed. Verify its expected writes persist, proving the test harness is not merely ignoring all transactions.
8. Test a rejected native issuance attempt through the **actual** bank keeper and transaction path. Assert no new native supply, no cap-state change, and no successful receipt.
9. Capture sanitized before/after state roots, account balances, total supply, cap state, transaction response codes, and source commit for each case.

## Hard assertions

- A failed transaction never changes committed bank balance, native supply, sentinel key, or PRVI cap record.
- A later failed message rolls back earlier messages in the **same transaction**.
- A successful control transaction commits its state changes.
- No test-only failure or mint bypass handler is registered in the production app.
- Unexpected errors, skipped cases, and absent evidence fail the CI job; they are not warnings.

## Exit criteria

The test must run as an automated job on the pinned custom app, not a fake-KV keeper test or static source check. A maintainer must review the actual SDK cache/commit boundaries, and independent security review must validate any custom SDK patches. Until this is implemented and passing, T03 of PRVI_MULTIHOST_TESTNET_ACCEPTANCE.md remains **UNVERIFIED** and the financial mainnet launch gate remains **NO-GO**.
