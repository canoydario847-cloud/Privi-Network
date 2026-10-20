# Privi PoP Native Mainnet Release Gate

**Status: NO-GO. This is mainnet engineering work, not an activation.**

Privi's target is **Point of Position (PoP)**, from the 2026 white paper
*Point of Position: A New Framework for True Asset Valuation* by Dario Canoy.
PoP here means verified position on a ledger: a company identifier,
functional zone and sequence number bound to a cryptographic record.
It **does not mean Proof of Stake (PoS) or Proof of Staked Authority (PoSA)**.
In the white paper, "PoS" is also used as shorthand for Point of Sale,
a **valuation** comparator, not a consensus implementation.

The current pinned Cosmos EVM / CometBFT application **has NOT been
replaced by PoP consensus**. Any project screen, deployment, validator
manifest or token launch representing the current Cosmos EVM voter system
as PoP finality would be inaccurate. PoP data-layer work in this branch
cannot silently elect validators or change BFT finality.

## Implemented (preproduction, not released)
- Native-only IoT event ledger commitments: PoP company / zone / sequence
  and event hashes; device signatures validated by an authorized gateway.
- Mandatory Privi-registered developer gateway; revocation and device
  enrollment; external bridging and token pairing disabled.
- Local classifier suggests an AI label without uploading raw readings
  to a third-party model.
- Transparent Point of Position frequency-duration valuation from the
  research paper: F = min(1,R/50), T = min(1,D/365),
  L = 1 + (0.6F + 0.4T)*1.5.
- All values in "proposed_micro_prvi" are **not minted, redeemable,
  transferable, exchangeable or guaranteed**; no reward entitlement.
- Position stamps of the form PoP:COMPANY:ZONE:SEQUENCE are signed
  before the gateway creates a blockchain transaction.
- EVM ID 262144 and Cosmos ID local-4221 refer only to the disposable
  upstream developer reference network. Neither is a production PoP ID.

## PoP-only production consensus: design and safety work remaining

The white paper defines valuation and position stamps, but it does **not**
fully specify an implementable Byzantine fault tolerant consensus engine.
Before a network may be called "PoP consensus mainnet", implement,
review and independently test:

1. **PoP eligibility:** distinct validator identity and verifiable
   cryptographic position proofs, anti-Sybil controls, challenge expiry
   and replay-resistant epochs. Decide whether positions confer
   voting weight; if they do, prevent fabricated mass IoT events from
   cheaply accumulating consensus power.
2. **Validator election:** consensus-native algorithm for validator
   rotation, proposer selection and quorum, not stake-weighted elections
   and not PoSA/PoS under a renamed label.
3. **Finality:** formal safety and liveness model (fault assumptions,
   deterministic state transition, conflicting positions, leader failure,
   equivocation, network partitions, and canonical block ordering).
4. **Consensus implementation:** reproducible source changes to
   validator update paths, state machine and application security,
   test vectors, multi-host adversarial simulations, upgrade safety,
   key recovery and independent source review.
5. **Monetary integrity:** globally enforce the 1,000,000,000 PRVI
   native maximum including SDK balances, bank writes, EVM/IBC,
   governance and upgrade routes. Existing PR #21 is **experimental**:
   its idempotent APRVI guard does not cover raw bank collection writes.
6. **Operational launch:** independently operated real validators,
   signed genesis and binary, external code audit, firewall/sentry,
   backups, double-sign prevention, endpoint hardening, dashboard,
   public explorer and independent chain-attested finality evidence.
7. **Legal and economic review:** PoP reward, issuance and data-value
   claims need independent legal and economics approval. Sensor
   authenticity and frequency quotas need anti-gaming design.

## Architecture boundary

    [approved sensor with Ed25519]
        -> [Privi registered-developer gateway]
        -> [verified Privi network / PoP IoT contract]
        -> [PoP receipt hashes + position stamps]
        -> [local AI classification and proposed PRVI accounting]

This architecture does **not** convert CometBFT staking consensus into
PoP finality. Until a real PoP consensus implementation is available,
the release guard intentionally returns NO-GO on every production request.

## Exclusive official access (not a monopoly on the idea)

Only developers registered by the Privi contract administrator can call
official `PriviIoTLedger` event functions; a developer cannot replace
that with Base/BNB bridging or a token pair. This is enforced by
contract code and fail-closed gateway validation.

The supplied paper identifies a Creative Commons **CC BY 4.0** license.
Such a license permits unrelated parties to reuse the published ideas
with attribution under its terms; Privi's technical gateway cannot force
all independently developed IoT or PoP software in the world to use Privi.
To claim exclusive licensed rights beyond the published material, obtain
specific professional intellectual-property advice.

No financial mainnet deployment, issuance or public sale is authorized by
this engineering PR.
