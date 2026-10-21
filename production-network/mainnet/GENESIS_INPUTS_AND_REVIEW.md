# PRVI Financial Mainnet — Candidate Genesis Inputs and Review Protocol

**Status:** Required inputs not yet supplied; financial mainnet is NOT activated. This document is NOT a genesis file, a signed artifact, token issuance authorization or an exchange listing.

## Immutable proposal parameters — subject to technical/legal confirmation

- Proposed native asset symbol: **PRVI**, separate from existing BNB Chain PRIV and permanently valueless TEST.
- Proposed *hard maximum* lifetime issuance: **1,000,000,000 whole PRVI**.
- Proposed native base precision: **18 decimals**; if approved, max lifetime base units = **1,000,000,000,000,000,000,000,000,000** (10^27). A maximum is *not* a claim about issued or circulating supply.
- Cosmos chain ID: **TBD**, unique and distinct from `local-4221`.
- Numeric EIP-155 chain ID: **TBD**, unique and distinct from the upstream dev-demo EVM ID `262144` and other public networks.
- Native staking and fee base denomination: the **current custom-app candidate requires `aprvi`**, displayed as `PRVI` at 18 decimals. This remains proposed and is not proof that a financial genesis or network is approved.
- Chain binary/version, locked release digest, genesis time, genesis digest: **TBD**.
- Governance, slash, staking, inflation/mint module permissions, fee model, upgrade plan: **TBD**.

### EIP-155 chain identity startup enforcement

The custom Cosmos EVM binary now rejects unset or known development/public
Ethereum chain IDs **before constructing its encoding configuration and
module keepers**. The rejected values are `0`, `1`, `56`, `97`,
`1337`, `31337`, `4221` and upstream demo `262144`. This is
enforced by [the Cosmos SDK-compatible identity guard](prvicap/chain_identity.go)
and injected by [the exact-source app patcher](custom-app/apply_prvi_cap.py).

The acceptance of a different positive uint64 ID by the guard **does not**
mean that ID is globally unassigned or production-approved. Independently
review the actual chosen EIP-155 identity for collision risk, record the
owner-approved chain ID in signed release configuration, and validate each
real node's `eth_chainId` observation against that decision. The valueless
CI probes use fictional `424242`; it must not be copied into a mainnet
release without a separate registry review. Cosmos chain identity is
distinct, and both identities must be reviewed and matched.

### Sole proposed founder-controlled administrative wallet (nonfinancial)

The owner has specified that the proposed Privi **network owner, governance
administrator, and treasury controller must be the same public EVM address**:

`0x1990589FD200E043b8C6FD9ec5956c61b3071048`

Dario Canoy / Privi World Corp remain the sole proposed operator. The public
wallet address is a candidate **control identity** only; it does not prove
possession of the private key, confer any current on-chain role, authorize
minting, or set the amount of founder/treasury genesis allocation. All balance
and vesting amounts remain **TBD**. No second platform owner, delegated
administrator, guardian wallet, or multisig owner is authorized by the
candidate policy. See
`../ops/privi_owner_wallet.candidate.json` and the strict
`../ops/verify_privi_single_owner.py` development verifier.

Four validator *consensus signing keys* must remain distinct from one another
and from the owner EVM account; they do not become other treasury or governance
owners. Sole-wallet control is a material key-loss / operator-compromise risk:
funds and governance may become inaccessible if the founder key is lost, and
unauthorized actions can occur if that key is compromised. Store the private
key offline under the owner's control; never supply it to an assistant,
GitHub workflow, hosted build runner, or chat. Independent review remains
necessary even under permissioned single-operator governance.

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


### Experimental externally pinned PoP signer registry

The custom PoP-enabled development app now accepts an optional app-options
string key `privi.pop.trusted_registry_digest`, whose value must be an
externally authenticated lowercase SHA-256 digest from
`prvipop.GenesisDigest(chainID, authorities)`. When supplied, the app
rejects mismatching signed-author genesis **before** SDK module writes,
checks the committed registry at BeginBlock/EndBlock, and also checks it
at the EVM PoP receipt hook to reject same-block substitution. The CI
`wrong-pin` case proves rejection on a valid but differently pinned genesis.

This option is **not authenticated by the program**. A real deployment must
verify the operator-signed release manifest and independently deliver the
trusted digest on every restart. If absent, the app falls back to basic
registry/chain-ID checks for NONFINANCIAL research only. That fallback is
not sufficient for a production financial mainnet. Neither this feature
nor passing CI constitutes PoP BFT finality or release approval.


### PoP default-deny startup restriction (development milestone)

To prevent accidental startup with unpinned PoP signers, the custom
application now requires `privi.pop.trusted_registry_digest` as 64 canonical
lowercase hex characters before initializing the EVM chain or bank keepers.
The only unpinned exception requires **both** an explicit
`privi.pop.allow_unpinned_dev=true` app option and EVM chain ID `424242`;
InitChain also restricts that exception to the two exact valueless fixture
Cosmos chain identities `privi-ci-only-not-financial-1` and
`privi-valueless-genesis-probe-1`. Any other EVM or Cosmos identity is
rejected without an externally supplied pin. This does not authenticate
the submitted digest or make the code ready for financial mainnet; a
trusted owner-signed release is still mandatory.
