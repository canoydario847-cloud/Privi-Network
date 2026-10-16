# BNB Chain PRIV → potential native Privi migration

**PLANNING ONLY. NO REAL ASSET MOVEMENT.** Existing BNB PRIV holders, contracts and staking activity remain untouched.

## Contracts to independently verify

- BNB Chain ID: 56.
- Reported PRIV ERC-20/BEP-20 contract: `0xbf154Ff2577F4B85db7B2ee910Db5880D06e0f64`.
- Reported initial supply: 1,000,000,000 PRIV, 18 decimals. Check actual supply at a chosen historical block; audit mint/burn/rebase, fee-on-transfer and upgradable proxy behavior.
- Reported staking: `0xCBCb79306f50b071A083d2d642a097B10F5701F4`. Research unclaimed rewards, staking deposit ownership, pools and custodians; simple balance snapshots do not establish economic entitlement.

## Controlled process

1. Verify source contracts, chain ID, rights, ownership, tokenomics and supply; obtain legal/community review and approval of migration approach.
2. Agree on a well-confirmed BNB snapshot block number and hash. Independently reproduce supply and balances using two separate archive RPC/indexer providers.
3. Run the **read-only** script `snapshot_priv.py`. It reconstructs standard `Transfer` event balances from block 0, validates `totalSupply` and checks samples against historical `balanceOf`. It fails closed on anomalies. Do not treat its output as a final audited holder registry.
4. Review exchange custodians, LPs, staking contracts, rewards, treasury, blackholes, technical wallets and privacy; publish eligibility and disputes procedure before determining holder allocations.
5. Decide on legally and technically reviewed **optional** future burn-and-claim, lock-and-claim or wrapped bridge mechanisms. Prevent double-counting or unbacked 1:1 issuance across BNB and Privi. Native gas currency and bridged PRIV are distinct until explicitly designed.
6. Publish a signed allocation/claim-root manifest only after independent audits; use a timelocked multisig for any issuance authority and perform public testnet dry-runs with **valueless test tokens**.
7. Require independent bridge/claim contract audits, fraud/rollback handling, operator availability, governance approval, and explicit user consent before any mainnet migration.

## Run an optional read-only snapshot (NEVER moves PRIV)

```bash
python3 production-network/migration/snapshot_priv.py \
  --rpc-url "$BNB_ARCHIVE_RPC_URL" --snapshot-block <CONFIRMED_NUMBER> \
  --out production-network/migration/out/priv-holders.json
```

Block number and archive RPC are mandatory. Output contains public wallet addresses; do not publish or commit private eligibility analysis without appropriate review. Incomplete Transfer events or nonstandard token mechanics can produce inaccurate snapshots; the script rejects detectable supply and audit discrepancies. There is no mint, transfer, lock or burn code.
