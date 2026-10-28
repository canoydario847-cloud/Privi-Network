# Synthetic RAAA / Privi independent evidence evaluation

**Status: local, synthetic-only engineering example.** Not a Privi production endpoint,
not an RAAA integration, not HIPAA compliance evidence, not an accepted client engagement,
and not proof that an authorized action actually occurred.

This reference package responds to RAAA's initial technical evaluation requirements:
* a signed authorization decision;
* a separately signed **reported** execution outcome;
* linkage to synthetic tenant, actor, action, policy ID/version/digest, approval reference,
  and both software versions;
* independently supplied public keys for offline checks;
* a chain head, monotonic event order, tamper and duplicate-event tests.

Unlike a product screenshot, these are actual local Ed25519 signatures. The **private
keys are fresh, test-only keys generated in memory** and are never saved. This sample
does *not* use Privi Ledger signing keys or attest that RAAA authorized anything.

## Generate a signed example and verify offline

Requires **Node.js 20+**. No packages, service signup, network requests or funds required.

Run from this folder:

```sh
node demo.cjs create ./sample
node demo.cjs verify ./sample/receipt.json ./sample/trusted-keys.json
node --test test_demo.cjs
```

The first command generates two files in `sample/`:

* `receipt.json` — authorization and execution-report records, separate signatures,
  hash-chain linkage and signed head.
* `trusted-keys.json` — the *public* Ed25519 keys and key fingerprints for two
  independently generated test signers. It contains no private keys.

Expected result:

```text
PASS 2 synthetic signatures and event linkage
NOT PROVEN: real action execution, human approval, tenant authentication or compliance
```

The verifier deliberately requires a **separate trust-file argument**. For genuine
independent evaluation, the reviewer must authenticate and pin the public key fingerprints
through a separate trusted channel. Receiving `receipt.json` and
`trusted-keys.json` together from the same untrusted sender does **not** establish
the sender's identity. The signed event fields are integrity-checked, not independently
proven fact.

Test tampering: edit `sample/receipt.json` to change `result`, `actor_id`,
`approval_id`, `policy_sha256`, or `software_version`; verification exits nonzero.
The test suite also checks deletion/reordering, signature substitution, and replay
via duplicate event records. Run `create` in a *new* directory to generate a fresh
pair; it will never overwrite existing demonstration files.

## What the fields mean

| Field | Meaning | Proof provided by **this** demo |
|---|---|---|
| `tenant_id`, `actor_id`, `action_id` | Claimed scope and actor/action identities | Both signers bound the same strings; identity authentication not proven |
| `policy_id`, `policy_version`, `policy_sha256` | Identifies a fictional policy | Digest and version preserved; policy enforcement not independently proven |
| `approval_id`, `approval_evidence_type` | References a synthetic approval | Reference integrity only; **not** human authorization evidence |
| `software_version` | Claimed component version at each step | Signed metadata, not software supply-chain attestation |
| `result` on authorization | `allow` | Signature verifies that the toy authorization signer asserted it |
| `result` on execution | `reported_success` | Signature verifies what the toy execution reporter *claimed* |
| `external_ack_id` | Synthetic acknowledgment | Deliberately fictional; *not* an independently confirmed system receipt |
| `authorization_entry_hash`, `previous_entry_hash` | Cryptographically joins outcome to decision | Verifiable linkage and ordering in the two-record specimen |
| `entry_hash`, `signature_b64` | SHA-256 and Ed25519 proof | Offline integrity and authentication against pinned demonstration keys |

**Critical distinction:** A valid execution report is evidence that the **signer reported**
an outcome, not evidence that the outcome happened. A full RAAA evaluation must add
an authenticated execution-system acknowledgment or independently observable effect,
tied to the action ID and the authorized policy version.

## Relationship to existing Privi services

These are repository-documented engineering interfaces, **not exercised or depended on
by the local demo**:

* [Privi Ledger](../../ledger-server/README.md) describes `ledger_record_action`,
  `ledger_audit_stream`, `ledger_evidence_bundle` and offline
  `src/privi_ledger/verify_bundle.py`.
* [Privi Anchor](../../anchor-server/README.md) describes `anchor_verify`.
* [Privi Live](../../ledger-server/README.md) describes human approvals and one-use
  authorization references.

For an actual integration, the tenant's authorized agent should create an
organization-scoped Ledger stream; its execution platform must produce separate
authenticated outcome evidence; and an evaluator must export a Ledger evidence
bundle and independently verify signatures and the issuer's pinned keys.
The signed toy format here is **not** the Ledger production evidence-bundle format
and cannot be passed to `verify_bundle.py` unchanged.

## Evaluation data, commercial and operational boundaries

* **No PHI or customer data**. Names, actors, IDs, approvals and event details are
  unmistakably synthetic and embedded in the source.
* No Google Drive/Render writes, blockchain transactions, payment requests, USDC or
  PRVI token movement, wallet key use, or actual agent execution.
* No claim of operational key rotation, revocation, issuer identity, audit coverage,
  durable production backups, event completeness, HIPAA, SOC 2 or production readiness.
* A recorded event cannot establish that **missing** events never happened. Production
  review must consider source telemetry, gap detection, external checkpoints,
  monotonic sequencing across restarts, retention/deletion, secure key custody and
  revocation behavior.
* Proposed initial commercial step: **mutual, unfunded technical scoping only**;
  any formal paid proof of concept requires a separately agreed written scope,
  milestones, funding party and deliverables.

### Outstanding questions for RAAA

1. Which execution system can provide a **separate signed acknowledgment** linking an
   actual tool invocation to a decision/action ID?
2. What policy-version identifier and actor authentication evidence does RAAA expose?
3. Which claims must remain verifiable **without exporting PHI**?
4. Which party would own each signing key, retention process, revocation list and
   trusted verification-key distribution?

This is an isolated demonstration, intended for code review before any client or
production trial.
