# Privi mainnet release commitment contract — build-only

The `PriviMainnetReleaseCommitment.sol` contract records SHA-256 commitments for genesis, node binary, source commit, a release evidence manifest and chain identity. It is an **evidence registry draft**, not a PRVI native monetary issuance contract, validator consensus engine, permission to launch or external audit. It holds no funds, has no token balances or minting entrypoints, and does not control native Cosmos SDK bank balances or the proposed Proof of Participation mechanism.

The initial operator is set once at deployment, and changes use an explicit two-step owner handoff. Only the operator can append release commitments. A repeated genesis hash is rejected. Uploaded digests are operator declarations; publishing them does **not** validate them or prove independent reviewer approvals. Do not place confidential genesis details, secrets or private evidence URLs on a public chain.

Test offline:
```bash
npm install --no-save --no-package-lock --ignore-scripts solc@0.8.24
node --test production-network/mainnet/contracts/test_release_commitment.cjs
```

**NO DEPLOYMENT OR REAL ASSETS AUTHORIZED:** This artifact is not audited, no contract address exists, financial PRVI mainnet remains NO-GO and no fee or transaction should be paid to register these hashes without an independently reviewed deployment plan.
