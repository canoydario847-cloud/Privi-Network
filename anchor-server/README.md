# Privi Anchor MCP

**Timestamped proof that data existed, on chain.** Any AI agent can fingerprint what it produced or relied on (a report, generated image, dataset, contract, model card, audit-log head) and anchor that fingerprint on chain. Anyone can later prove the exact content existed at that time and hasn't changed, by checking the chain itself rather than trusting Privi.

Works with Claude, ChatGPT, Cursor, VS Code and custom agents. Part of the Privi suite with [Privi Verify](../mcp-server) and [Privi Ledger](../ledger-server).

**Live:** `https://privi-anchor.onrender.com/mcp`, anchoring on the **Privi Devnet** (EVM chain ID 772626, RPC and explorer at https://privi-devnet.onrender.com) until the Privi mainnet launches. Anchors made earlier on **Base** (chain 8453) still verify: `anchor_verify` reads them from Base, read-only (`ANCHOR_ARCHIVE_CHAINS`). Anchors from the retired 262144 devnet are reported as such instead of failing.

## Tools

| Tool | Access | What it does |
|---|---|---|
| `anchor_status` | free | Chain, anchor wallet, gas balance, totals |
| `anchor_hash_text` | free | SHA-256 of text, ready to anchor |
| `anchor_verify` | free | Proves on chain that a hash was anchored, by whom and when. With a receipt's `tx_hash` + `proof`, uses chain data only |
| `anchor_hashes` | API key | Anchors 1-100 hashes in one transaction; returns a receipt per hash |

Only hashes go on chain, never content.

## How it works

1. The hashes in a call become leaves of a SHA-256 Merkle tree (`node = sha256(min(a,b) || max(a,b))`).
2. One zero-value transaction from the anchor wallet to itself carries the root in its data: `0x50525641` ("PRVA") + `0x01` + 32-byte root. No contract is needed.
3. Each hash gets a receipt: the transaction hash and its Merkle proof.
4. To verify, read the transaction from the Privi Devnet RPC (https://privi-devnet.onrender.com, or its explorer), take the root from its data, and recompute it from the hash and proof. The block's timestamp is the proof of when.

Independent check in a few lines:

```python
import hashlib
def node(a, b): return hashlib.sha256(min(a, b) + max(a, b)).digest()
x = bytes.fromhex(my_hash)
for sib in proof: x = node(x, bytes.fromhex(sib))
assert x.hex() == tx_input[12:]   # strip "0x" + "50525641" + "01"
```

## Access

`anchor_hashes` needs `Authorization: Bearer <key>` with a key from `ANCHOR_API_KEYS` and is rate-limited per key. It's free with a key. Each call is one Privi Devnet transaction (valueless TEST gas, paid by the anchor wallet); the server still enforces a daily budget against abuse (`ANCHOR_MAX_TX_PER_DAY`, default 5000). Batch up to 100 hashes per call.

## Run, test, deploy

```bash
pip install -e ".[dev]"
cp .env.example .env     # set ANCHOR_PRIVATE_KEY and ANCHOR_API_KEYS
pytest
privi-anchor-mcp         # HTTP :8000, MCP at /mcp
```

The anchor wallet is a hot key. On the Privi Devnet it is funded with TEST in genesis (`DEVNET_FUND_ADDRESSES` on the devnet service). `/status` shows its balance and `gas_ok`.

## License

MIT © 2026 Dario Canoy, Privi World Co
