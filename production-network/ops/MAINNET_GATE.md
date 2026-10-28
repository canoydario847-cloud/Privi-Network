# Native PRVI mainnet evidence gate

Run from repository root:

```bash
python3 production-network/ops/mainnet_gate.py production-network/ops/mainnet_evidence.example.json
python3 -m unittest discover -s production-network/ops -p 'test_mainnet_gate.py'
```

The CLI intentionally returns a **nonzero NO-GO exit status for every evidence document**, even if all declared review links and reviewer fields are present. No automation may interpret a successful presence check as authority to launch. `check()` is an offline shape/presence diagnostic only; it cannot authenticate evidence URLs or reviewer claims.

The example intentionally returns **NO-GO**. Create a separate private evidence JSON only when audits and operational reviews have completed. Never commit validator private keys, seed phrases, wallet credentials, or sensitive infrastructure information. Every gate requires reviewer attribution and a publicly accessible HTTPS evidence reference; a URL alone is not proof. This script checks completeness of review records, **not** correctness, validator independence, actual consensus, audit quality or launch authorization. It cannot certify mainnet readiness.

POP is a proposed consensus requirement, not demonstrated in the current upstream Cosmos EVM localnet. No financial mainnet, native minting, bridge, token sale or chain migration is activated by this code. TEST and BNB PRIV remain separate.
