# Isolated Railway Privi EVM Devnet

**ONE validator only. Valueless testing only. NOT the four-validator network and NOT a production blockchain.**

This separately deployed Cosmos EVM v0.7.3 reference chain is an interim HTTPS Ethereum JSON-RPC endpoint for MetaMask development. It is deliberately separate from the old Privi NOTE chain and the BNB Chain PRIV token.

- Cosmos ID: `local-4221` (upstream demo name).
- Ethereum EIP-155 chain ID: `262144` (`0x40000`).
- Gas/native coin: `TEST` (base denom `atest`, 18 decimals), with **no monetary value**.
- REST/JSON-RPC: via a separate Railway generated domain only after successfully verified.
- Storage: **separate persistent volume mounted at /data**. The startup script refuses to overwrite unknown existing chain contents or regenerate genesis after partial initialization.
- Exposure: JSON-RPC namespaces `eth,net,web3`. No `personal`, `debug`, `admin`. Avoid using real wallets and implement rate-limiting before public use.
- The Dockerfile pins Cosmos EVM v0.7.3 to an exact upstream Git commit and Go 1.25.9.

**Never deploy it over the legacy Privi service.** Do not confuse this one-validator *development service* with independent four-validator consensus. You cannot create an independent network simply by replicating a single-validator image: a coordinated unique genesis and separate validator signing keys are required. No PRIV assets, BNB token contracts, or user funds are transferred by this code.

The command to validate the resulting URL (only when deployed) is:
```bash
python3 production-network/testnet/evm_smoke.py --rpc https://REPLACE-WITH-DEVNET.up.railway.app --expect-chain 262144
```
