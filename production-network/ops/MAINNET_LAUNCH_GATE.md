# Privi PRVI Mainnet Launch Readiness Gate

Status: **BLOCKED — NOT LIVE** (review initiated 2026-10-17).

This is an evidence checklist, not a launch authorization. The local Cosmos EVM `local-4221` four-validator demo is **not** the PRVI financial mainnet. TEST is permanently valueless; BNB PRIV is separate. No migration or financial transaction is authorized here.

## Owner-authorized architecture change — 2026-10-18

The owner has explicitly selected **four Privi World Corp-operated validator nodes**, not four independently owned operators. Privi's proposed financial network would therefore be **centrally operated and permissioned**, with exactly **one** operator and **four separate signing identities / fault-separated hosts**. This intentionally replaces the former independent-operator gate; it does NOT reduce the need for four distinct secured hosts, safe consensus key handling, multi-host tests, security review, signed exact release/genesis or proof of legal and operational readiness.

[Owner validator security architecture](OWNER_OPERATED_VALIDATORS.md) · [Non-live candidate inventory](owner-operated-validators.candidate.json) · [Preflight tool](owner_validator_preflight.py) · [Preliminary internal audit findings](INTERNAL_SECURITY_REVIEW_2026-10-18.md).

The inventory is currently all placeholders, and no actual production hosts or keys have been provisioned. **0/4 production validators verified, but not 0/4 independent operator companies (only one company is intended).** No claim of decentralization, asset issuance or live network is justified.

## Required evidence before GO decision

| Gate | Acceptance evidence | Status |
| --- | --- | --- |
| 1. Chain identity and binary | Reproducible pinned Privi-customized Cosmos EVM release, checksums, chain ID, fee denom, source and security review | BLOCKED |
| 2. Genesis and supply | Reproducible genesis hash signed by operators; initial balances, capped maximum 1,000,000,000 PRVI, allocations, emissions, staking, vesting, and tests proving cap invariants | BLOCKED |
| 3. Owner-operated validators | Four physically separate, uniquely keyed validator hosts in distinct fault domains, all operated by Privi World Corp as ONE permissioned centralized operator; independent host/security attestations, hardened signing, sentries, slashing/double-sign mitigation and documented common-control risks | BLOCKED |
| 4. Public testnet and CI | Four-host valueless owner-operated testnet (not the four-container same-runner reference); passing archived validator consensus and EVM transactions; wallet, upgrade, adverse-network and recovery drills | BLOCKED |
| 5. Security | Independent external code/infrastructure assessment in addition to Privi internal security review, all critical findings resolved, threat model, incident response, key rotation and backup restoration verified | BLOCKED |
| 6. Operations | Monitors, on-call, RPC rate limiting, explorer, disaster recovery rehearsal, documented maintenance and upgrade procedure | BLOCKED |
| 7. Legal and communications | Review of token launch obligations and published user disclosures; claims accurately distinguish PRVI, TEST, BNB PRIV | BLOCKED |
| 8. Final approval | Privi World Corp owner/operator and accountable security reviewers sign off on identical immutable binary + genesis hashes; published UTC activation plan and rollback/stop policy; no claim of independent validator ownership | BLOCKED |

## Cap model progress — SDK-backed build-only prototype, NOT a production cap

The [reference in-memory Go cap model](../mainnet/capmodel/cap.go) and
[consensus-KV-backed Cosmos SDK keeper](../mainnet/prvicap/keeper.go) are
implemented for engineering tests. The keeper stores immutable native aprvi
genesis allocation, denies PRVI minting through the restricted x/bank
`MintCoins` path, and checks bank supply and actual account-balance
conservation before and after module blocks.

A [source-pinned Cosmos EVM v0.7.3 patcher](../mainnet/custom-app/apply_prvi_cap.py)
wires this keeper into a **build-only** customized app and CI tests
the actual SDK banking API, cap+1 genesis boundary, disposable InitChain,
FinalizeBlock and persistence across restarts. The SDK burn-and-remint
regression also confirms an authorized burn never makes minting permissible
**through the restricted bank keeper**, including after restart.

**Unresolved consensus-critical risks:**

- Old unrestricted keeper copies and low-level bank balance setters
  may bypass the mint callback. The block-boundary reconciliation cannot
  detect unauthorized burn/remint cycles when ending net supply remains
  at or below original genesis issuance, nor all within-block mutations.
- Walking *all* account balances twice per block is O(number of accounts)
  and has not been performance-benchmarked at realistic chain scale.
- SDK, ERC-20, VM, IBC, governance and upgrade-related bypasses need
  complete dependency audit and negative integration tests.
- The pinned reference Cosmos EVM enables **permissionless ERC-20 token registration** by default. The proposed Privi genesis now rejects that default and any initial ERC-20 pair with native `aprvi`, including disabled pairs. **This protects genesis only**; native-pair registration during governance, later transactions or app upgrades still needs explicitly enforced and externally reviewed policy. The current preflight cannot establish production protection.
- A financial production release and signed actual four-host genesis do not
  exist. Current CI artifacts are isolated, disposable and **not for deployment**.

[Hard-cap integration requirements](PRVI_HARDCAP_INTEGRATION_REQUIREMENTS.md)
and [preliminary security findings](INTERNAL_SECURITY_REVIEW_2026-10-18.md)
document these gaps. **Gate 2 remains BLOCKED** until independently
verified whole-system issuance control, module upgrades and signed
genesis/release acceptance are complete.

## GO / NO-GO

**NO-GO** unless every gate has documented verifiable evidence, the sole owner/operator proves possession of **four different validator signatures on the same genesis** (one owner is not four independent operators), and the final accountable launch approvers explicitly authorize activation. Approval should be recorded with reviewer, date, commit/hash and evidence link. CI passing by itself does not constitute approval.

## Launch-day record (leave blank until confirmed)

- Privi chain ID:
- Numeric EVM chain ID:
- Native base denomination:
- Tagged binary release and SHA256:
- Genesis SHA256:
- Four separate owner-operated validator host/key attestations and independently verified genesis signatures:
- Security audit evidence:
- Production seed/sentry and RPC endpoints:
- Monitoring and incident commander:
- Planned UTC genesis:
- Authorization and approvers:
- Block-height / chain-ID verification after activation:

**Never commit mnemonics, validator private keys, seed phrases, or passwords.** Keep live financial genesis and production network unactivated while any gate is blocked.
