# Jose backend — v3

Accounts, app plugins, and (new in v3) **Hey Jose** live AI chat paid in JOSE, **MetaMask** wallet linking, and an **NFT marketplace**. Plain Node 22, no npm dependencies.

```
npm start      # node src/server.js
npm test       # unit tests + end-to-end test against a fake chain and fake AI
```

## What's new in v3

| Feature | Pages | API |
|---|---|---|
| Hey Jose chat (ES/PT/中文/EN) | `chat.html` | `POST /api/chat` |
| AI credits paid in JOSE | `chat.html`, `dashboard.html` | `GET /api/credits`, `POST /api/credits/claim` |
| Link MetaMask wallet (signed message, no gas) | `dashboard.html` | `POST /api/wallet/challenge`, `/api/wallet/link`, `/api/wallet/unlink` |
| Add network / JOSE token to MetaMask | `dashboard.html`, jose-site | `GET /api/config` (public, CORS-open) |
| NFT marketplace — browse, list, detail, withdraw | `market.html`, `nft.html` | `GET/POST /api/nfts`, `GET /api/nfts/:id`, `POST /api/nfts/:id/cancel` |

How it works:

- **Credits.** New accounts get `JOSE_FREE_CREDITS` once. Each chat message costs `JOSE_CREDITS_PER_MESSAGE`; a failed AI answer is refunded. To buy more, the user sends JOSE from their **linked** wallet to `JOSE_TREASURY_ADDRESS`; the server reads the transaction receipt from the chain, checks the `Transfer` came from that wallet to the treasury, waits for `JOSE_MIN_CONFIRMATIONS`, and credits `amount ÷ JOSE_PER_CREDIT`. Each tx hash can be claimed once.
- **Wallet linking.** The server issues a one-time message; the user signs it with `personal_sign`; the server recovers the signer and links that address. One wallet per account.
- **Marketplace.** A listing is accepted only if `ownerOf(tokenId)` on-chain is the seller's linked wallet. If the NFT later leaves that wallet, the listing shows as stale. **Listings are a catalogue — nothing on these pages moves funds or NFTs.** On-chain buying needs a marketplace contract, which is a separate step.
- **Chat history** is kept in the browser tab and sent each turn; the server stores no transcripts.

## Environment variables

Existing: `PORT`, `BASE_URL`, `APP_SECRET` (required), `DB_FILE`, and the plugin keys.

New in v3:

| Variable | Default | Needed for |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Hey Jose (off without it) |
| `JOSE_AI_MODEL` | `claude-sonnet-5-5` | |
| `JOSE_AI_MAX_TOKENS` | `1024` | |
| `JOSE_FREE_CREDITS` | `10` | |
| `JOSE_CREDITS_PER_MESSAGE` | `1` | |
| `JOSE_TOKEN_ADDRESS` | — | Add-token button + payments |
| `JOSE_TREASURY_ADDRESS` | — | Payments (wallet that receives JOSE) |
| `JOSE_PER_CREDIT` | `1` | JOSE per credit |
| `JOSE_TOKEN_DECIMALS` | `18` | Must match the token |
| `JOSE_TOKEN_SYMBOL` | `JOSE` | |
| `JOSE_TOKEN_IMAGE` | — | Optional token icon URL for MetaMask |
| `JOSE_MIN_CONFIRMATIONS` | `3` | |
| `JOSE_CHAIN_ID` / `JOSE_CHAIN_NAME` | `8453` / `Base` | |
| `JOSE_RPC_URL` | `https://mainnet.base.org` | Use a paid RPC in production |
| `JOSE_EXPLORER_URL` | `https://basescan.org` | |

Payments switch on only when both `JOSE_TOKEN_ADDRESS` and `JOSE_TREASURY_ADDRESS` are set; until then the pages say so and users run on starter credits.

## Also fixed in v3

- Dashboard error banner rendered the URL's `error` text as HTML (script injection); it now renders as text.
- Login `next=` could redirect to any outside site; it now only follows same-site paths.
- Request bodies are capped at 200 KB; malformed JSON returns 400 instead of 500.
