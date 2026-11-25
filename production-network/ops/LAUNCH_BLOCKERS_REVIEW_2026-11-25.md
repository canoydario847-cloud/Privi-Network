# Privi PRVI mainnet — independent launch blockers review

**Date:** 2026-11-25  
**Scope:** Read-only review of published gates, PoP candidate, genesis/supply tooling  
**Repo:** `canoydario847-cloud/Privi-Network`  
**Verdict:** **NO-GO** — financial mainnet must remain unactivated

This review does not authorize issuance, listing, migration, or validator operation.

## Executive summary

The repository correctly fail-closes production. CI, offline cap models, and research PoP modules are useful **engineering evidence only**. They do not satisfy the eight gates in `production-network/ops/MAINNET_LAUNCH_GATE.md`.

| Gate | Status | Primary blocker |
| --- | --- | --- |
| 1. Chain identity / binary | BLOCKED | No pinned Privi-custom audited binary; still upstream Cosmos EVM reference posture |
| 2. Genesis / supply | BLOCKED | Allocation worksheet TBD; SDK hard-cap keeper not integrated |
| 3. Independent validators | BLOCKED | No four operator-controlled production attestations |
| 4. Public testnet + recovery | BLOCKED | Local Docker 4-val is not multi-host independent ops |
| 5. Security audit | BLOCKED | No external audit package on a final release hash |
| 6. Operations | BLOCKED | No production RPC/monitor/on-call evidence pack |
| 7. Legal / disclosures | BLOCKED | Launch obligations and user disclosures incomplete |
| 8. Final approval | BLOCKED | No signed immutable binary+genesis+GO record |

## Code and design findings

### Point of Position (PoP)

- `POP_CONSENSUS_IMPLEMENTED = False` in `production-network/mainnet/pop_mainnet_guard.py`.
- `pop_candidate/` is explicitly **research**: certificate mechanics, durable vote lock experiment, block payload hash — not ABCI/CometBFT replacement.
- `CONSENSUS_RFC.md` correctly lists unproven assumptions (governance root compromise, no view-change, no quorum intersection proof across epochs, no execution verification).
- **Do not** treat `node --test …/test_engine.cjs` as finality or mainnet evidence.

### Supply and cap

- Proposed lifetime max **1,000,000,000 PRVI** (18 decimals → 10^27 base units) is a **policy proposal**, not an on-chain control.
- Go `capmodel` and genesis supply audit scripts are offline / time-zero checks.
- `PRVI_HARDCAP_INTEGRATION_REQUIREMENTS.md` correctly states: no production cap keeper, no full mint-route inventory on a pinned binary, no adversarial multi-host proof.

### Identity and honesty

- Chain IDs, fee denom, genesis time, and binary digests remain **TBD**.
- Upstream demo IDs (`local-4221`, EVM `262144`) must never be published as PRVI mainnet.
- BNB PRIV (`0xbf154Ff2577F4B85db7B2ee910Db5880D06e0f64` on chain 56) is separate and unchanged by these docs.

## Security-oriented launch blockers (priority)

1. **Consensus gap** — No native PoP BFT state machine bound to a Privi node binary.
2. **Mint surface** — Unenumerated bank/mint/EVM/precompile paths on the actual release source.
3. **Operator independence** — Syntactic multi-key tests ≠ separate fault domains, custody, or recovery.
4. **Genesis mutability** — Any material change after signatures invalidates the digest; ceremony not completed.
5. **Key material** — Repo policy forbids committing mnemonics/keys; enforce in CI and operator runbooks.
6. **Claim boundary** — Marketing or UI must not present TEST, localnet, or research certificates as live PRVI.

## Recommended next engineering order

1. Freeze a **candidate binary pin** (commit + reproducible build recipe) without activation.
2. Complete mint-route inventory on **that** pin; wire a consensus-persisted cap keeper design + tests (still testnet-only).
3. Expand validator failure/recovery drills (see companion test plan) on multi-host testnet only.
4. Fill genesis allocation worksheet with public addresses only; run supply audits; never paste private keys.
5. Commission external review only after binary+genesis candidates are hash-stable.

## Out of scope for this review

- Implementing a production PoP engine in this pass
- Signing genesis or releasing financial PRVI
- Operating validators or holding funds
