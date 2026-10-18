# Privi disposable EVM developer chain — Solidity and resilience checks

**Status:** CI probes are implemented on the draft readiness branch. Actual
results must be verified from GitHub Actions before claiming completion.

The CI workflow builds an ephemeral, four-validator **same-runner** upstream
Cosmos EVM developer network (`local-4221` / EVM `262144`), then:

1. Repeats read-only Ethereum RPC checks and a real **valueless `atest`**
   native wallet transfer verified by an independently implemented receipt
   checker. No PRVI or BNB PRIV accounts are used.
2. Compiles
   [PriviDevCounter.sol](contracts/PriviDevCounter.sol) with an explicitly
   pinned Solidity compiler (`solc@0.8.26`, conservative `paris` EVM
   bytecode), using no external Solidity imports.
3. Deploys that **nonfinancial** counter with a disposable account0 TEST
   signing key that remains in CI runner memory. Checks deployment receipt,
   exact runtime bytecode, initial counter value zero, one signed
   `increment()` state transaction, emitted `Incremented` event and
   persisted counter value one, with two confirmations on both transactions.
4. During a controlled outage, stops **only one** disposable local Docker
   validator, checks the other three retain a four-validator voting set,
   progress at least two heights, agree on block hashes and show greater than
   two-thirds signed voting power **without** the stopped validator signing.
5. Restarts the stopped validator and requires all four node RPC observers
   to agree on blocks, with the restored validator's **consensus signature**
   included in a subsequent finalized block. The recovery script attempts
   to restart the node in a `finally` block even on test failure.
6. Always cleans up the disposable Docker network after testing.

Execution is gated to GitHub CI (`CI=true`), explicit
`PRIVI_EPHEMERAL_TRANSFER_TEST=1` authorization and the known
local-development paths/RPC. There are **no** remotely administered nodes,
real tokens, persistent wallet keys, sales, staking payouts or mainnet
activations. Running against public networks is not supported.

### Independent evidence and limitations

- The Docker containers all share **one** machine, cloud account and
  failure domain. Passing does not establish cross-region or independent
  operator recovery.
- A temporary runner and its test chain are destroyed after execution.
  Its transaction hashes are therefore **not public explorer URLs** and
  should not be described as production on-chain data.
- The Solidity contract is a deliberately tiny test fixture, **not PRVI
  currency, a PRVI token contract, or a production smart-contract audit**.
- One successful deployment/increment/stop/restart does not show
  smart-contract security, sustained performance, upgrades, state-sync
  recovery, double-sign resistance, Byzantine safety under hostile
  operators or production failover.
- Independent public validator onboarding is **deferred at the owner's
  request**, not waived; independent verification remains **0/4**.
- Financial PRVI mainnet is **NO-GO** until a reviewed custom binary and
  real capped PRVI genesis, independent operators, multi-host public
  testnet, formal security audit and verified counsel/go-live approvals.

**Evidence links:** [draft readiness PR #13](https://github.com/canoydario847-cloud/Privi-Network/pull/13),
[previous successful native transfer evidence](../ops/VERIFIED_DEV_TRANSFER_2026-10-18.md).
