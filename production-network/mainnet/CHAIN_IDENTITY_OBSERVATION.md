# Privi node identity observations — not a mainnet authorization

**Status: build-only / NO FINANCIAL MAINNET LAUNCH.** Cosmos EVM has two distinct identities: the Cosmos/CometBFT chain ID and Ethereum transaction chain ID. A node with the right Cosmos ID and the **wrong** EVM chain ID is *not* the approved candidate chain. The pinned Cosmos EVM reference application's EVM chain ID is supplied through app options and can default to `262144`; matching only unsigned genesis or bank denomination fields is therefore insufficient.

This document establishes a **read-only observation** milestone for a future, Contabo-hosted, *valueless* staging node. It cannot authenticate captured responses or verify a production genesis, a peer or a signing key.

## Capture responses with the owner's authenticated access

Only after the host OS, admin access, firewall and RPC loopback binding have been independently verified, run these commands in a trusted shell **on the staging node**:

```sh
umask 077
# Internal Comet status; never bind RPC to all interfaces for this check.
curl --fail --silent --show-error --max-time 5 http://127.0.0.1:26657/status > comet-status.json

# Query the local Cosmos EVM JSON-RPC endpoint with no wallet or private key.
curl --fail --silent --show-error --max-time 5 \
  --header 'Content-Type: application/json' \
  --data '{"jsonrpc":"2.0","id":1,"method":"eth_chainId","params":[]}' \
  http://127.0.0.1:8545 > eth-chain-id.json
```

**These commands are examples, not remote actions performed in GitHub or ChatGPT.** If either local RPC endpoint is unavailable, do not expose it to the internet as a shortcut. The captured replies may contain node/public peer identifiers; keep them private until reviewed. Never submit wallets, passwords, signing keys, mnemonics or privileged RPC methods.

## Offline check

After independently approving the **intended** staging Cosmos and Ethereum chain IDs (do not copy the example chain IDs into financial mainnet), run:

```sh
python3 production-network/ops/verify_node_identity.py \
  --comet-status comet-status.json \
  --eth-chain-id eth-chain-id.json \
  --expected-cosmos-id REPLACE_WITH_REVIEWED_COSMOS_ID \
  --expected-evm-id REPLACE_WITH_REVIEWED_UINT64_ID
```

The verifier rejects a mismatched Cosmos `node_info.network`, EVM `eth_chainId`, missing finalized block hash, unverified synchronization, and chains that have not finalized at least two blocks. It emits `MATCHES_DECLARED_NODE_IDENTITIES_ONLY`, **never** `MAINNET_LIVE`. Its inputs are local captured JSON, not an authenticated cryptographic proof of what ran on the Contabo VPS.

## Production acceptance remains separate

- Review the exact live `evmd` binary version, source commit and executable checksum on each intended host.
- Compare each host's independently retrieved genesis SHA-256 to the one signed and approved by the operator/security reviewers.
- Verify **all four** unique consensus signing public keys and that nodes are on distinct actual fault domains, not four containers on one VPS.
- Validate non-TEST native denom, no post-genesis native PRVI issuance, RPC and peer topology, slashing and signer recovery, upgrade paths, security fixes, and signed evidence. Follow [MAINNET_LAUNCH_GATE](../ops/MAINNET_LAUNCH_GATE.md).

**Passing this observation checker alone is not launch evidence sufficient for a financial blockchain, and is not evidence that a particular server is deployed or reachable.**
