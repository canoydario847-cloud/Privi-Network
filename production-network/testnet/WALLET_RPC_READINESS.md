# Privi disposable TEST developer EVM — wallet RPC readiness

**Status:** Read-only wallet-query testing. **No real PRVI, BNB PRIV, unlocked
wallets, or private-key signing is involved.**

Validator operator recruitment is deferred by the project owner until
operator details are available. This is an independent preparatory milestone,
**not a waiver** of the four-independent-validator public-testnet launch gate.

## Automated wallet-facing JSON-RPC check

The four-local-validator CI workflow now executes:

```bash
python3 production-network/testnet/wallet_rpc_smoke.py \
  --rpc http://127.0.0.1:8545 --expect-chain 262144
```

This probes a deliberately fixed public *read-only* address. It checks:

- Upstream **local developer** EVM chain ID `262144`; rejects mismatches
  and common real/public EVM IDs in this development probe.
- Positive, synchronized EVM block height and a structurally valid
  historical block number and hash.
- `eth_getBalance` and `eth_getTransactionCount` at the **same historical
  block height**, without modifying account state.
- `eth_getCode` hex validity and `eth_gasPrice` response validity.

The checks explicitly require RPC responses from the actual running
developer nodes in CI. Mocked unit tests also exercise malformed responses
and wrong IDs. The tool **never** calls `eth_sendTransaction`,
`eth_sendRawTransaction`, key-management APIs or any signing method.

Passing these reads is **NOT evidence of**:
- a wallet-signed native TEST transfer or mined receipt;
- production wallet extensions, chain-ID configuration, fees or
  account-abstraction support;
- RPC availability on a public multi-host testnet;
- operator independence, slashing/consensus recoverability, audited
  staking or custom PRVI supply cap enforcement;
- financial PRVI mainnet activation.

## Next executable milestones after wallet-query checks

1. Keep the local developer nodes disposable; use throwaway wallets only.
2. Arrange an explicitly authorized transaction funded entirely with
   **valueless developer TEST**, with no real BNB PRIV or PRVI transfers.
3. Verify the actual mined transaction with
   [evm_receipt_audit.py](evm_receipt_audit.py), including value, sender,
   recipient, status, block hash and confirmations. **No successful real
   transfer is claimed until this evidence is recorded.**
4. Evaluate wallet chain metadata and RPC limits with real devices when
   available. Complete four-independent-operator public testnet only after
   the deferred onboarding gate resumes.

Technical work and CI checks are tracked in
[Privi readiness PR #13](https://github.com/canoydario847-cloud/Privi-Network/pull/13).
Financial mainnet stays **NO-GO**.
