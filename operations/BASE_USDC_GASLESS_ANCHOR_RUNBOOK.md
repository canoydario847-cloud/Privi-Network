# Privi Base anchoring: no ETH required in the service wallet

## Verified problem (Nov 15, 2026)

- Render service **privi-anchor** has EOA signer `0x4228f264fEA8e2FDb1e21a3d124673653E4B3bF7`. Logs show `balance_wei=0`.
- The existing `anchor-server/src/privi_anchor/chain.py` sends ordinary EOA self-transactions. On Base, these still need native ETH. Sending USDC to the same signer will **not** pay EOA gas.
- Privi Ledger's service reports are still HTTP 200 and its signed/hashed Master Ledger entries continue. **External Base settlement of newly sealed blocks is pending**, not confirmed.

## Immediate zero-cost production action

Until an approved paymaster is live, use **Master Ledger–only** mode:

| Render service | Environment variable | Value |
| --- | --- | --- |
| Privi Anchor | `ANCHOR_BASE_TX_ENABLED` | `0` |
| Privi Ledger | `LEDGER_EXTERNAL_ANCHORS` | `0` |
| Privi Verify | `PRIVI_EXTERNAL_ANCHORS` | `0` |
| Privi Quantum | `QUANTUM_EXTERNAL_ANCHORS` | `0` |
| Privi Call | `CALL_EXTERNAL_ANCHORS` | `0` |

These flags stop repeated unfunded ETH transfers; they **do not** stop signed Master Ledger append, Quantum Ledger block sealing, outbox delivery, or payment handling. Transaction requests requiring a Base receipt return an explicit failure or remain pending; never show them as completed Base anchors. Disabled state is exposed via `anchor_status` and `/status`.

Do not disable the underlying service, delete the onchain receipt queue, or put fake tx hashes into Ledger.

## USDC gas option A — permissionless paymaster

Circle Paymaster supports Base and ERC-4337 compatible accounts, including an EIP-7702-upgraded EOA. The paymaster pays network gas in ETH and collects the fee in **native USDC on Base** (typically adding a percentage surcharge). A bundler submits the user operation. The regular EOA transaction code cannot simply switch fee currency; this is a different transaction protocol.

- Circle official: https://www.circle.com/paymaster
- Pimlico (bundler and ERC-20 paymaster, Base + EIP-7702): https://docs.pimlico.io/guides/how-to/payments/send-usdc-without-eth
- Coinbase CDP sponsored gas credits: https://www.coinbase.com/developer-platform/products/paymaster

The guarded `anchor-server/usdc-paymaster/anchor.mjs` is a separate **pilot**, not the existing anchor's live broadcaster. It can create a `PRVA`-formatted 32-byte Merkle root calldata in a single EIP-7702 ERC-4337 UserOperation. It does **not** yet produce receipts usable by legacy `anchor_verify`, because the outer transaction targets EntryPoint rather than a direct EOA self-transaction. You must finish an independently verifiable UserOperation evidence format before making it a customer-facing proof.

### Safe dry run (no keys, network or funds)

```sh
cd anchor-server/usdc-paymaster
node anchor.mjs --root YOUR_LOWERCASE_SHA256_DIGEST
node --test test_anchor.mjs
```

Default is dry-run. It only prints the proposed calldata, target and proof type; **no transaction is sent**.

### Controlled USDC pilot (not automatic production activation)

Only after reviewing the EIP-7702 delegation and confirming the Anchor EOA holds Base USDC, configure a dedicated non-custodial signer and Pimlico mainnet-enabled bundler account. Do **not** reuse a wallet holding customer funds or move the owner's personal USDC automatically.

```sh
cd anchor-server/usdc-paymaster
npm install
# Set ANCHOR_PRIVATE_KEY, PIMLICO_API_KEY privately using deployment secrets.
# Operator explicitly opts in to EIP-7702 delegation and one operation:
PRIVI_USDC_ANCHOR_EXECUTE=1 PRIVI_USDC_ANCHOR_EIP7702_APPROVED=1 \
  node anchor.mjs --root SHA256_ROOT --mode usdc --execute
```

The first EIP-7702 authorization *persists as smart-account delegation*. It is security-sensitive and must be reviewed before using a production signer. There is no automatic mainnet spend or delegation in this repository or Render settings. Client libraries are pinned for an isolated pilot, and no wallet secret appears in GitHub.

### Option B — sponsored operation with no USDC in the Anchor EOA

If the service signer has neither ETH nor USDC, an **approved sponsor paymaster policy** can cover gas from a provider's account or promotional credits. This still requires provider setup and bounded sponsorship, not magically free perpetual chain access. In the script this is `--mode sponsored`, requiring `PIMLICO_SPONSORSHIP_POLICY_ID`, with transaction target and daily budget limited in the provider dashboard. Coinbase CDP offers a separate sponsorship product; do not assume an x402 facilitator key automatically creates a Paymaster account.

## Read-only independent UserOperation proof checker

New `anchor-server/usdc-paymaster/verify.mjs` checks an already-mined, Base EntryPoint 0.8 `handleOps` transaction **without** API keys, signatures or transfers. It verifies chain ID 8453, canonical transaction/block/receipt, two confirmations by default, EIP-7702 delegation to the pinned Simple7702Account implementation, successful `UserOperationEvent` matched by the entrypoint-computed operation hash, and exact `PRVA` Merkle root passed to the approved zero-value destination. A batched Base-USDC paymaster approval must have the paymaster address as spender and no more than 0.05 USDC allowance; arbitrary extra calls are rejected.

```sh
cd anchor-server/usdc-paymaster
npm install --ignore-scripts
npm test
node verify.mjs --root <64_HEX_DIGEST> --tx <BASE_TX_HASH> --userop <USER_OPERATION_HASH> --sender <PUBLIC_ADDRESS>
```

On success it outputs `verified: true` with an onchain proof; it **does not assert that gas was actually paid in USDC**, that a sponsor paid, or that a customer made a payment. The verifier has no wallet access and cannot cause spending. For now it is a separate CLI and **is not wired into legacy anchor_verify**; do not treat old self-transaction proof and new UserOperation proofs as interchangeable.

No transaction is known to have been submitted through this new paymaster path yet, so this is tested verification logic, not proof of a completed production anchor.

## Production launch gates before re-enabling onchain settlement

1. Verify sponsor or USDC paymaster availability and a cost limit per checkpoint. Check the **Anchor signer address**, not the personal sales wallet; public Base balance may be zero.
2. Build a trustworthy `prva-userop-v1` verifier that fetches a confirmed UserOperation, checks its sender, target and exact Merkle root calldata, validates the EntryPoint event and chain ID, and produces a proof others can reproduce.
3. Confirm sample transaction on **Base Sepolia** first, then one owner-approved small Base receipt, compare USDC spent and onchain status. Reconcile any ambiguous receipt before retrying to avoid double-paying.
4. Implement an authorized adapter in Privi Anchor that generates the correct proof type and stores its transaction ID. Do not treat UserOp hash as equivalent to the legacy EOA transaction hash.
5. On verified success, switch **one** Master Ledger settlement process on. Keep Verify/Call/Quantum's redundant direct anchoring disabled: they report through Privi Ledger.
6. Verify block seal and external receipt on `/quantum-scan` and independently in BaseScan, then retire duplicate history only after backups and reconciliation.

**Never assert Base anchoring is complete when service signing gas is unavailable.** Production migration and USDC charges remain unverified until the chain receipts and actual provider configuration are confirmed.
