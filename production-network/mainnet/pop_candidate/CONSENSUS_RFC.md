# Privi Point of Position — proposed validator-finality design (research v0)

**Research only. NOT consensus deployed, a PoP chain, a public testnet,
a mainnet launch, or a replacement for CometBFT.**

## What comes from the author's PoP paper

The *Point of Position: A New Framework for True Asset Valuation* paper
(Dario Canoy, 2026) describes a cryptographically chained position stamp:

    PoP:COMPANY:ZONE:SEQUENCE

It also derives a data *valuation leverage factor* from frequency R and
confirmed on-ledger duration D:

    F = min(1, R/50)
    T = min(1, D/365)
    L = 1 + 1.5*(0.6*F + 0.4*T)

Those formulas are already available to the Privi-only IoT accounting
prototype, with no real PRVI issuance. They do NOT by themselves determine
validator eligibility, propose a Byzantine-safe vote algorithm, prove network
fault tolerance or prescribe honest-node locking rules.

**All validator-finality rules described below are additional, unreviewed
engineering proposals.** Calling the proposal "PoP" does not confer security.

## Candidate architecture (not integrated with running blockchain)

* Only independently authenticated Privi-native positions can anchor validator
  identities. The draft research position uses
  \`PoP:COMPANY:VALIDATOR/AUTH:SEQUENCE\`; it is distinct from IoT data zones.
* Admission is signed by an explicit PoP governance authorization root after
  a separate, manual identity/fault-domain verification. This is intentionally
  a **permissioned research admission** mechanism. It is neither stake-weighted
  voting (PoS) nor PoSA, and does not claim permissionless Sybil resistance.
* Each validator has exactly one active Ed25519 public identity, one admitted
  operator, one attested failure domain, one confirmed native Privi position
  commitment and exactly **one vote**. IoT transaction frequency, wallet PRVI
  balances and PoP valuation multipliers **do not grant voting power**.
* All admission and vote signatures are domain-separated by candidate protocol
  version, exact research chain ID, genesis hash and membership epoch; proposal
  votes also commit to height, round, previous block hash, candidate block hash
  and designated proposer.
* The deterministic **research-only** proposer uses a versioned
  `Privi/PoP/Research/ProposerElection/v2` seed: SHA-256 of the UTF-8
  JSON array [version tag, chain ID, genesis hash, epoch, governance key
  fingerprint, sorted admitted validator key fingerprints, height, round],
  interpreted as a big-endian integer modulo validator count. Binding the
  actual admitted signer roster avoids reusing the same election seed for
  different committees with identical sizes. Reordering registry JSON cannot
  change election order. This version change is NOT compatible with earlier
  research proposer selection and is NOT a reviewed production upgrade.
  The result remains predictable from public data: it provides **no**
  unpredictability, fairness guarantee, Sybil resistance, censorship
  resistance, or production consensus.
* A prototype commit certificate for N candidate validators requires
  \`floor(2*N/3) + 1\` **distinct valid Ed25519 signatures** to the same
  proposal. N must be between 4 and 31 in tests. An in-memory model rejects
  equivocation at the same height (including across rounds), but it is NOT a
  crash-safe signing service.

**Research certificate result semantics:** The verifier returns `valid:true`
only when the candidate proposal and distinct Ed25519 quorum signatures
validate against the admitted research committee. The result now exposes
the signed research chain ID, genesis hash, governance admission key
fingerprint, previous block hash and block hash for explicit provenance.
It always returns `finalized:false`, `validatesExecution:false`,
`validatorIndependenceVerified:false`, and `productionConsensus:false`.
These are explicit **non-finality** flags, not a path to production approval.
The certificate also returns a lexicographically sorted, frozen `signerIds`
array of the verified admitted validator key fingerprints. This makes research
quorum attribution independent of vote arrival order and prevents accidental
post-verification mutation of the returned signer list. It is not an
independently verifiable proof export: the underlying signatures and proposal
must still be retained and checked against the admitted registry.
A quorum signature alone cannot establish canonical chain ancestry, execution,
validator independence or a safe financial settlement.

## What "PoP only" means for official IoT features

On the official Privi IoT contract, the Privi administrator enrolls each
developer gateway first. Device registration binds a company to a signed
Ed25519 identity. Every device event commits to the Privi-only transaction
recipient and PoP stamp; position counters are shared by all devices for
the same company and zone. External chains, bridges, pairs, unregistered
developers and automatic token payouts are excluded.

This control does not force unrelated developers to use Privi for independent
software. Licensing enforcement is separate from native contract permissions.

## Threat model and explicit unproven assumptions

1. The governance Ed25519 root and admitted validators are assumed honest
   enough for correct admissions. A compromised root can forge identities.
2. Public key, operator and fault-domain uniqueness are syntactic checks, not
   independent evidence that the operators are genuinely separate.
3. \`anchorBlockHash\` is an attested datum in this research module; it is
   **not** cryptographically proven against a final native Privi state root.
4. No actual proposer/broadcast/prevote/precommit state machine, pacemaker,
   byzantine view-change, consensus store, network transport or ABCI binding
   exists in the research verifier.
5. A single certificate's signature count cannot prove *global safety* across
   competing blocks. A true BFT protocol needs provable intersection under
   f < N/3 Byzantine faults, honest non-equivocation, proposal/lock and
   view-change rules, evidence propagation and durable signing-state recovery.
6. Membership changes across epochs can invalidate quorum intersection unless
   an explicitly finalized joint-consensus transition or epoch-proof scheme
   is implemented.
7. No deterministic execution validation, block availability, data sampling,
   mempool fairness, denial-of-service limits, fork choice, block/height range
   bounds for untrusted sockets, or multi-client interop implementation exists.
8. No integration tests prove 4 independently operated Privi PoP validators,
   network partitions, malicious proposer censorship, node replacement or
   unsigned state roots.
9. Native PRVI financial safety is blocked independently by unreviewed SDK
   bank collection/KV, IBC/EVM, upgrade and mint routes in draft PR #21.
10. The current Cosmos EVM reference network is *not* PoP consensus. Nothing in
    this module may be included in a release certificate as deployed finality.

## Required engineering milestones, in order

1. **Protocol review**: write formal safety and liveness assumptions, define
   PoP validator admission from objectively verifiable ledger position proofs,
   identity revocation, anti-Sybil and proposer fairness without stake weights.
2. **Consensus engine**: build native validator state machine and durable
   two-phase vote locks / view changes with formalized evidence and f-threshold.
3. **Execution integration**: replace the consensus voter/election mechanism
   in the actual Privi node source, not just its display name, plus genesis,
   upgrade, RPC and proof verification APIs.
4. **Adversarial simulations**: conflicting votes, Byzantine withholding,
   independent network partitions, replay at different heights/epochs,
   malicious identity claims, simultaneous rotating validator elections and
   disk/restart failure.
5. **Financial integrity**: close direct native balance writes and full supply
   accounting, verify cap exactly 1,000,000,000 PRVI (if retained) through every
   module route, and prove no real reward issuance from IoT data proposals.
6. **Independent testnet**: operator-attested 4+ distinct hosts, reproducible
   binaries, chain ID, signed genesis, separate keys, public finality proofs,
   external security audit and incident recovery.
7. **Controlled production decision**: only after signed review of the
   end-to-end technical, security, operator and financial release evidence;
   never based solely on this proposal or a passing GitHub unit test.

## Test entrypoint

    node --test production-network/mainnet/pop_candidate/test_engine.cjs

This test verifies only the signed *research certificate* mechanics and
negative admission cases. Its results MUST NOT be interpreted as an
operational validator, finalized block or PoP financial mainnet.


## Durable vote-signing guard research (separate follow-up)

The research implementation supplies \`persistent_vote_guard.cjs\`.
Before emitting a **research-only** commit signature from an admitted
Ed25519 validator, it reserves a height lock scoped by
\`(research-chain-id, genesis-hash, height, validator-id)\`. The stored record
also includes the admitted membership epoch, candidate block hash, and
the claimed **previous-block hash**. A research signer now rejects the
same candidate hash at the same height with a different parent link,
including across rounds or process restarts. This improves signed
proposal consistency, but the parent hash is still an unverified
proposal assertion, NOT proof of finalized native chain state.

The on-disk record format is now `PriviPoPResearchHeightLock/v2`.
A preexisting parentless v1 lock is NEVER silently upgraded or overwritten;
replay fails closed and requires audited operator recovery. The lock filename
remains scoped to chain/genesis/validator/height and deliberately does not
include epoch, round, block hash, or parent hash, preventing an alternative
claim from bypassing an earlier height reservation.

**Fail-closed epoch behavior:** A signer cannot forget a same-height
commitment merely because committee membership moved to a new epoch:
even re-signing an *identical* block hash at that height in another epoch
is refused until a separate, formally reviewed handoff protocol exists.
The in-memory research lock now also stores height commitments in a
private class field and freezes its public instance. This prevents callers
from accidentally clearing or replacing a previously exposed public Map or
overwriting the instance's accept method. It is **not** protection against
malicious code with control of the JavaScript process, module prototype,
signing key, host or runtime, and it does not persist across restarts.

The in-memory \`ResearchVoteLock\` now mirrors this conservative
one-chain/genesis rule. A new height may be signed after an epoch
change; that is NOT a safe, finished consensus membership protocol.

The durable guard requires a private local lock directory (0700),
refuses symlinked directory ancestry and existing hard-linked lock files,
creates each record exclusively (O_EXCL), and fsyncs both the file and
directory before any signature leaves the process. An existing lock
is re-validated from an open file descriptor and re-synced on replay,
so a previous directory-sync failure cannot be mistaken for durable
commitment. Existing records must also match the signer's exact canonical
JSON bytes (including the terminating newline). This deliberately rejects
duplicate JSON member names, changed field order, alternate whitespace,
and appended bytes, even when JSON.parse would recover equivalent fields.
Corrupted or conflicting records are never auto-deleted.
Dedicated tests cover ordinary restart/replay, ambiguous records, corrupted locks,
symlink ancestors, hard links, simulated sync failure, and competing
signing processes across epoch boundaries and conflicting parent links.

These controls remain *local research experiments*: they do not prove
that two committees' quorums overlap, that a proposal is valid on a
live native ledger, that network partitions recover safely, or that
PoP voting is integrated with running Privi validators.

**Do not deploy:** This is only a filesystem-level non-equivocation
experiment, not a production slashing/lock protocol. The entire host,
identity-attestation root, and local disk are assumed trusted. File
replication, malicious administrator access, key cloning, timeouts,
liveness, Byzantine view-change, weighted quorum intersections, ledger
inclusion verification and active integration into validator consensus
remain unaddressed.

Test only on disposable paths:

    node --test production-network/mainnet/pop_candidate/test_persistent_vote_guard.cjs

Passing that test is *not* evidence that native Privi mainnet
has implemented Point of Position validator finality.


## Necessary cross-epoch quorum overlap study (not a transition protocol)

The optional `epoch_overlap.cjs` research preflight now compares **two
separately governance-admitted adjacent-epoch committees** on the same
research chain and genesis. It does not sign or execute membership changes.
For each epoch it requires the exact committee object returned by verified
Ed25519 governance admissions, not a caller-forged quorum configuration.
The validator registry now records the fingerprint of the Ed25519 governance
root used to verify those admissions. The preflight rejects adjacent epochs
signed by different governance roots, even when the validator roster is
identical. Governance key rotation needs an independently reviewed and
signed authority handoff; accepting two individually valid registries does
**not** prove their authority was continuous.
For comparison, a shared validator must retain its exact signing identity,
operator identity, failure domain and PoP position evidence; otherwise it
is conservatively counted as changed.

With `N₁`, `N₂` admitted validators, quorums `Q₁`, `Q₂`, and `M`
unchanged signer identities, the smallest guaranteed intersection between
any two quorums is:

    max(0, Q₁ + Q₂ - (N₁ + N₂ - M))

Under an *unverified* candidate assumption of at most
`max(floor((N₁-1)/3), floor((N₂-1)/3))` Byzantine members in the
shared signer set, the preflight **rejects** transitions whose worst-case
quorum overlap is not greater than that bound. For four research
validators with 3-of-4 quorum, an unchanged four-member set has
two guaranteed signers in the intersection; rotating even one member
leaves only one, not a guaranteed honest intersection. For seven
validators with 5-of-7 quorum, one new member similarly reduces
guaranteed overlap from three to two when the assumed fault bound is two.

**This is only a necessary static condition.** Even passing overlap does
NOT establish any finalized joint-consensus handoff proof, validator key
continuity, real Byzantine limit, authentic ledger position attestations,
view-change safety, liveness or actual PoP consensus. The preflight
**always returns `permitsEpochTransition: false`** on accepted research
fixtures. Real native financial mainnet remains **NO-GO**, and neither
the research preflight nor its test suite can authorize a real membership
change. It does not alter validator deployments, native PRVI issuance,
chain IDs, BNB PRIV or permanently valueless TEST.

Offline adversarial tests:

    node --test production-network/mainnet/pop_candidate/test_epoch_overlap.cjs



## Consecutive signed candidate certificate ancestry (offline research)

The opt-in `candidate_ancestry.cjs` preflight checks a **bounded** (1–256)
series of synthetic research proposals and Ed25519 voting certificates
against an explicitly supplied `{height, blockHash}` checkpoint:

1. The committee must be the exact object previously returned by verified
   governance-root-signed validator admissions.
2. Each candidate must have the next consecutive height, its previous-block
   hash must match the preceding signed candidate (or the starting
   checkpoint), and no candidate hash may recur.
3. Every proposal and quorum is independently checked using
   `verifyCertificate`: correct PoP proposer, signed exact height/round/
   previous/current hashes, admitted distinct voting keys and quorum.
4. Any missing, duplicate, reordered, disconnected or unsigned certificate
   refuses the **entire** sequence. It also rejects an invalid/missing
   checkpoint and chain-height overflow.

The response reports `finalized: false`,
`verifiesExecution: false`, `verifiesCheckpointAuthenticity: false` and
`productionConsensus: false`. A **caller-supplied** checkpoint is not
a trustworthy canonical ledger or verified state root. A properly signed
candidate can still represent unavailable, unexecuted or invalid state,
and this preflight does NOT establish a BFT network's global safety,
independent block availability, finalized ancestry, fork choice or
actual PoP node integration. Nor does it implement finalized epoch handoff
or permit financial PRVI mainnet activation.

Offline adversarial regression:

    node --test production-network/mainnet/pop_candidate/test_candidate_ancestry.cjs

**NO-GO:** Only a production chain with externally authenticated
finalized checkpoints, independent validator evidence, audited
consensus execution and recovery can establish genuine mainnet finality.


## Research checkpoint issuer attestation (still NOT finality)

The new opt-in `checkpoint_attestation.cjs` requires a
`PriviPoPResearchGovernanceCheckpoint/v1` **synthetic claim** signed
under the same Ed25519 governance key that authenticated the research
committee's validator admissions. Callers must supply a *separately
trusted/pinned* governance public key: the checkpoint must never be allowed
to select its own verification key. The verifier rejects an unverified
committee, unexpected fields, changed chain/genesis/epoch, changed
checkpoint height/hash, governance key substitution, malformed signatures,
wrong research tag and any attempted production-finality assertion.

The signing domain is `Privi/PoP/Research/2026/v1` with tag
`research-checkpoint-attestation-v1`, distinct from validator
`admit`, `propose` and `commit` signatures. A valid
signature authenticates **which key issued the checkpoint claim**. It
does NOT prove that key had external governance authorization or that
the claimed block hash is canonical, finalized, available, executed or
anchored in actual Privi consensus.

`verifyAttestedCandidateAncestry` performs that signer check first,
then uses `verifyCandidateAncestry` to verify each contiguous
quorum-signed research candidate. Its result explicitly preserves
`checkpointFinalityVerified:false`, `finalized:false`,
`productionConsensus:false` and
`verifiesCheckpointAuthenticity:false` (the canonical ledger state
remains unauthenticated). This is a **pre-production trust-binding
exercise, not a Privi checkpoint service or a signed genesis**.
A real mainnet verifier would need external finalized-state evidence,
independent operator attestations and a reviewed genesis/root-of-trust
ceremony before trusting an on-chain finality claim.

Offline synthetic regression:

    node --test production-network/mainnet/pop_candidate/test_checkpoint_attestation.cjs

No private production keys, financial mainnet activation, PRVI issuance,
production validators, network transports or real checkpoints are involved.


## Conflicting signed quorum certificate evidence (offline research)

The read-only `certificate_conflicts.cjs` audit accepts **two**
individually valid quorum-signed *research* certificates from the exact
same governance-admitted committee at the same height. It verifies
both original signed proposals, all Ed25519 commit votes, quorum
thresholds, and voter identity before attempting to report any conflict.

If the two certificates commit to **different current block hashes OR
different previous-block hashes**, the audit computes their
cryptographically verified signer intersection. For each intersecting
key it emits the two complete signed `commit` field arrays and their
original signatures, allowing an independent reviewer with the
governance-admitted research registry to reproduce verification.
A different round alone, without a different parent/current hash,
**does not** qualify as equivocation in this conservative experiment.
Two 3-of-4 committees' quorums intersect in at least 2 signers within
one committee; two 5-of-7 quorums intersect in at least 3. The
checker refuses a missing quorum, duplicate/unknown signer, forged
signature, unverifiable registry or mismatched height.

This only establishes that the same Ed25519 **keys** signed
contradictory research commitments when such evidence is provided.
It does not establish who physically used a key, malicious intent,
which branch is valid, whether other hidden certificates exist,
whether a canonical state was executed, or Byzantine finality.
It **never authorizes slashing or financial penalties**. Reports
explicitly set `finalityProven:false`,
`slashingAuthorized:false`, `operatorMisconductProven:false`
and `productionConsensus:false`.

Test with synthetic 4- and 7-member research committees:

    node --test production-network/mainnet/pop_candidate/test_certificate_conflicts.cjs

**NO-GO:** Production mainnet still requires a formally reviewed
consensus protocol, genuine validator key custody and external
attestations, authenticated finalized chain state, durable recovery,
and independently validated operator processes.


## Deterministic non-financial state-binding experiment (research only)

The `toy_state_commitment.cjs` module adds a **deliberately isolated
counter-state application** to test the next consensus boundary: a
valid Ed25519 PoP certificate and correct parent hash do not by
themselves prove what an application executed. It uses no financial
transfers, staking, coins, production IoT data, wallets or ABCI state.

For up to 64 supplied candidate blocks, the verifier:

1. Checks the caller-provided starting state against a separately
   expected SHA-256 state digest. This digest is *not* independently
   proven canonical or derived from a production genesis.
2. Checks a synthetic research checkpoint **issuer signature** against
   a separately pinned research governance public key and verifies
   each committee-admitted quorum certificate and contiguous
   parent/block hashes using the existing research modules.
3. Executes canonical, bounded counter-increment operations with
   per-account strict monotonically increasing nonces, integer
   overflow safeguards, deterministic key ordering and account/operation
   limits. It rejects all financial, unrecognized or malformed opcodes.
4. Recomputes each ordered operation digest, resulting state digest,
   and candidate block hash from chain/genesis/epoch, height, parent,
   operations and resulting state. The signed candidate must bind to
   this *same* computed commitment; an inconsistent, replayed or
   forged transition refuses the **whole** sequence.

This is an offline educational execution model for reasoning about
commitment binding—not an implementation of the Cosmos SDK bank keeper,
ABCI block execution, CometBFT voting, Privi validator finality, IoT
accounting, token vesting, staking or PRVI's 1-billion cap.

The result explicitly states
`validatesLiveCosmosEvmState:false`,
`startingStateExternallyAuthenticated:false`,
`checkpointFinalityVerified:false`,
`productionConsensus:false` and `finalized:false`.

Regression suite:

    node --test production-network/mainnet/pop_candidate/test_toy_state_commitment.cjs

**Financial mainnet remains NO-GO.** The next substantive engineering
work is a formally reviewed state commitment and actual independently
verified *Cosmos EVM* execution proof plus the full PoP consensus
protocol. Passing this toy test proves neither.
