# Privi mainnet binary/genesis signed operator evidence — preproduction verifier

Status: **EVIDENCE ONLY · NO FINANCIAL MAINNET LAUNCH**.

The `verify_operator_release.cjs` command cryptographically checks Ed25519
signatures made by a previously vetted **four-or-more-operator** trust roster.
Every signature commits to exactly the same native PRVI chain identity,
candidate genesis digest, candidate binary digest, source commit, max supply,
consensus-protocol name and planned UTC activation time.

Unlike a spreadsheet of four unverified names, actual public keys must
independently sign the same transcript. Replacing the genesis or binary file,
one signer's key, changing a chain ID, choosing the upstream developer chain,
or replaying a signed release for a different height/time fails closed.

## Inputs

Keep an out-of-band, independently reviewed `trusted-operators.json`:

```json
{
  "format": "PriviIndependentOperatorRoster/v1",
  "operators": [
    {
      "operator_id": "OPERATOR_A",
      "fault_domain": "provider-a.example",
      "public_key_spki_base64": "BASE64_ED25519_SPKI_PUBLIC_DER"
    }
  ]
}
```

Populate **at least four distinct real operators**. The above is intentionally
incomplete and cannot pass verification. Real independent fault-domain
attestations and identity/KYC are external human verification tasks. One
person generating four keys **is not four independent operators**.

Prepare `release-evidence.json` with this schema:

```json
{
  "format": "PriviMainnetReleaseEvidence/v1",
  "release": {
    "cosmos_chain_id": "privi-UNAPPROVED-CANDIDATE",
    "evm_chain_id": 424242,
    "base_denom": "aprvi",
    "max_supply_whole_prvi": "1000000000",
    "consensus_protocol": "Point of Position",
    "genesis_sha256": "64 lowercase SHA-256 hex characters",
    "binary_sha256": "64 lowercase SHA-256 hex characters",
    "source_commit": "40 lowercase reviewed commit hex characters",
    "planned_genesis_utc": "2030-01-02T03:04:05Z"
  },
  "signatures": [
    {
      "operator_id": "OPERATOR_A",
      "signature_base64": "BASE64_ED25519_SIGNATURE_OVER_VERSIONED_OPERATOR_TRANSCRIPT"
    }
  ]
}
```

**Everything above is a non-operational placeholder**, including chain ID,
timestamp, sample EVM ID and keys. Complete it only with reviewed launch
values and one signature per vetted operator.

The signing transcript consists of UTF-8

```text
Privi/OperatorReleaseEvidence/v1
JSON.stringify([
 "PriviMainnetReleaseEvidence/v1",
 cosmos_chain_id, evm_chain_id, base_denom, max_supply_whole_prvi,
 consensus_protocol, genesis_sha256, binary_sha256, source_commit,
 planned_genesis_utc, operator_id, fault_domain, public_key_spki_base64
])
```

The verifier exports `message(release, operator)` to generate the exact
canonical bytes for an **independently operated, offline** Ed25519 signing
device or custodian. Every operator must manually compare SHA-256 digests and
the chain/release details on a separate trusted channel before signing. Never
send mnemonic, raw private keys or validator signer state to CI, ChatGPT or
the repository.

## Verify (read-only)

```bash
node production-network/ops/verify_operator_release.cjs \
  --manifest /secure/release-evidence.json \
  --trust-roster /secure/trusted-operators.json \
  --genesis /secure/approved-genesis.json \
  --binary /secure/approved-privi-node
```

Successful verification reports `verified_operator_signatures >= 4`,
`production_release_authorized: false` and
`financial_mainnet_activated: false`. The latter are **always false**.
A failed verification exits 1 and reports `RELEASE EVIDENCE REJECTED`.

**Critical residual launch gates:** this tool does NOT prove four
independent physical operators (only distinct keys and claimed domains);
does NOT verify signature by the Privi founder's EVM wallet; does NOT
validate the Cosmos genesis app state, canonical staking, vesting or PoP
position anchors; and cannot certify native PoP BFT finality, raw bank
keeper bypass security, external audits, capacity, custody, or network
readiness. Hashes pin bytes but are not proof of reproducible-build
provenance; the signed source commit may be unreviewed unless separately
authenticated. Never infer readiness or initiate a launch based solely on
this evidence or unit tests.

Operator signatures are not an alternative to an explicit independently
recorded human GO review against
[MAINNET_LAUNCH_GATE.md](MAINNET_LAUNCH_GATE.md).

## Security tests

```bash
node --test production-network/ops/test_verify_operator_release.cjs
```

The test suite generates random **ephemeral** Ed25519 keys and fake
disposable genesis/binary bytes. These are not production approvals.
