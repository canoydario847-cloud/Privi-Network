# Privi MAINNET — pre-purchase implementation and payment handoff

**PROJECT STATUS: BUILD/PREPARATION ONLY, NO FINANCIAL MAINNET LAUNCHED.**

## Work completed in this repository

- [x] Define proposed native `PRVI` max **1 billion**, `aprvi` base unit, 18 decimals, five allocation-policy buckets.
- [x] Review-only source overlay for Cosmos EVM `v0.7.3` pinned commit, native denom, Privi address prefix, no default inflation and supply ceiling (external audit still required).
- [x] Strict read-only cap, genesis-module and vesting validation with deliberately incomplete default inputs.
- [x] Offline candidate-genesis assembler that requires a clean unfunded Cosmos EVM module template, approved public Bech32 addresses and full on-chain vesting schedule. **Creates only an unsigned offline candidate**, never initial blockchain state.
- [x] Unit tests for invalid TEST genesis, wrong network IDs, bad checksums, duplicate addresses, inflation, unbalanced supply and missing vesting.
- [x] Reproducible Go candidate build tested in CI on disposable synthetic non-mainnet chain IDs; audited mainnet container Dockerfile prepared but **deliberately unbuildable without a reviewed patch**.
- [x] Operator/sentry Compose topology with no signing-node RPC exposure, disabled launch profiles, read-only preflight and private state ignored by Git.
- [x] Signed-genesis ceremony verifier requiring seven distinct Ed25519 public attestations, consensus public keys, provider diversity, audit evidence and manifest hashes.
- [x] Read-only mainnet Ethereum and Cosmos RPC monitoring for chain identity, liveness, >2/3 real block signing power, validator distribution and freshness.
- [x] Operator handoff README and editable written hosting quote request: `operator-kit/VALIDATOR_RFQ.md`.

## Still requires explicit external decisions and cannot be faked or inferred

| Requirement | Who must complete | Status |
| --- | --- | --- |
| Final mainnet Cosmos/EVM chain IDs and denomination metadata collision review | Project owner + chain ID ecosystem review | NOT APPROVED |
| Actual legal allocation recipients with reviewed PUBLIC `privi1...` account addresses and beneficial owner vetting | Project owner + counsel + independent reviewer | NOT PROVIDED |
| Actual vesting periods, lockups, reward escrow/fee routing and governance policy | Project owner + qualified reviewers | PROPOSED ONLY |
| Fully customized Privi Cosmos EVM runtime test/release, auditing all mint authorities and genesis import rules | Independent security engineers and auditors | NOT APPROVED |
| Audited canonical genesis and binary digests; finalized and checked gentxs/validator public consensus keys | Seven independently controlled operators + coordinator | NOT PRODUCED |
| Independent validator custody, separate providers, signed genesis and production on-call arrangements | Seven real operator companies/entities | NOT CONTRACTED |
| Legal/regulatory review of any transfer, public sale or liquidity activity | Specialist counsel | NOT COMPLETED |
| Production image registry, secured public RPC/explorer, monitoring service and launch SLA | Paid infrastructure operators + project owner | NOT PROVISIONED |
| Final production launch authorization | Owner + independent auditors and operators | NOT GRANTED |

## Handoff sequence to the first paid operator

1. **Technical proposal review:** Send `operator-kit/VALIDATOR_RFQ.md` and operator topology README to candidate Cosmos operators. Request written, all-inclusive fixed setup and monthly quotes; this does **not** authorize activation or token trades.
2. **Agree operator independence:** Gather independent legal entities and key custodians, with provider/region choices and specific infrastructure SLOs. Seven slots must have seven *genuinely independent* signing administrators.
3. **Freeze audited binary and IDs:** Obtain technical code review, supply invariants, reviewed unique Cosmos and EVM IDs, immutable image digests and independent testing of staking, vesting, upgrade and receipt behavior.
4. **Freeze allocations and produce candidate genesis:** Project owner supplies real *public* account addresses and public vesting plan; run `assemble_candidate_genesis.py` against uninitialized audited module genesis template. Validate with `validate_candidate_genesis.py`. Do not use the publicly funded TEST wallet/address automatically.
5. **Final genesis ceremony:** Collect operators' independently generated public consensus keys/gentxs and separate signed attestation public keys. Freeze final genesis; verify with `ceremony_verify.py`. At least seven actual independent operators sign the **same** genesis and binary hashes. Never exchange private keys or reveal seeds.
6. **Payment point:** Review vendors' quotes, terms and invoices. The user—not CI—authorizes payments and chooses providers. No purchases have been made by this work.
7. **Activation is a separate final release:** Only after all release gates, audits, genesis approval, operator agreements, monitoring and incident response exercises pass. No code currently starts or deploys a financial mainnet.

### Example commands (all offline, cannot run with current missing inputs)

```bash
python3 production-network/mainnet/assemble_candidate_genesis.py \
  --empty-upstream-template /reviewed/empty-template.json \
  --approved-public-ledger /reviewed/allocations.json \
  --config /reviewed/privi-config.json \
  --genesis-unix 1893456000 \
  --output /reviewed/UNSIGNED-CANDIDATE-genesis.json

python3 production-network/mainnet/validate_candidate_genesis.py \
  --genesis /reviewed/UNSIGNED-CANDIDATE-genesis.json \
  --allocations /reviewed/allocations.json \
  --config /reviewed/privi-config.json
```

The sample command's future timestamp is only an illustration, not a planned genesis launch date. **The committed configuration uses intentionally null chain IDs; tools must fail until these are decided and reviewed.**

## Economics and status warning

The proposed PRVI native coin and 1-billion cap are specifications, **not** live circulating assets or a contractual value. The public TEST devnet is permanently valueless and remains separate. Existing BNB Chain PRIV is not swapped, bridged, deposited or altered. Mainnet security and tokenomics must be independently tested and audited; static checks and compilation alone are not proof that new coins are safe.
