# PRVI Financial Mainnet — Candidate Genesis Inputs and Review Protocol

**Status:** Required inputs not yet supplied; financial mainnet is NOT activated. This document is NOT a genesis file, a signed artifact, token issuance authorization or an exchange listing.

## Immutable proposal parameters — subject to technical/legal confirmation

- Proposed native asset symbol: **PRVI**, separate from existing BNB Chain PRIV and permanently valueless TEST.
- Proposed *hard maximum* lifetime issuance: **1,000,000,000 whole PRVI**.
- Proposed native base precision: **18 decimals**; if approved, max lifetime base units = **1,000,000,000,000,000,000,000,000,000** (10^27). A maximum is *not* a claim about issued or circulating supply.
- Cosmos chain ID: **TBD**, unique and distinct from `local-4221`.
- Numeric EIP-155 chain ID: **TBD**, unique and distinct from the upstream dev-demo EVM ID `262144` and other public networks.
- Native staking and fee denom: **TBD** pending chain review; `aprvi` is an *illustrative* possible denomination used in unit fixtures, not an approved network setting.
- Chain binary/version, locked release digest, genesis time, genesis digest: **TBD**.
- Governance, slash, staking, inflation/mint module permissions, fee model, upgrade plan: **TBD**.

### Initial genesis allocation worksheet — must be filled and approved

| Allocation bucket | PRVI whole units | Account addresses/public keys | Vesting/unlock terms | Control/approval |
| --- | ---: | --- | --- | --- |
| Founder / team | TBD | TBD | TBD | TBD |
| Foundation / treasury | TBD | TBD | TBD | TBD |
| Community/ecosystem | TBD | TBD | TBD | TBD |
| Validators/staking bootstrap | TBD | TBD | TBD | TBD |
| Reserves/other | TBD | TBD | TBD | TBD |
| **TOTAL INITIALLY ALLOCATED** | **TBD** | | | |

Every allocated account must provide a **public** receiving address only. Do not share wallet recovery phrases or private keys with GitHub or ChatGPT. Initial supply must reconcile to the Cosmos bank module `balances` and `supply` fields.

For a fixed-cap native coin, the launch committee must independently prove that **initial allocation + all possible future issuance is never greater than 1 billion PRVI**, including the effect of staking rewards, inflation parameters, governance, module mint permissions, chain upgrades and vesting. Merely placing `1000000000` in a JSON manifest does NOT enforce a chain-level limit.

### Auditing the initial balance accounting (read-only)

```bash
python3 production-network/ops/genesis_supply_audit.py \
  --genesis /secure/review/candidate-genesis.json \
  --denom REVIEWED_BASE_DENOM \
  --chain-id REVIEWED_COSMOS_MAINNET_CHAIN_ID
```

This can reject invalid account totals and excess starting supply; it does **not** prove a total lifetime cap, vesting implementation, uniqueness of EVM ID, or deploy a chain. Attach the verifier output and independent chain-state proof to the audit.

The offline audit now also requires an explicit Cosmos SDK bank `denom_metadata` entry for the reviewed native base denomination, with display `prvi`, symbol `PRVI`, one base unit at exponent 0 and one PRVI display unit at exponent 18. Missing, duplicated or inconsistent metadata is rejected rather than assuming that a wallet-visible PRVI equals 10^18 base units. This is a **candidate-genesis review policy**, not proof that the active application honors the metadata or implements immutable supply controls. The native base-denom choice remains subject to approval; no existing TEST, BNB or Base asset is relabeled.

### Independent validator evidence (minimum four operator-controlled deployments)

For each operator: independently verified organization identity, different operating control / fault domain, signed public consensus-key and node metadata, sentry design, secure remote-signing arrangement if applicable, signed genesis digest, backup-and-restore rehearsal and double-signing prevention. Do not create four nominally different validators under the same private-key or infrastructure control and claim independence.

### Freezing and signing candidate genesis

1. Obtain the audited custom-chain binary and run a reproducible build with approved parameters.
2. Create unsigned candidate genesis offline in a controlled workstation; run initial bank audit and independently verify module configuration, vesting and max lifetime issuance rules.
3. Validate chain IDs against reserved registries, wallets and integrations; rerun real end-to-end public testnet and upgrade/fault-recovery checks.
4. Each validator operator independently checks every genesis field and signs the exact published SHA-256 digest with their own attested identity/signing process.
5. Publish non-sensitive binary/genesis hashes and launch schedule. Store private keys offline or in secure signer/HSM, never in repository.
6. Complete external audit, verified counsel scope, KYB, incident response and named accountable launch GO signatures. Any material file change invalidates previous digest signatures and requires review again.
7. Only after approval, coordinate the genesis time with independent operators; verify production `eth_chainId`, block commit voting power, wallets, RPC and explorer. Never equate a developer localnet success with financial activation.

**Gate:** Mainnet remains **NO-GO** until the complete [MAINNET_LAUNCH_GATE.md](../ops/MAINNET_LAUNCH_GATE.md) evidence package is verifiable.
