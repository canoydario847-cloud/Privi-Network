# Independent security, operations, and launch-review workstream

**No external audit is claimed complete.** These are review handoff documents
for external auditors, legal counsel and real independent validator operators.

## Source-security review scope

- Pin Cosmos EVM `v0.7.3` and compare source overlay against a reproducible,
  independently built binary by SHA-256 digest and source provenance/SBOM.
- Map all `aprvi` mint authorities and entrypoints, including x/mint,
  governance upgrades, bank module sends and blocked module accounts,
  ERC20 adapters, fee market, IBC receiving paths, burns and supply APIs.
- Test invariant: *native PRVI bank supply is never greater than 10^27 aprvi*,
  before, during and after EVM gas refunds, staking, slashing, governance,
  IBC interactions and upgrades. Avoid bypass by writes to non-bank state.
- Inspect genesis auth account codecs, vesting sums, treasury grants,
  fund control, timelocks, fee-denom consistency and unbonding/slashing.
- Review privileged roles and governance upgrade powers. Rehearse emergency
  patches, rollback limitations, and malicious validator / p2p adversaries.
- Review build reproducibility, Docker provenance, dependency CVEs, signing
  keys, wallet integrations, replay protection, chain IDs, RPC DoS limits,
  public EVM gateway and sentry-only P2P exposure.

## Nonproduction rehearsal acceptance record

Before an auditor can accept a rehearsal, supply *external evidence* of:
1. All seven real operators' privately operated nodes sharing one approved
   genesis hash, verified public consensus keys, voting set and >2/3 power.
2. Private-RPC seven-of-seven commit-signature proof over multiple heights;
   `rehearsal_audit.py` provides a read-only observation at one height.
3. EVM chain-ID correctness, transaction receipt/nonce, gas and base-fee
   behavior, EVM/Comet heights and hashes, bank balances and staking.
4. A stopped-node restart, validator eviction and rejoin, non-signing sentry
   failure, three-provider outage scenario and recovery performance.
5. Encrypted backup recoverability with remote signer **fenced off** first;
   demonstrate no duplicate signer, no rollback below last signed H/R/S,
   and no `priv_validator_state.json` rewind. Have independent operators
   attest completion; ordinary snapshot restore does not prove safety.
6. On-chain vesting, governance proposal/voting, timelock execution and
   module authority checks against unfunded **valueless rehearsal assets**.
7. Disk/CPU/peer count monitoring, block-time alerting, 24/7 on-call
   escalation, emergency maintenance, ingress protection and runbooks.
8. Independent security and tokenomics audit reports, findings tracker,
   remediation evidence, qualified legal review, and an explicit *manual*
   release approval **after** all checks pass.

## Critical severity gate

Record each finding's owner, class, independent reproduction, fix commit,
test/proof, external retest and final disposition. Critical/high findings
MUST block financial launch while unresolved. Closing a GitHub issue or
passing a unit test is not an external auditor signature.

## Key compromise and recovery runbook (prepare, never automate release)

1. Isolate suspected compromised validator or remote signer and inform
   all operators. Pause any launch/restart until signing authority is known.
2. Fence off and independently confirm the OLD signer is unable to sign.
   This cannot be established by a Kubernetes/Railway success status alone.
3. Preserve immutable incident evidence and identify the latest durable,
   verified signing state H/R/S; compare it against network observed commits.
4. Validate offline that restored private state is not stale. Never reset
   or remove consensus signing state to force a restart; never clone active
   signing keys into a second running process.
5. Only the genuine operator may re-enable its own signer after review.
   Independently audit the post-restart voting signature and state.
6. Rehearse this with valueless nonproduction keys first. Do not let CI
   print or upload signing secrets.

## Operator details deferred

An empty operator template is in `operator_roster.template.json`.
It deliberately fails the `independent_operator_roster.py` readiness gate.
The owner can supply independent operator identity, infrastructure,
public consensus keys and attestations LATER. Never collect their private
signing keys or recovery seeds.

## Mainnet status

The only active Railway seven-validator deployment is a **one-owner TEST
staging network**. No audited PRVI mainnet, funded genesis, external
operators, independent audit attestation or real PRVI launch is established
by this repository change. Do not connect this PR to Railway deployment
triggers or merge it into any live branch.
