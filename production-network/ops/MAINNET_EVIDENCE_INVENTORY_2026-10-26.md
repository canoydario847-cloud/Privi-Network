# PRVI mainnet engineering evidence inventory — 2026-10-26

**Decision: NO-GO. This is an evidence inventory, not authorization to launch.**

Reviewed repository documentation at main commit `172ce8dbb6e7d808c3a62d66b0f2f31e44dfb496`. No production genesis, audited custom binary, independent validator attestations, or production consensus proof was established by this review.

## Verified repository state

- `production-network/README.md` identifies upstream Cosmos EVM v0.7.3 `evmd` as a **reference implementation**, not a Privi-customized audited binary.
- The local four-validator bootstrap is a **single-host demo**, not four independent production validators.
- `production-network/mainnet/GENESIS_INPUTS_AND_REVIEW.md` leaves Cosmos chain ID, EIP-155 ID, base denom, allocations, release digest and genesis digest undecided. The demo EVM ID `262144` must not be treated as approved production identity.
- `production-network/ops/MAINNET_LAUNCH_GATE.md` records eight blocked gates. The pure-Go cap model is not consensus-integrated; the 1-billion PRVI lifetime cap is therefore **not enforced on a production chain**.
- TEST must remain valueless and BNB PRIV separate; do not mint, bridge or enable sales as part of this inventory.

## Next build sequence and required artifacts

1. **Chain fork:** pin upstream source, fork a Privi-customized binary, record reproducible build SHA-256 and software bill of materials. Review all mint authorities and upgrades; wire cap enforcement into persistent consensus state and test against bypass routes.
2. **Identity and genesis:** approve distinct Cosmos/EVM chain IDs, base denom and staking/governance parameters; produce offline unsigned genesis and independently reconcile bank supply, vesting and issuance rules.
3. **Four operators:** collect public validator keys and independently verified custody/fault-domain evidence from four operators. Do not store secrets in GitHub.
4. **Public testnet:** run the same candidate binary on independent hosts; archive CometBFT commit proofs, EVM receipts, failover, restore and double-sign prevention results.
5. **Release:** complete independent audit and operational reviews, then obtain operator-signed hashes and named GO authorization as required by `MAINNET_LAUNCH_GATE.md`.

## Read-only checks to run when evidence exists

```bash
python3 production-network/ops/genesis_supply_audit.py \\
  --genesis /secure/review/candidate-genesis.json \\
  --denom REVIEWED_BASE_DENOM \\
  --chain-id REVIEWED_COSMOS_MAINNET_CHAIN_ID
node --test production-network/ops/test_verify_operator_release.cjs
node production-network/ops/verify_operator_release.cjs \\
  --manifest /secure/release-evidence.json
```

These commands require real reviewed inputs; no pass result is claimed here. Keep all financial launch gates BLOCKED until evidence is independently verified.
