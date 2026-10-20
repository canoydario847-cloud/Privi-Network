# Privi Verify MCP

An MCP server that lets AI agents check **where a manufactured lot came from** and **whether its records were changed after the fact**, paid per call in USDC on Base using [x402](https://github.com/x402-foundation/x402).

Works with any MCP client: Claude, ChatGPT, Cursor, VS Code, and custom agents.

**Live (testnet):** `https://privi-verify.onrender.com/mcp` · demo lots `DEMO-STEEL-0001`, `DEMO-FOOD-0001`

Built by [Privi World Co](https://github.com/canoydario847-cloud) (Port Huron, Michigan) as the agent-facing side of **Privi ChainFlow**.

## Tools

| Tool | Price | What it does |
|---|---|---|
| `privi_pricing` | free | Lists tools, prices, network, and the payout wallet |
| `privi_lookup_fingerprint` | free | Checks whether a record fingerprint (from a label, certificate or document) exists |
| `privi_verify_lot` | $0.01 | Lot summary: product, first and latest custody events, recall status, record integrity |
| `privi_chain_of_custody` | $0.05 | Full ordered event history with fingerprints and an integrity check |
| `privi_record_event` | API key | Manufacturers append events: `received`, `produced`, `inspected`, `shipped`, `transferred`, `recalled` |

Prices are set with environment variables.

## How records stay honest

Each event's fingerprint is a SHA-256 of its contents **plus the previous event's fingerprint** in the same lot. Editing or deleting any past event breaks every fingerprint after it, and both verify tools report exactly where the chain broke.

> Each lot's latest fingerprint is anchored on the Privi blockchain every few minutes (see On-chain checkpoints), so anyone can check it without trusting Privi.

## On-chain checkpoints

Every 5 minutes the server anchors the latest fingerprint of each lot that changed on the Privi blockchain through [Privi Anchor](../anchor-server). Audit results include `onchain_checkpoint`: the anchored position, transaction, and Merkle proof, plus an `anchor_verify` call anyone can run. If stored history no longer matches what was anchored, the audit fails even when every local hash was recomputed consistently. Set `PRIVI_ANCHOR_KEY` (an Anchor API key) to turn it on; `PRIVI_ANCHOR_INTERVAL` changes the period (seconds, default 300).

## How payment works (x402 over MCP)

Follows the [x402 v2 MCP transport spec](https://github.com/x402-foundation/x402/blob/main/specs/transports-v2/mcp.md):

1. The agent calls a paid tool. The server answers `isError: true` with a `PaymentRequired` object listing price, network, USDC contract and the `payTo` wallet.
2. The agent's wallet signs a USDC authorization and retries with it in `_meta["x402/payment"]`.
3. The server checks the payment matches the price, has the facilitator **verify** it, runs the tool, has the facilitator **settle** it, and returns the result with the receipt in `_meta["x402/payment-response"]`.

If settlement fails, the agent gets no result. Payments go straight to the `PRIVI_PAY_TO` wallet; the server never holds funds or private keys.

## Run it

```bash
pip install .
cp .env.example .env        # set PRIVI_PAY_TO and PRIVI_WRITE_KEYS
python scripts/seed_demo.py # optional demo lots (or set PRIVI_SEED_DEMO=1)
privi-verify-mcp            # HTTP on :8000, MCP endpoint at /mcp
```

Over stdio (e.g. Claude Desktop):

```json
{
  "mcpServers": {
    "privi-verify": {
      "command": "privi-verify-mcp",
      "args": ["--stdio"],
      "env": { "PRIVI_PAY_TO": "0xYourWallet", "PRIVI_NETWORK": "base-sepolia" }
    }
  }
}
```

Remote clients connect to `https://<your-host>/mcp`. `GET /health` returns status.

## Make a test payment

`scripts/test_payment.py` pays the live server exactly the way an AI agent would, using a throwaway Base Sepolia wallet (free testnet USDC, no real money):

```bash
pip install eth-account
python scripts/test_payment.py --new-wallet   # prints a test wallet address
# get testnet USDC at https://faucet.circle.com (Base Sepolia), then:
python scripts/test_payment.py                 # pays $0.01, verifies DEMO-STEEL-0001, prints the tx link
```

The key is saved to `.agent-wallet` (git-ignored). The script refuses to pay on mainnet unless you pass `--allow-mainnet`.

## Deploy

The `Dockerfile` runs on Railway, Render, Fly or any container host:

- Set `PRIVI_PAY_TO`, `PRIVI_WRITE_KEYS` and `PRIVI_NETWORK`.
- Mount a volume at `/data` so the SQLite database survives redeploys.
- Start on **`base-sepolia`** with testnet USDC. Switch to `base` only after a full test payment works, and set `PRIVI_FACILITATOR_URL` to a production facilitator, since the public one is testnet only.

## Recording events

```bash
curl https://<your-host>/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H 'Authorization: Bearer <your-write-key>' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"privi_record_event",
       "arguments":{"lot_code":"LOT-0001","event_type":"produced","location":"Port Huron, MI",
                    "actor":"Your Plant","product":"Bracket A-12","quantity":"800 pcs"}}}'
```

## Develop

```bash
pip install -e ".[dev]"
pytest
```

Tests cover the payment flow (missing, mismatched, invalid and failed-settlement payments), tamper detection, and write authorization, using a stand-in facilitator.

## Roadmap

- Per-manufacturer accounts and dashboards (Privi ChainFlow)
- Postgres storage for multi-instance hosting
- Listings in MCP directories

## License

MIT © 2026 Dario Canoy, Privi World Co
