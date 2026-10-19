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

### Strict input and credential hygiene

The review utilities parse candidate genesis and release JSON with **duplicate-key rejection**. Repeating keys such as `chain_id`, `supply`, or `max_supply_whole_prvi` is not a harmless formatting choice: many JSON parsers silently pick one version. All duplicate properties now fail closed. Obvious private-key, mnemonic, access-token, and password fields or key material are also rejected without printing credential values to build logs.

The checks are **offline**, cannot validate the identity of an operator or the safety of private signing infrastructure, and cannot approve a launch. Keep production keys and service credentials outside the repository, hosted CI and chat. A public SHA256 fingerprint of a signing key is not a signing credential.

### Auditing the initial balance accounting (read-only)

```bash
python3 production-network/ops/genesis_supply_audit.py \
  --genesis /secure/review/candidate-genesis.json \
  --denom REVIEWED_BASE_DENOM \
  --chain-id REVIEWED_COSMOS_MAINNET_CHAIN_ID
```

This can reject invalid account totals and excess starting supply; it does **not** prove a total lifetime cap, vesting implementation, uniqueness of EVM ID, or deploy a chain. Attach the verifier output and independent chain-state proof to the audit.

### Four owner-operated validator evidence (one legal operator, four independently keyed hosts)

Privi World Corp has chosen **one centrally controlled, permissioned operator** controlling **four separate, uniquely keyed validators**. This is *not* a decentralized four-operator design. Each of the four hosts must have a distinct real failure domain, unique CometBFT public signing-key fingerprint, signed genesis digest, screened sentry/P2P connectivity, secure signer storage, separate host credentials, and proven single-active-signer recovery. Operator/host/failure-domain attestations are external records; names or synthetic labels in a JSON file alone cannot verify hardware separation. With 25% voting power per host, three of the four signatures are needed for >2/3 consensus; loss of two can halt block finalization. No production keys, real genesis signatures, external audit, or operating validators are established yet.

The [mainnet evidence verifier](../ops/verify_mainnet_evidence.py) requires exactly four unique validator identities, signing-key fingerprints, host IDs and fault domains, each under **Privi World Corp**. The [native genesis auditor](../ops/native_prvi_genesis_params.py) additionally rejects using upstream TEST/stake for PRVI gas/staking, nonzero x/mint inflation, invalid 18-decimal metadata and excess initial issuance. These checks only reject bad *declarations*; they cannot sign, mint, attest, deploy or authorize any financial token or chain.

### Freezing and signing candidate genesis

1. Obtain the audited custom-chain binary and run a reproducible build with approved parameters.
2. Create unsigned candidate genesis offline in a controlled workstation; run initial bank audit and independently verify module configuration, vesting and max lifetime issuance rules.
3. Validate chain IDs against reserved registries, wallets and integrations; rerun real end-to-end public testnet and upgrade/fault-recovery checks.
4. The one legal operator's four distinct, protected validator signing identities must each attest the same genesis SHA-256 and approved release digest; independent external review must verify unique keys, separate hosts and exclusive signing control. Never describe them as four independently owned operators.
5. Publish non-sensitive binary/genesis hashes and launch schedule. Store private keys offline or in secure signer/HSM, never in repository.
6. Complete external audit, verified counsel scope, KYB, incident response and named accountable launch GO signatures. Any material file change invalidates previous digest signatures and requires review again.
7. Only after approval, coordinate the genesis time with independent operators; verify production `eth_chainId`, block commit voting power, wallets, RPC and explorer. Never equate a developer localnet success with financial activation.

**Gate:** Mainnet remains **NO-GO** until the complete [MAINNET_LAUNCH_GATE.md](../ops/MAINNET_LAUNCH_GATE.md) evidence package is verifiable.
