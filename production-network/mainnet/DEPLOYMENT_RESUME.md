# Privi PRVI — deployment resume checkpoint

**FINANCIAL MAINNET NOT DEPLOYED.** This document is a source-code handoff,
not approval to mint, distribute, sell or create a financial blockchain.

## Current technical state

- The nonproduction pinned Cosmos EVM candidate compiled successfully in
  GitHub Actions run 38990882414. Its synthetic EVM chain ID was 999991, its
  synthetic Cosmos chain ID was privi-ci-nonproduction-999. That image/binary
  is NEVER a final production release.
- Mainnet review source: draft GitHub PR #10, branch
  mainnet/prvi-four-gates-preparation-20261016, based on
  mainnet/secure-launch-readiness-20261016. Keep draft and do not merge
  until reviewed.
- Existing Railway Privi Seven Validator Staging has its OWN valueless
  local-privi-seven-4221 chain and separate accounts/volumes; it is not the
  future financial PRVI blockchain. Do not copy its genesis, keys or coin.
- Native financial coin proposal: PRVI, 18 decimals, base denomination aprvi,
  cap 1,000,000,000 PRVI (exactly 10^27 aprvi). On-chain mint/cap invariants
  and genesis distribution must be independently audited.
- Proposed chain identifiers are UNRESERVED and not copied into the approved
  mainnet config. Reserve/review them independently before freezing genesis.
- The operator owner has said independent operators exist but will supply
  public details later. Do not invent names, public keys, custody or signatures.

## Eight input artifacts required before the deployment gate can evaluate release

1. **Reviewed manifest JSON**: `--manifest` with references to actual
   external audits, legal review, independent operator evidence, recovery
   rehearsals and explicit release authorization.
2. **Separately audited release config JSON**: `--config` with
   status `AUDITED_MAINNET_RELEASE_CANDIDATE`, approved unique
   Cosmos/EVM IDs, and the fixed-supply \`aprvi\` implementation.
   The design-stage file in this repository intentionally does NOT qualify.
3. **Canonical future genesis.json**: `--genesis` from a secure,
   independently reviewed genesis ceremony; real balances, on-chain vesting,
   slashing/staking parameters and seven public consensus validators.
4. **Auditor-approved allocation ledger JSON**: `--allocations` with
   verified recipient addresses and ownership, categories totalling EXACTLY
   10^27 aprvi and executable vesting schedules. Do NOT use empty templates.
5. **Audited production Cosmos EVM binary**: `--binary` built from
   reviewed source, reproducibly verified and signed. The synthetic CI executable
   is NOT approved and must NOT be supplied as this binary.
6. **Frozen public release metadata JSON**: `--release` with
   the same chain IDs and the SHA256 hashes of genesis, allocations and binary.
7. **Externally reviewed real independent operator roster JSON**: `--roster`
   with 7+ distinct human/legal controllers and key custodians, different
   provider/regions, public (never private) consensus keys and voting power.
8. **Real signed public release attestations JSON**: `--attestations`
   containing one cryptographically verified Ed25519 message per operator
   over the exact genesis, binary hash, allocations and chain identifiers.

Run the integrated read-only gate OFFLINE from a trusted machine:

```sh
python3 production-network/mainnet/deployment_readiness.py \
  --manifest /secure/reviewed-mainnet-manifest.json \
  --config /secure/audited-mainnet-source-config.json \
  --genesis /secure/canonical-genesis.json \
  --allocations /secure/reviewed-allocations.json \
  --binary /secure/audited-privi-evmd \
  --release /secure/approved-release-digests.json \
  --roster /secure/independent-operators.json \
  --attestations /secure/genesis-release-attestations.json
```

The gate combines \`mainnet_preflight.py\`,
\`validate_candidate_genesis.py\`, \`independent_operator_roster.py\`,
and the actual cryptographic \`operator-kit/ceremony_verify.py\` checks,
then cross-checks chain IDs, hashes and public keys across documents.

**A passing command is not permission to launch.** It cannot independently
establish legal ownership, external audit validity, real compliance or signer
fencing. An authorized human release committee must verify all of those.
Only then should operators independently deploy a reviewed binary and
canonical genesis with protected private signers and monitored sentry/RPC
infrastructure. Never ask operators to give the coordinator keys.

## Not yet available; cannot be claimed done

- Final reviewed unique IDs, registered network metadata or wallet support.
- Final approved allocation recipients, treasury multi-signature key custody
  and complete genesis with exactly 1B PRVI.
- Seven independently verified public operator keys and signed genesis.
- Independent code/economics audits, deployment rehearsals, incident recovery
  evidence, provider diversity, public RPC hardening and legal signoff.
- Financial PRVI mainnet live chain, circulating PRVI, token sale or liquidity.

## Safety boundary

No existing valueless TEST, BNB PRIV or Railway service should be
modified or renamed as mainnet. Keep the developer/test network separate.
CI does NOT deploy and deliberately retains no private keys.
