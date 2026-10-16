# Privi EVM developer demo (not mainnet)

Four-node Cosmos EVM reference chain via pinned upstream evmd. **This is separate from the deployed Railway NOTE chain `privi-dev-1`** and the BNB Chain PRIV token. The demo chain ID is **Cosmos `local-4221`, expected EVM numeric `4221`**; verify the number over JSON-RPC rather than trusting a label.

## Start local testnet

Requires Git, Make, Docker daemon and Docker Compose v2. From the GitHub repo root:

```bash
bash production-network/testnet/bootstrap-local-4.sh
python3 production-network/testnet/consensus_audit.py \
  --chain-id local-4221 \
  --rpc http://127.0.0.1:26657 --rpc http://127.0.0.1:26667 \
  --rpc http://127.0.0.1:26677 --rpc http://127.0.0.1:26687
python3 production-network/testnet/evm_smoke.py \
  --rpc http://127.0.0.1:8545 --expect-chain 4221
```

The consensus audit checks identical blocks, four distinct voting validator addresses, and >2/3 signed voting power. Four processes running on one machine are NOT independent production operators. Generated keys are disposable.

## MetaMask and native test transfers

Serve the wallet UI only on the same computer as the local RPC:

```bash
cd production-network/testnet
python3 -m http.server 8088 --bind 127.0.0.1
```

Open `http://127.0.0.1:8088/privi-wallet.html`, press **Check EVM chain**, then **Connect MetaMask**. The app reads the live `eth_chainId` and adds the detected test network. Use a disposable development MetaMask wallet; never use seed phrases protecting real assets.

Enter a recipient 0x address and send valueless **TEST** coins with MetaMask. This uses actual `eth_sendTransaction` and wallet signing, not the custom Privi NOTE API. A new test wallet needs a funded local testnet balance to send. A returned hash means submission, not confirmation; check `eth_getTransactionReceipt`.

| Example field | Local demo |
| --- | --- |
| Network | Privi EVM Developer Demo (upstream evmd) |
| RPC | http://127.0.0.1:8545 |
| Cosmos chain ID | local-4221 |
| EVM chain ID | 4221 (verify RPC) |
| Display/test token | TEST (valueless, 18 decimals) |
| Block explorer | Not yet deployed for this EVM chain |

These are local developer settings, NOT verified public MetaMask settings. Never label this token PRIV or transfer production BNB PRIV.

## To actually become an independent Privi network

Fork/review the upstream Go application, select a unique EIP-155 chain ID and native denomination, create a reviewed shared genesis and independently hosted validators, and test transfers/receipts and consensus under failure. Only then deploy read-only public RPC and an EVM-aware explorer with audits and monitoring. Do not deploy the demo private keys publicly.