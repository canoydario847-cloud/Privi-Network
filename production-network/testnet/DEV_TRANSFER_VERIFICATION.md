# PRVI developer EVM transaction receipt verification

**Status:** Tools and mocked unit tests are prepared. **No real test transaction has been executed or verified by this change.**

A successful local [four-validator smoke CI run #147](https://github.com/canoydario847-cloud/Privi-Network/actions/runs/39073186273) demonstrates CometBFT consensus and read-only Ethereum RPC against disposable, same-host upstream example nodes. It does **not** exercise an independently signed and mined ETH-style value transfer.

Use only a **throwaway MetaMask development wallet**, funded with upstream **valueless developer TEST**, to submit a transaction against the local RPC, or use an authorized dev-only signing client. Never use a wallet holding BNB PRIV or real assets. Confirm the developer network EVM ID **262144**, distinct from the Cosmos string `local-4221`.

Once a positive-value transfer has been **signed and broadcast by a test wallet** and mined, independently verify the hash, sender, destination, native TEST amount, successful receipt, block inclusion and confirmations:

```bash
python3 production-network/testnet/evm_receipt_audit.py \
  --rpc http://127.0.0.1:8545 \
  --expect-chain 262144 \
  --tx-hash 0xYOUR_REAL_64_HEX_TX_HASH \
  --sender 0xYOUR_REAL_DEV_SENDER \
  --recipient 0xYOUR_REAL_DEV_RECIPIENT \
  --value-wei 1000000000000000 --min-confirmations 2
```

A successful check must use the **actual** mined transaction on that disposable local chain. This tool never signs or broadcasts a transaction and cannot create a receipt.

**Not established by this test:** balance deltas, gas economics, transfer across independent validators or host failures, staking, custom PRVI denomination, 1B PRVI supply cap, inflation limits, vesting, production wallet compatibility, auditor acceptance, financial mainnet or exchange eligibility.
