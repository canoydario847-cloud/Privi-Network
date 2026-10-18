# Privi PRVI Mainnet Launch Readiness Gate

Status: **BLOCKED — NOT LIVE** (review initiated 2026-10-17).

This is an evidence checklist, not a launch authorization. The local Cosmos EVM `local-4221` four-validator demo is **not** the PRVI financial mainnet. TEST is permanently valueless; BNB PRIV is separate. No migration or financial transaction is authorized here.

## Required evidence before GO decision

| Gate | Acceptance evidence | Status |
| --- | --- | --- |
| 1. Chain identity and binary | Reproducible pinned Privi-customized Cosmos EVM release, checksums, chain ID, fee denom, source and security review | BLOCKED |
| 2. Genesis and supply | Reproducible genesis hash signed by operators; initial balances, capped maximum 1,000,000,000 PRVI, allocations, emissions, staking, vesting, and tests proving cap invariants | BLOCKED |
| 3. Independent validators | At least four independently controlled production validator operators; secured key management, sentries, diversity, documented slashing/double-sign mitigation | BLOCKED |
| 4. Public testnet and CI | Multi-host public testnet; passing archived validator consensus and EVM transactions; wallet, upgrade, adverse-network and recovery drills | BLOCKED |
| 5. Security | Independent code/infrastructure audits, critical findings resolved, threat model, incident response, key rotation and backups verified | BLOCKED |
| 6. Operations | Monitors, on-call, RPC rate limiting, explorer, disaster recovery rehearsal, documented maintenance and upgrade procedure | BLOCKED |
| 7. Legal and communications | Review of token launch obligations and published user disclosures; claims accurately distinguish PRVI, TEST, BNB PRIV | BLOCKED |
| 8. Final approval | Named reviewers sign off on immutable binary + genesis hashes; published UTC activation plan and rollback/stop policy | BLOCKED |

## Cap model progress (NOT a production cap implementation)

A separately tested [proposed 1-billion lifetime PRVI cap model](../mainnet/capmodel/cap.go)
has been implemented in pure Go, with concurrent mint, overflow, burn,
and malformed-amount tests run in offline CI. This is a **reference accounting
model only**. It is not registered with the Cosmos SDK, has no consensus
KV state, is not connected to bank mint authorities and cannot limit any
currently running or future upstream `evmd` financial chain by itself.

[Production cap integration requirements](PRVI_HARDCAP_INTEGRATION_REQUIREMENTS.md)
list the still-missing mint-route audit, persisted state enforcement,
complete governance/vesting/staking/upgrade tests and external review.
**Gate 2 remains BLOCKED**, even when offline model tests pass.

## GO / NO-GO

**NO-GO** unless every gate has documented verifiable evidence, each independent operator signs the same genesis, and the final accountable launch approvers explicitly authorize activation. Approval should be recorded with reviewer, date, commit/hash and evidence link. CI passing by itself does not constitute approval.

## Launch-day record (leave blank until confirmed)

- Privi chain ID:
- Numeric EVM chain ID:
- Native base denomination:
- Tagged binary release and SHA256:
- Genesis SHA256:
- Validators and independently verified signatures:
- Security audit evidence:
- Production seed/sentry and RPC endpoints:
- Monitoring and incident commander:
- Planned UTC genesis:
- Authorization and approvers:
- Block-height / chain-ID verification after activation:

**Never commit mnemonics, validator private keys, seed phrases, or passwords.** Keep live financial genesis and production network unactivated while any gate is blocked.
