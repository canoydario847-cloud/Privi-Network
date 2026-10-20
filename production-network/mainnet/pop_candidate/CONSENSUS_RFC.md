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
* Admission is signed by an explicit PoP research Ed25519 governance
  authorization key after a separate, manual identity/fault-domain review.
  The proposed founder EVM control wallet is pinned as
  `0x1990589FD200E043b8C6FD9ec5956c61b3071048` in signed candidate
  admission messages, **but the Ed25519 key is NOT cryptographically
  proven to belong to that wallet**. Before this can become live governance,
  signature verification must be bound to the founder's actual EVM wallet
  and verified genesis/validator state. This is permissioned *research*,
  neither PoS nor PoSA, and has no permissionless Sybil resistance.
* **One legal operator** `PRIVI_WORLD_CORP` controls four distinct signer
  public keys, distinct declared validator host/failure domains, and unique
  candidate `PoP:PRIVI_WORLD_CORP:VALIDATOR/AUTH:SEQUENCE` positions.
  All four validators belong to that single operator. They are NOT four
  independently controlled organizations, and a single company or signing
  administrator compromise can undermine every validator. Each distinct
  validator still has exactly **one vote**; IoT transaction frequency, PRVI
  balances and PoP multipliers do **not** confer voting power. No independent
  real-host proof or verified PoP ledger inclusion exists in this prototype.
* All admission and vote signatures are domain-separated by candidate protocol
  version, exact research chain ID, genesis hash and membership epoch. Admission
  also commits to the *sole proposed founder EVM wallet*, operator identity,
  host claim and position. Proposal votes bind height, round, previous block
  hash, block hash and designated proposer. Founder-wallet declaration is not
  evidence of actual EVM private-key authorization.
* The deterministic research proposer is the indexed validator selected by
  SHA-256(chain ID, genesis, epoch, height, round) modulo validator count,
  after validators are sorted by public identity. This is not a proof of leader
  unpredictability or censorship resistance.
* A prototype commit certificate for N candidate validators requires
  \`floor(2*N/3) + 1\` **distinct valid Ed25519 signatures** to the same
  proposal. N must be between 4 and 31 in tests. An in-memory model rejects
  equivocation at the same height (including across rounds), but it is NOT a
  crash-safe signing service.

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
2. The current owner-operated architecture intentionally **does not require
   distinct legal operators**: Privi World Corp is the one proposed operator
   for four or more uniquely keyed research validators. Public key and
   declared fault-domain uniqueness do not attest independent hosts or
   compromise resistance. Governance and infrastructure remain centralized.
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

The next research experiment supplies \`persistent_vote_guard.cjs\`.
Before emitting a **research-only** commit signature from an admitted
Ed25519 validator, it writes a height lock for
\`(research-chain-id, genesis-hash, epoch, height, validator-id)\`
and the accepted block hash. It uses a private local directory (0700),
an exclusive create (O_EXCL), fsync on the file and directory, and
refuses to overwrite corrupted or conflicting lock records.

This is materially stricter than the earlier volatile \`ResearchVoteLock\`:
a restarted signing process rejects attempts to sign a *different* block
at the same height, even if the round changes. Signatures are domain
separated and require a governance-admitted signer and an authenticated
candidate proposal. The implementation never handles financial wallet keys,
PRVI emissions, PoS voting power or third-party settlement.

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


## Founder wallet cryptographic authorization experiment (EIP-191)

The next research layer is
\`founder_wallet_authorization.cjs\`. It closes a specific admission
**declaration** gap: merely storing Dario Canoy's proposed EVM address in
the admission messages does **not** prove that the EVM wallet owner has
authorized the validator committee.

It creates a deterministic \`personal_sign\` (EIP-191) challenge that
commits to all of these proposed research values:

- the **exact** founder EVM wallet
  \`0x1990589FD200E043b8C6FD9ec5956c61b3071048\`;
- the single legal operator \`PRIVI_WORLD_CORP\`;
- the named \`privi-pop-research-*\` chain, genesis hash and epoch;
- the current governance-admission Ed25519 **public** key;
- each uniquely admitted validator's signing-key hash, host assertion,
  company PoP stamp, position commitment and alleged native anchor;
- a caller-generated nonzero random 32-byte nonce and an expiration
  no more than seven days from verification.

\`verifyFounderResearchAuthorization\` uses independently implemented
ethers v6 EIP-191 signature recovery and accepts **only** that exact
founder address. It rejects missing, forged, malformed, stale and
different-wallet signatures. The existing baseline PoP certificate parser
does **not** authorize owner governance by itself; only the EIP-191
gate can produce a \`ownerCryptographicallyVerified\` *research result*.

**No real founder EIP-191 signature has been provided or requested.**
The CI tests generate an entirely unrelated, ephemeral test EVM wallet,
show that valid signatures are actually recoverable for that test key,
and prove that the **real founder-only** check refuses every such
test signature. They never create, recover, simulate or claim to have
the founder's private key.

Even a valid EIP-191 approval would bind only *one research committee
configuration*, not a deployed financial mainnet, a wallet's legal owner,
or identity verification of real physical validator hosts. Operational
anti-replay storage, revocation, EIP-1271 smart-account support,
committee rotation safety, EVM-authorized governance changes,
independent host attestations, objective PoP ledger inclusion proofs,
distributed Byzantine finality and actually patched node consensus
remain unimplemented. The time check assumes a trusted local clock;
production approval would need consensus-based validity and revocation.

To run the isolated proof tests without any founder credentials,
install pinned ethers v6 into a disposable local directory and set
\`PRIVI_POP_ETHERS_PATH\` to its module directory:

    node --test production-network/mainnet/pop_candidate/test_founder_wallet_authorization.cjs

This experiment never sends a token, signs a real founder authorization,
starts validators, or changes the real Cosmos EVM node.


## Disposable on-chain validator-position anchor verifier

The development-only module \`onchain_anchor_verifier.cjs\` can now consume
a **real transaction receipt** for each governance-attested research
validator. It verifies all of the following before considering a
\`PoP:PRIVI_WORLD_CORP:VALIDATOR/AUTH:SEQUENCE\` position anchored:

- Four separate, signed Ed25519 validator admissions under the one
  \`PRIVI_WORLD_CORP\` operator and founder EVM address *declaration*
  (not a real founder-wallet signature).
- Live RPC chain identity, genesis block hash and the bytecode SHA-256
  of the exact configured \`PriviIoTLedger\` Solidity contract, using
  the existing **loopback-only, developer-only** EVM ID 262144 gate.
- A successful mined transaction, its canonical block hash and height,
  current-head confirmation depth, actual matching \`IoTRecorded\` event
  decoded from the pinned contract, correct validator PoP stamp hash,
  \`VALIDATOR/AUTH\` zone, validator-position event type and position
  sequence.
- On-chain device enrollment containing the governance-admitted
  validator's Ed25519 SPKI public-key hash and Privi World Corp company
  identifier. One receipt may not be reused for multiple validators.
- Failure on fictitious hashes, reorg/canonical-block inconsistencies,
  absent transaction, insufficient confirmations, alternative genesis,
  changed contract bytecode, duplicate receipts and forged event fields.

CI exercises one **actual disposable four-validator Cosmos EVM network**
and records four separate validator-position events, then checks receipt
inclusion and several denial cases. The mock unit tests separately
probe tampered receipts and RPC values. Admission Ed25519 root
signatures remain test-only and are NOT real founder EVM signatures.

This is a substantial improvement over **trusting a bare claimed
\`anchorBlockHash\` string**. But the source ledger is still the
stake-based **upstream Cosmos EVM developer chain**, not actual native
Privi PoP consensus. The verifier relies on its configured RPC and
does not independently validate Merkle receipt proofs, validator
commits, live host identity, or finalized native PoP application state.
The developer gateway controls the validator-zone test events; such
an event alone **does not appoint a live validator**. Candidate votes
are not bound into actual CometBFT/ABCI messages. This does not activate
a mainnet, create coins or prove the 1B PRVI lifetime cap.

**NO-GO:** Native PoP BFT safety, objective production position-inclusion
proofs, founder EIP-191 signature, independent signer isolation, secure
validator update logic, complete native bank mutation authorization,
external audit, signed genesis and public operational evidence remain
unimplemented.
