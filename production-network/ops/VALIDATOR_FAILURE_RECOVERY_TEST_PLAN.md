# Validator failure and recovery test plan (testnet only)

**Status:** Plan for **non-financial** multi-host testnet drills  
**Not:** mainnet activation, PRVI issuance, or proof of production readiness  
**Related:** `MAINNET_LAUNCH_GATE.md` gate 4, `CONSENSUS_RFC.md` threat model

## Goals

Demonstrate that **at least four independently controlled** test validators can:

1. Keep finalizing under single-validator loss
2. Refuse double-sign / equivocation where the protocol defines evidence
3. Recover from process crash, disk full, and clock skew without silent fork acceptance
4. Restore from backup without reusing consensus keys unsafely

Passing these drills **does not** flip the mainnet gate to GO.

## Environment requirements

| Requirement | Minimum |
| --- | --- |
| Hosts | 4+ distinct machines or VPCs (not four containers on one node claiming independence) |
| Binary | Same pinned build hash on every host |
| Genesis | Single signed **testnet** genesis hash |
| Keys | Separate consensus keys per operator; no shared mnemonic |
| Network | Documented peers/sentries; ability to partition traffic in a lab |
| Observability | RPC height, voting power, peer count, disk, and process health exported |

Local Docker `bootstrap-local-4.sh` may be used for **smoke only**. It does not satisfy independence.

## Test matrix

### A. Process failure

| ID | Procedure | Pass criteria |
| --- | --- | --- |
| A1 | Kill validator process on one host during steady state | Chain continues; height advances on remaining ≥2/3 voting power |
| A2 | Restart killed validator | Catches up; no conflicting commit for prior heights |
| A3 | Kill 2 of 4 simultaneously (if N=4, power assumes equal) | Document whether liveness stalls (expected if <2/3); no conflicting finality |

### B. Disk and state

| ID | Procedure | Pass criteria |
| --- | --- | --- |
| B1 | Fill disk on one validator data volume | Node fails closed; others continue |
| B2 | Restore from documented snapshot/backup onto clean host | Rejoins with same consensus identity only if policy allows; otherwise new identity + governance path |
| B3 | Delete local state and state-sync (if enabled) | Reaches network height; app hash matches peers at same height |

### C. Network partition

| ID | Procedure | Pass criteria |
| --- | --- | --- |
| C1 | Isolate one validator | Majority continues; isolated node does not finalize a conflicting branch that later survives |
| C2 | Split 2+2 (N=4) | Neither side finalizes under honest majority rules; heal without manual height rollback of committed blocks |
| C3 | Prolonged partition then heal | Single canonical chain; no dual finality |

### D. Equivocation / key misuse (research + protocol)

| ID | Procedure | Pass criteria |
| --- | --- | --- |
| D1 | Attempt two different votes same height/round with same key | Rejected or evidenced per protocol; node/operator runbook triggered |
| D2 | Copy consensus key to second machine and dual-run | Detection + documented response (key tombstone / tombstone process) |
| D3 | Restart after crash mid-sign | Durable lock / double-sign protection holds (where implemented) |

PoP research modules (`persistent_vote_guard.cjs`) may be exercised offline; they are **not** substitutes for node-integrated protection.

### E. Clock and dependency failure

| ID | Procedure | Pass criteria |
| --- | --- | --- |
| E1 | Skew system clock ± a few minutes on one host | Node either corrects via NTP policy or fails closed without poisoning peers |
| E2 | RPC dependency down (explorer/indexer only) | Consensus unaffected |
| E3 | Seed/sentry loss | Validators with remaining peers continue; document recovery of topology |

## Evidence package (per drill)

For each ID record:

- UTC start/end
- Binary SHA-256 and genesis SHA-256
- Host identities (no private keys)
- Heights before/after
- Logs (redact secrets)
- Pass/fail and residual risk

Store outside the public repo if logs contain infrastructure detail you do not want public; publish hashes and summaries if needed for gate 4.

## Explicit non-goals

- Proving PoP BFT safety theorems
- Authorizing financial mainnet
- Using production PRVI keys or mainnet genesis
- Claiming four local containers equal four independent operators
