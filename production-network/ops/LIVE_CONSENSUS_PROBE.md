# Native PRVI live consensus verification — read-only probe

This probe checks **observed** EVM and CometBFT RPC state from a future separately approved Privi deployment. It **cannot** authorize financial launch, prove private-key custody, certify independent operators, audit PoP consensus, or prove the 1-billion PRVI lifetime cap. It does not create keys, submit transactions or provision hosts.

Run this only after the owner has approved the exact Cosmos and EIP-155 IDs and secured dedicated RPC gateways:

```bash
python3 production-network/ops/verify_live_consensus.py \
  --evm-rpc https://APPROVED-EVM-RPC.example/ \
  --comet-rpc https://APPROVED-COMET-RPC.example/ \
  --cosmos-chain-id privi-APPROVED-MAINNET-ID \
  --evm-chain-id APPROVED_NUMERIC_EVM_ID
```

Use locally secured HTTPS RPC gateways, not public validator signers. Never paste admin credentials, mnemonics or signing keys. The CLI rejects embedded credentials and remote cleartext HTTP. Reserved upstream developer identities are rejected.

The probe verifies:

- The live EVM identity and latest block timestamp/height
- Matching Cosmos chain ID, commit header identity and height, and a node that is not catching up
- A complete set of at least four unique voting validator addresses, nonzero voting power and no individual signer holding one-third or more of the total
- Actual commit signatures representing **strictly greater than 2/3 of voting power**; absent and nil votes do not count
- Reported EVM/Comet heights within a small allowable synchronization gap

**RPC observations are untrusted without independently verified TLS endpoints and release/genesis hashes.** Fake or misconfigured RPC servers can return fabricated responses. Even a real quorum is insufficient to prove four independently secured private signing keys, disjoint infrastructure, audit completion or Point of Position finality. Recheck commit proofs against a trusted validator and independent RPC peers before making any financial claims.

`status: RPC_QUORUM_OBSERVED_ONLY` is **not** an activation certificate. The output permanently includes `financial_mainnet_authorized: false` and `independent_operator_custody_verified: false`. Final GO requires every gate in [MAINNET_LAUNCH_GATE.md](MAINNET_LAUNCH_GATE.md), including independent audits, exact signed genesis and binary, custody review and incident response.

Unit tests mock all network responses and exercise counterexamples; CI must not attempt to connect to real PRVI endpoints. TEST is valueless; BNB PRIV is separate.
