# PRVI mainnet — independent validator evidence template

**NO-GO / planning only.** Complete this privately for each of at least four independently controlled validator operators. Do not commit private keys, seed phrases, IP addresses, personal identity documents, credentials or unredacted contracts.

| Field | Required evidence (private record) |
| --- | --- |
| Operator reference | Non-sensitive identifier and independent reviewer |
| Custody | Evidence operator alone controls consensus signing key; backup and recovery process |
| Independence | Ownership/control attestation, hosting provider, jurisdiction and failure-domain diversity |
| Public key | Reviewed CometBFT consensus public key and exact proposed genesis mapping |
| Double-sign protection | Persistent signer state, restart/failover test and recovery runbook |
| Network security | Sentry topology, restricted RPC/P2P, patching and key access review |
| Availability | Monitoring, paging/on-call, retention and tested incident escalation |
| Testnet evidence | Same candidate binary hash, multi-host block finality and restart results |
| Approval | Reviewer identity, UTC date, signed release/genesis digest and evidence location |

## Acceptance

- Four distinct keys **alone are insufficient** to prove four independent operators.
- An operator's attestation alone does not substitute for independent custody and failure-domain verification.
- Every operator must sign the **same** reviewed binary and genesis hashes only after the independent testnet, security and supply-cap gates pass.
- Missing, conflicting, or unverifiable evidence means **NO-GO**. No mainnet activation, token minting, bridge or real-money deposit is authorized by this template.
