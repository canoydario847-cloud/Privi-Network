# Privi native PRVI mainnet design package — NOT LIVE

**No mainnet is deployed. No PRVI has been minted, sold, bridged, assigned a market price or distributed.** This directory is a source configuration and genesis-review toolkit only. It must not be merged as a release or deployed to Railway. The current publicly working **TEST** devnet remains valueless and entirely separate; existing BNB Chain **PRIV** remains untouched.

## Contents

| File | Purpose |
| --- | --- |
| `privi_chain_config.json` | Mainnet design source of truth: PRVI, 18 decimals, fixed 1-billion maximum, provisional staking/slashing and allocation/vesting policy, placeholder unique chain IDs |
| `privi_source_overlay.py` | Fail-closed, local, REVIEW-ONLY source patch generator targeting exact Cosmos EVM `v0.7.3` commit `c3ae9067a7eadcdea55a5192226916deb44c71c4`. Refuses unapproved IDs and a dirty upstream checkout |
| `validate_candidate_genesis.py` | Read-only structural check on a **separately generated** candidate genesis and complete allocations ledger, including native bank cap, staking/fee denom, supply reconciliation and enforced vesting structures |
| `mainnet_preflight.py` | Separate all-gates evidence checklist; requires binary/genesis/allocations checksums, independent operators, audits and release approval |
| `manifest.example.json` | Intentionally incomplete review manifest: MUST fail |
| `test_*.py` | Read-only negative and synthetic candidate tests, never real keys or coins |
| `.github/workflows/privi-mainnet-preflight.yml` | CI unit checks and temporary candidate compile; NEVER deploys |

## Economics — values requiring independent review

Native **PRVI** has **1,000,000,000** units maximum with **18 decimals** (`aprvi` smallest unit), maximum **1,000,000,000,000,000,000,000,000,000 aprvi**. The proposed ledger policy buckets total the full cap: community 40%, ecosystem 20%, rewards reserve 20%, protocol treasury 10%, contributors 10%.

Genesis must be generated **later** from independently verified operator public keys and owner-approved allocations. Contributor, treasury and ecosystem allocations are currently required by the candidate validator to use actual Cosmos `PeriodicVestingAccount` on-chain account types; descriptions or off-chain spreadsheets alone are NOT vesting. The policy proposes a 12-month contributor cliff and 36-month linear vesting, but that is **not yet executable**; exact on-chain periods, recipients, start dates, and governance approvals are pending. Reward reserves must be controlled on chain and paid from existing escrow and fees, rather than newly minted inflation.

Staking proposed for review: `aprvi` bond and EVM gas denom; 21-day unbonding; 100 maximum protocol validator slots; 5% minimum commission; 5% double-sign slashing and 0.01% downtime slashing; governance quorum 33.4%, threshold 50%, veto 33.4%, seven-day voting. These values are **not approved** and must be checked against actual CometBFT/Cosmos SDK module parameter formats, safety and legal requirements. A noninflationary network cannot promise staking yields without an economically viable, finite reward schedule.

## Temporary source patch example (offline only)

The committed JSON has `null` chain IDs, so this example **will refuse** to make a source patch until *both IDs are separately reviewed and selected*.

```bash
python3 production-network/mainnet/privi_source_overlay.py \
  --upstream /path/to/clean/pinned-cosmos-evm-v0.7.3 \
  --config /secure/reviewed-mainnet-design.json \
  --output /tmp/privi-unreviewed.patch
```

CI uses explicitly **non-production** synthetic chain IDs only to make sure the source patch can apply and compile. Compilation is not an audit, production binary release, network creation, genesis ceremony, or deployment permission.

The generated patch **does not mutate** the upstream checkout. It proposes changing the example Bech32 prefix, CLI EVM numeric ID, native EVM fee denomination, fee market, default mint inflation and begin-block mint path, hard-coded upstream ERC20 examples, and an application end-block supply ceiling. Those source changes must be audited along with module mint authorities, runtime ABI and genesis invariants; runtime initialization and chain-ID tests on an isolated staging environment are still required. Do not assume a source patch guarantees the coin supply is immutable.

## Read-only candidate genesis review

After a separate offline genesis ceremony and audited PRVI app implementation:

```bash
python3 production-network/mainnet/validate_candidate_genesis.py \
  --genesis /secure/proposed-privi-genesis.json \
  --allocations /secure/disclosed-prvi-allocations.json \
  --config /secure/reviewed-mainnet-design.json

python3 production-network/mainnet/mainnet_preflight.py \
  --manifest /secure/signed-mainnet-review-manifest.json \
  --genesis /secure/proposed-privi-genesis.json \
  --allocations /secure/disclosed-privi-allocations.json \
  --binary /secure/independently-audited-node-binary
```

The candidate genesis checker verifies actual bank supply, balances, ledger buckets, module denomination settings, inflation defense in depth, vesting type, vesting amounts and periods. The release preflight separately requires **seven independent operators**, protected keys under their own control, audits and signoffs. Passing either tool does not prove Cosmos genesis validity and does not authorize a financially consequential launch.

## CI

```bash
python3 -m unittest discover -s production-network/mainnet -p 'test_*.py' -v
```

The upstream source overlay build job clones the pinned example and compiles a throwaway candidate to validate patch compatibility; it never uploads the binary, installs real keys, generates funded genesis, or starts a chain. CI is not trusted to generate production validator signing keys. External operators must independently verify code and genesis.

## Still blockers before any financial mainnet

1. Decide unique Cosmos and EVM IDs, complete audited Privi native denomination end-to-end, and reserve/register chain metadata.
2. Audit source modifications and cap enforcement including bank supply, x/mint, all module mint permissions, IBC/ERC20 token adapters and governance upgrades.
3. Decide and implement actual vesting and reward-escrow contracts/account controls; publish a ledger of real recipients with independently verified sums and lockups.
4. Finalize genesis with complete operator-consensus public keys; certify at least seven distinct operators with independent keys and infrastructure.
5. Rehearse upgrades, slashing, restores, chain liveness, IBC safety, fee behavior and anti-double-sign fencing using **valueless** test tokens.
6. Complete independent external security audits and appropriate legal review and obtain manual release authorization.

**No deployment, no real PRVI minting, no copying TEST genesis or demo mnemonics, no changes to BNB PRIV, and no changes to the existing Railway network.**


## Four-gate preparation workstream (details from operators may arrive later)

Everything here is **source-only, fail-closed and offline**. It does not mint
PRVI, choose final registered IDs, fund genesis, verify real operator ownership,
run a mainnet signer or initiate a financial launch. The current one-owner
seven-node Railway TEST staging network is not changed by this branch.

1. **IDs and supply policy**: `candidate_network_ids.json` proposes the *unreserved*
   Cosmos/EVM IDs; check snapshots with `network_id_check.py`. IDs remain
   **unapproved** in the production source-of-truth `privi_chain_config.json`
   until collision checks, registry reservations and external signoff.
   `privi_source_overlay.py` produces an unreviewed, non-deployed
   PRVI-denominated Cosmos EVM source patch from the pinned upstream checkout.
   Its fixed-supply protections still require independent module-level audit.
2. **Genesis, 1B cap, staking, vesting**: `allocations.template.json`
   records the exact proposed 40/20/20/10/10 policy buckets but **no real
   recipients**. Run `vesting_plan.py` only after the real, recipient-reviewed
   ledger is supplied. Contributor tokens unlock in 36 monthly installments
   **following** the proposed 12-month cliff; treasury and ecosystem drafts
   use 36 monthly increments. All are review-only Cosmos vesting account
   JSON fragments, **not** a funded or Cosmos-validated genesis. The separate
   `validate_candidate_genesis.py` must validate an actual downstream
   candidate, plus upstream binary integration and code audit.
3. **Seven independent operators**: `operator_roster.template.json` is
   deliberately empty until the owner supplies the operators' **public**
   details and evidence. `independent_operator_roster.py` screens unique
   legal control, signing custody, infrastructure, regions, independent
   attestations and individual voting-power concentration. Every signer
   remains in an operator's exclusive custody. **Do not provide private
   consensus keys, seed phrases, or server credentials.**
4. **Audit, recovery, rehearsal, launch**: `rehearsal_audit.py`
   reads seven separate private Comet RPCs and one EVM RPC and checks the
   seven commit signatures against the voting set. See
   `SECURITY_REVIEW_AND_RECOVERY.md` for source-audit scope,
   H/R/S fencing, backup safety, slashing, governance and incident drills.
   The original `mainnet_preflight.py` requires actual audited
   binary/genesis/ledger hashes, outside signoffs, seven genuine operators,
   resilient services and a **manual** launch authorization. A script passing
   does not replace independent review.

### Offline commands (not a financial deployment)

```bash
python3 -m unittest discover -s production-network/mainnet -p "test_*.py" -v

# Both commands are EXPECTED TO FAIL because details are deliberately absent.
python3 production-network/mainnet/independent_operator_roster.py \
    --roster production-network/mainnet/operator_roster.template.json

python3 production-network/mainnet/mainnet_preflight.py \
    --manifest production-network/mainnet/manifest.example.json

# Once independently reviewed allocations and a FUTURE genesis time exist:
python3 production-network/mainnet/vesting_plan.py \
    --approved-ledger /secure/approved-allocations.json \
    --genesis-time <APPROVED_FUTURE_UNIX_TIMESTAMP> \
    --output /secure/vesting-draft-for-auditor.json

# Mainnet rehearsal only, from authorized non-public RPC access:
python3 production-network/mainnet/rehearsal_audit.py \
    --cosmos-chain-id <REVIEWED_COSMOS_ID> \
    --evm-chain-id <REVIEWED_EVM_ID> \
    --rpc http://validator-0.internal:26657 \
    --rpc http://validator-1.internal:26657 \
    --rpc http://validator-2.internal:26657 \
    --rpc http://validator-3.internal:26657 \
    --rpc http://validator-4.internal:26657 \
    --rpc http://validator-5.internal:26657 \
    --rpc http://validator-6.internal:26657 \
    --evm-rpc http://reviewed-evm-gateway.internal:8545
```

**Guardrails:** all operators' real details can be added later. Their absence
does not block writing and testing code, but it blocks final genesis and
release approval. Never merge these files onto a branch that Railway
auto-deploys. Neither existing TEST nor BNB PRIV is PRVI mainnet.

