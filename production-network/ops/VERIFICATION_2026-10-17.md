# PRVI Technical Verification Snapshot — 2026-10-17

**Decision: NO-GO for financial mainnet and live-exchange claims.**

## Evidence actually inspected

- Workflow: [four-validator smoke CI run #139](https://github.com/canoydario847-cloud/Privi-Network/actions/runs/39066135695), associated with review head `4668134fb49c46dfaae8b8c3f1cf41745bd2501a`.
- Overall result: **failure**.
- `Offline checks` job: **success** (existing offline tests and syntax checks).
- `Build and verify four ephemeral EVM validators`: **failure**.
- Within that job: Docker environment **pass**; upstream Cosmos EVM v0.7.3 build/init **pass**; four-validator CometBFT consensus audit **pass**; Ethereum JSON-RPC check **fail**.
- Failure observed 24 attempts: `EVM chain ID mismatch`. The workflow expected numeric EVM chain ID **4221** from the local demo configuration, but the RPC returned a different numeric value; the original probe did not print the observed ID, so it **cannot be determined from these logs alone**.
- All local ephemeral validator containers were removed by the workflow cleanup.
- PR #13 had **no verified independent lawyer/code-audit approval** from GitHub Reviews when checked.

## Corrective action committed to review branch

1. EVM mismatch diagnostic now includes both expected and observed numeric ID while **still failing** on disagreement.
2. Offline CI runs tests from `production-network/ops`, including the genesis/validator evidence rejection suite.
3. Dedicated mocked test checks EVM mismatch explanation, expected acceptance and refusal of invalid/local production chain ID.
4. Listing dossier and tracker document exchange prerequisites without fictional circulation or venue approval.

## Do not bypass

Do **not** change the expected EVM ID to whatever appears merely to turn CI green. Resolve the intentional Cosmos ID / EVM ID configuration, inspect upstream v0.7.3 node options and frozen genesis, choose a unique public-testnet ID, then retest full wallet interactions, transactions and receipts. Production PRVI identifiers require separate documented approval and security testing.

## Remaining gates

No approved mainnet genesis, proven cap enforcement, independent validator infrastructure, multi-host public testnet, end-to-end EVM acceptance, completed external audit, verified counsel opinion, signed final hashes or venue asset integrations have been demonstrated.

**This review does not launch, mint, bridge, trade, or list PRVI.**

## Additional CI evidence: run #143

- [Workflow run #143](https://github.com/canoydario847-cloud/Privi-Network/actions/runs/39067107019) also ended **failure** with **offline unit tests PASS**, four local validators reaching consensus, and the EVM RPC probe failing on the same chain ID mismatch.
- Improved diagnostics captured **observed EVM ID 262144 vs wrongly expected 4221** (24 attempts).
- The upstream Cosmos EVM example-chain documentation and default EVM parameter confirm **262144 is the reference evmd numeric EVM chain ID** (separate from the local CometBFT Cosmos network string `local-4221`): https://cosmos.chaindev.net/evm/latest/documentation/getting-started/build-a-chain/quick-start and https://github.com/cosmos/evm/blob/main/x/vm/types/params.go.
- Correcting the **development-only smoke test expectation and wallet demo docs** to 262144 aligns with upstream's documented reference default, but does NOT choose or approve an EVM ID for the future custom PRVI chain.
- A passing four-validator developer smoke test would still NOT prove mainnet supply invariants, public validator independence, audited consensus code, wallet transfer / receipt functionality, or exchange readiness.
