# Privi World Corp — Four Owner-Operated Validator Architecture

**Status:** PROPOSED / OWNER-OPERATED / BUILD-PREPARATION ONLY. **No production validators deployed. No real PRVI issued.**

## Operator control / accurate public disclosure

Privi World Corp is the **single legal/administrative validator operator** of four physically separated consensus nodes. The owner appoints administrators, authorizes binary and genesis changes, and manages treasury/governance policies. **Four validator processes do not make four independent operators**. The network is **centrally controlled and permissioned**; do not market it as independently decentralized. Users and exchanges must be able to assess this centralization transparently.

Four active CometBFT validators each have **25% voting power**. When all four are online, at least **three** must sign to exceed two-thirds voting power for finalization; loss of two nodes can halt liveness. Hosts should be in four independent failure domains (at minimum separate machines and provider accounts/network/power zones wherever practical) with hardened OS, private-management connections, different node identities, and distinct signing keys. Four nodes under one operator share policy, legal and credential-compromise risks even across four regions.

## No-secrets candidate

[owner-operated-validators.candidate.json](owner-operated-validators.candidate.json) contains four **UNASSIGNED placeholders**. It has **no real validator keys, addresses, endpoints or genesis signatures**. The [fail-closed preflight](owner_validator_preflight.py) checks exactly four node records, distinct host/fault-domain/private IP/node ID/public signing-key fingerprints/sentries, loopback RPC and metrics, separate signer attestations, 25% power each, and no embedded secrets. Draft structure may pass; release preflight always returns **NO-GO** pending actual external signed evidence.

Run:

\`\`\`sh
python3 production-network/ops/owner_validator_preflight.py production-network/ops/owner-operated-validators.candidate.json --mode draft
# Expected: DRAFT ACCEPTED; multiple NOT READY blockers; no network change.

python3 production-network/ops/owner_validator_preflight.py production-network/ops/owner-operated-validators.candidate.json --mode preflight
# Expected: exit 3, NO-GO. Never treat this as approval or a deploy command.
\`\`\`

## Minimum host and signing-key controls

1. **Four dedicated owner-operated hosts**: distinct hypervisor failure domains and host credentials; host attestation inventory held by Privi World Corp. Separate validator/sentry roles. Do not treat four containers on one CI runner as independent fault domains.
2. **Unique consensus signing keys**, generated **on each intended signer** with a reviewed CometBFT-compatible external signer or hardened local key protection. No shared mnemonics/keys across validators. Never publish a private validator key, mnemonic, test keyring or raw remote signer credential in GitHub or chat. Maintain separate signing state/backups to prevent double signing; all recovery procedures require single-active-signer guarantees.
3. **Private validator peer connectivity**: only screened sentries/peers communicate on P2P; no directly internet-accessible validator RPC, gRPC, REST, Prometheus or admin APIs. Inventory requires loopback-bound RPC/metrics, explicit network segmentation, deny-by-default ingress and rate-limited public RPC (if a public gateway is later approved).
4. **Separate operator credentials**: scoped administrative accounts, MFA and logged changes, maintenance break-glass controls, secure immutable backups of chain data and signer state, an offline incident/recovery runbook and periodic restore test.
5. **No central single-machine quorum**: validators must not share OS kernel, a single Docker daemon, one disk, one signing key or one host network. Even with separated hardware, the operator/governance remains centralized.
6. **Owner approval of exact artifacts**: review signed final genesis hash, custom binary digest, chain identity, base fee denom, PRVI mint prohibition, security audit results, operator inventory and UTC plan. Host provisioning and activation require real infrastructure and verified operator signatures. No unreviewed key automation or value-bearing chain startup.

## Candidate implementation boundaries

The current GitHub CI developer cluster [bootstrap-local-4.sh](../testnet/bootstrap-local-4.sh) builds **four disposable containers on one runner**, uses a test keyring and valueless \`atest\` with EVM developer ID 262144. It is **not** an owner-operated production validator deployment and its keys or genesis must never be reused.

The custom Privi Cosmos EVM source patch, PRVI permanent 1B cap candidate keeper, and actual bank tests are build-only. Full integration is incomplete, including upstream Cosmos SDK/IBC/EVM mint permissions, genesis and replay/upgrade safety. A public multi-host **valueless** testnet and independent security assessment are required to demonstrate the owner-operated topology safely.

## Launch policy adjustment

The superseded requirement of **four independently owned validator operators** is replaced by **four separately hosted, independently keyed validators, all operated by Privi World Corp**. This intentionally accepts centralized governance; it does **not** relax security, multi-host tests, signer protection, immutable PRVI supply review, audits, operational resilience or financial-activation gates. The owner has approved this change in this conversation; no production hardware, keys, or signed network artifacts were provided.

## Current stop gate

**0 of 4 production validator hosts configured/attested. 0 of 4 production signing identities independently verified. All financial launch gates remain NO-GO.**
