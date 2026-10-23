# Privi PRVI Mainnet Launch Readiness Gate

Status: **BLOCKED — NOT LIVE** (review initiated 2026-10-17).

This is an evidence checklist, not a launch authorization. The local Cosmos EVM `local-4221` four-validator demo is **not** the PRVI financial mainnet. TEST is permanently valueless; BNB PRIV is separate. No migration or financial transaction is authorized here.

## Owner-authorized architecture change — 2026-10-18

The owner has explicitly selected **four Privi World Corp-operated validator nodes**, not four independently owned operators. Privi's proposed financial network would therefore be **centrally operated and permissioned**, with exactly **one** operator and **four separate signing identities / fault-separated hosts**. This intentionally replaces the former independent-operator gate; it does NOT reduce the need for four distinct secured hosts, safe consensus key handling, multi-host tests, security review, signed exact release/genesis or proof of legal and operational readiness.

[Owner validator security architecture](OWNER_OPERATED_VALIDATORS.md) · [Non-live candidate inventory](owner-operated-validators.candidate.json) · [Preflight tool](owner_validator_preflight.py) · [Preliminary internal audit findings](INTERNAL_SECURITY_REVIEW_2026-10-18.md).

The inventory is currently all placeholders, and no actual production hosts or keys have been provisioned. **0/4 production validators verified, but not 0/4 independent operator companies (only one company is intended).** No claim of decentralization, asset issuance or live network is justified.

## Only founder wallet is authorized in proposed Privi network governance

The sole **proposed** EVM owner/governance/treasury-controller public wallet is
`0x1990589FD200E043b8C6FD9ec5956c61b3071048` (Dario Canoy,
Privi World Corp). No other governance admin, guardian, multisig co-owner, or
delegate is approved in the owner's current requirements. The nonfinancial
candidate and fail-closed validator live in
[`privi_owner_wallet.candidate.json`](privi_owner_wallet.candidate.json)
and [`verify_privi_single_owner.py`](verify_privi_single_owner.py).

The wallet only sets the **requested future controller identity**. It cannot
substitute for real validator private signing identities, native PoP BFT
consensus, a signed genesis, audited 1-billion-PRVI lifetime cap, independent
host verification or release attestation. Four validators under one
company still share a single legal administrator. Existing Railway TEST or
single-server clones do NOT become this mainnet. No private key, signed
financial transfer, PRVI issuance or deployment is performed by this policy.

## Existing Railway deployment — observed TEST-only, NOT native PRVI

On 2026-10-19, provider **read-only** observations verified that the Railway
project `Privi Seven Validator Staging` has **seven named validator services
and one bootstrap service**, all online with last deployment `SUCCESS`,
distinct attached persistent volumes, and **all in region `iad`**.
The provider source points to branch
`build/privi-seven-validators-20261016`, which is an **upstream
disposable TEST** setup, not the reviewed custom PRVI binary.
Bootstrap logs identify disposable upstream TEST validator identities. The source README explicitly states the bootstrap coordinator retains copies of **all seven TEST private validator signing keys** in its own persistent volume; this centralized custody is unacceptable for financial PRVI production, regardless of service count.
Runtime logs show P2P peer activity but also intermittent `pong timeout`
errors; provider success and "online" do not verify current synchronized
validator voting power, shared signed genesis, or fault-domain separation.
A separate Railway `Privi EVM Devnet` service has logged actual finalized
and committed blocks, also on its separate upstream development chain.

Read [sanitized provider snapshot](railway_staging_observation.json) and
[offline TEST-only preflight](railway_staging_preflight.py). These deliberately
**never convert Railway staging into production host attestations**.
The seven Railway services may be useful valueless test capacity, but
they are in one region and they do not count toward **0/4 verified native
financial validators**. Confirm genuine cross-host CometBFT identity and
block hashes independently before considering them even a validated
multi-service TEST network.

## Owner-selected Render hosting provider — 2026-10-20

The owner has selected **Render** for the proposed four production validator
services, **conditionally on validation of its infrastructure security**.
See [Render production validator preflight](RENDER_VALIDATOR_PREFLIGHT.md).

Render private services support same-region P2P communications and paid persistent
disks; however, a disk-backed service lacks zero-downtime deploys and private
networking does not automatically cross Render regions. Four containers in one
region share a provider failure domain. The launch gate **still requires four
unique signers, distinct host identities, fault-isolation evidence, safe
remote signing, resilient peer connectivity and documented recovery**.
No Render production validator is currently verified or deployed (0/4).
If Render cannot meet the fault-isolation/signing/network requirements,
production stays blocked until the owner approves a compliant architecture.

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


## Native bank guard progress — still no financial activation

A dedicated experimental module-facing `bankkeeper.Keeper` wrapper now
rejects direct `UncheckedSetBalance` writes for `aprvi`, and rejects
two value-copy builder functions on the restricted module dependency.
SDK-backed tests verify denial before mutation and after persistent
store reopen; the module wrapper's sole embedded interface field is
private and is not a concrete exported raw keeper. However this cannot
eliminate pre-existing raw copies, low-level collection or KV writes,
unreviewed third-party module code, or transient within-block mutations.
The raw SDK keeper vulnerability is still reproducible by a regression
test, so **S-01 and S-02 remain OPEN** and no code here launches a network.

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
  **A real pinned Cosmos SDK + committed LevelDB regression fixture now
  demonstrates this blind spot:** writing 99 native units back to one
  account and 1 to another via unchecked setters leaves total supply at
  100 and `Keeper.Reconcile` passes, including after database reopen.
  Thus the existing conservation check is NOT an account authorization
  or transaction provenance check. Financial activation must remain
  blocked until all native balance writes are restricted to reviewed
  authorization paths, with invariant/transaction-level tests proving
  this independently. Neither record of consensus totals nor a
  third-party legal approval substitutes for this engineering control.
  A separate corruption fixture writes an invalid immutable cap record
  into the actual SDK consensus store and verifies native mint and
  reconciliation fail closed after LevelDB reopen.
- Walking *all* account balances twice per block is O(number of account
  balance records), not just the number of accounts holding `aprvi`. An
  explicitly synthetic benchmark now runs at 10, 1,000, and 100,000 records
  with a mocked `BankView` and records allocations/cost in GitHub CI. It
  does **not** benchmark real Cosmos SDK IAVL disk reads, adversarial token
  diversity, compaction, multi-host block scheduling, or consensus latency.
  A second, more representative benchmark now calls the *actual Cosmos
  SDK v0.54.3 bank keeper and IAVL-backed in-memory multistore*, with 100,
  1,000 and 5,000 disposable unrelated-token accounts and unchanged native
  PRVI. Its costs are collected in the SDK CI job, but they exclude real
  disk I/O, CometBFT networking, EVM traffic and historical IAVL versions.
  A third benchmark now commits 100/1,000/5,000 disposable
  unrelated-token account balances to independent GoLevelDB-backed bank and
  cap IAVL stores, reopens a fresh SDK multistore, then times actual capped
  native supply reconciliation. CI rejects missing or zero-time readings
  for both SDK timing profiles. This narrows the evidence gap but does not
  establish real disk endurance, cold-cache worst cases, realistic account
  growth, fees, gas load, geographic P2P propagation, or block finality.
  The engineering prototype remains a scalability **BLOCKER** until a
  bounded production design and representative adversarial multi-host
  performance plus disk stress evidence exist.
- SDK, ERC-20, VM, IBC, governance and upgrade-related bypasses need
  complete dependency audit and negative integration tests.
- The pinned reference Cosmos EVM enables **permissionless ERC-20 token registration** by default. The Privi custom-app prototype now rejects that default and any native `aprvi` token pair in genesis, and additionally checks **live ERC-20 module state at BeginBlock and EndBlock**, refusing permissionless registration, a native-denom lookup entry, or a stored native-token pair. This detects unsafe end-state changes but **does not atomically prevent transient create/remove paths inside one block**, direct unrestricted keeper writes, unauthorized binary upgrades, or other unreviewed conversion routes. The token-pair scan is O(number of pairs) per block and needs scale benchmarks and independent security review. It is not a production-approved hard guarantee.
- A financial production release and signed actual four-host genesis do not
  exist. Current CI artifacts are isolated, disposable and **not for deployment**.

[Hard-cap integration requirements](PRVI_HARDCAP_INTEGRATION_REQUIREMENTS.md)
and [preliminary security findings](INTERNAL_SECURITY_REVIEW_2026-10-18.md)
document these gaps. **Gate 2 remains BLOCKED** until independently
verified whole-system issuance control, module upgrades and signed
genesis/release acceptance are complete.

## Separate live-chain identity observation (not a launch verdict)

The [read-only node identity verifier](verify_node_identity.py) compares locally
captured CometBFT `/status` (Cosmos chain ID, observed finalized height/hash and
non-catching-up state) to a separately captured Ethereum `eth_chainId` response.
It refuses swapped or missing identities, and its synthetic regression tests
fail closed on malformed JSON-RPC replies, wrong heights and invalid IDs.

**Important:** Cosmos EVM's numeric Ethereum chain ID is selected through
application options, and the upstream developer binary may default to
`262144`. A correct Cosmos `chain_id` and native `aprvi` in genesis **do
not prove** an independently selected Ethereum chain ID actually runs on a
node. Even if the offline identity checker passes, the captured RPC output
may be unauthenticated or forged. The operator must separately verify binary
and signed genesis digests on each physical validator host before any GO vote.
See [staging observation runbook](../mainnet/CHAIN_IDENTITY_OBSERVATION.md).

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
