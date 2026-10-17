# Privi mainnet genesis/validator consistency — production review gate

**Not live. Not a wallet, node release, token distribution or authorization to launch.**
This source-only gate operates on future OFFLINE, independently reviewed genesis
and public operator data. No real operator identities are invented here.

## Review integration

\`deployment_readiness.py\` now cross-checks the canonical genesis' initial
consensus public keys against the roster of **at least seven independently
controlled validators** in addition to:

- SHA-256 of the exact full genesis JSON, ledger and reviewed production binary;
- the approved Cosmos/EVM network IDs and exactly 1,000,000,000 PRVI;
- actual \`aprvi\` bank balances, vesting and the operator attestations
  over genesis/binary/allocations hashes;
- independent beneficial-ownership and security/legal approvals that **must
  still be verified by humans**.

\`genesis_operator_binding.py\` supports either:

1. Nonempty CometBFT \`validators\` in the canonical genesis. Each Ed25519
   pubkey and voting power must match the independently reviewed roster.
2. Cosmos SDK \`app_state.genutil.gen_txs\`, one
   \`/cosmos.staking.v1beta1.MsgCreateValidator\` per operator with a valid
   32-byte Ed25519 consensus public key, native \`aprvi\` self-delegation,
   a native \`privivaloper1\` address and a present, plausibly encoded
   transaction signature.

If both forms are present, their public-key sets must agree. If neither is
present, the integrated release gate **fails closed**. Any duplicate, missing
or extra public key or voting power concentration of at least one third is
rejected. Real operator attestations remain independently checked by
\`operator-kit/ceremony_verify.py\`.

**Limitations:** This is *static* JSON screening only. It does **not**
cryptographically verify the on-chain genesis gentx signatures, prove wallet
ownership, confirm the valoper Bech32 checksum, execute the Cosmos SDK
InitChain/genutil path, establish on-chain minted supply invariants, or certify
validator independence. Before approving a financial launch:

- Run the exact reviewed production binary's \`validate-genesis\`/equivalent
  offline and an **isolated valueless** end-to-end InitChain test; verify the
  **resulting initial CometBFT validator set** and voting power.
- Cross-check Comet validator address hashes against each operator's own
  independently attested Ed25519 public key.
- Verify raw signed gentx signatures with the actual chain's Cosmos SDK
  TxConfig/sign mode, independent operator account owners and reviewed
  staking/self-delegation amounts. A nonempty Base64 signature does NOT mean
  a valid signature.
- Have **each** real operator independently attest the identical canonical
  genesis SHA-256, approved Cosmos/EVM IDs, audited binary SHA-256 and verified
  allocations ledger SHA-256. Signatures must be verified, no private
  consensus signing keys shared.
- Independently rehearse key fencing, no-double-sign restores, slashing,
  staking, fee behavior and governance upgrades. External security/economic
  audit, legal review and written manual release authorization are mandatory.

The Privi TEST devnet, BNB PRIV and CI-only synthetic candidate binary are
**never** financial PRVI mainnet artifacts. Never reuse their genesis or keys.
