# Native PRVI POP production finality acceptance gate

Status: **NO-GO — specification and verification checklist only**. This file does not implement POP or authorize a financial launch.

## Required distinction

The upstream Cosmos EVM / CometBFT consensus path must not be represented as Privi Proof-of-Participation (POP). A research POP vote certificate is not a canonical block commit, finality proof, or slashing decision. Until a reviewed production implementation is integrated and independently tested, this gate fails closed.

## Minimum reproducible evidence

- [ ] Pin the exact production application binary, source commit, dependency lockfiles, chain ID, genesis SHA-256, and consensus configuration in a signed release manifest.
- [ ] Specify participation eligibility, identity admission and revocation, committee transitions, proposer selection, quorum weighting, fault assumptions, evidence handling, and liveness limits; document how these differ from stake-weighted PoS.
- [ ] Prove each accepted block's canonical commit is checked by production state transition and light-client verification, not merely by an offline research certificate.
- [ ] Run adversarial multi-validator tests for equivocation, duplicate/replayed votes, conflicting parents, epoch boundaries, delayed/reordered messages, crash recovery and signer-state rollback. Record commands, commits and logs.
- [ ] Demonstrate safety under the declared Byzantine fault bound and liveness under the declared network assumptions with independently controlled validator keys and hosts.
- [ ] Verify validator key isolation, durable high-watermark signing state, backups, and prevention of concurrent signers after recovery.
- [ ] Independently review the implementation and publish signed approvals tied to the tested binary and genesis hash.

## Release rule

Any missing evidence, failed test, changed binary/genesis, or unresolved critical finding means **NO-GO**. Do not activate mainnet, mint, sell, migrate, bridge, or move assets. Native PRVI (maximum 1,000,000,000), valueless TEST, BNB PRIV, and Base assets remain separate.
