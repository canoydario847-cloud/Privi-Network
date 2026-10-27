# Privi Explorer

One public page that searches everything Privi seals:

- **Quantum Ledger** blocks and entries (from Privi Ledger `/quantum-ledger/*`)
- **Privi Quantum** signed results: advantage receipts, crypto inventories, vault receipts (from `/explorer/recent` and `/explorer/lookup`)
- **Anchors on Base** (from Privi Anchor `/anchors/recent` and `/anchors/verify/<hash>`)
- **PRIVI token** supply, transfers and wallet balances, read straight from Base (`mainnet.base.org`)

It is a single static file (`index.html`) with no build step and no server. All data is fetched in the
visitor's browser, so it can be hosted anywhere: IONOS, Cloudflare Pages, Render static sites, or opened from disk.

## Host it on IONOS

1. In IONOS, open your hosting package and go to **Webspace** (or use SFTP with the credentials shown there).
2. Create a folder such as `explorer` and upload `index.html` into it.
3. Point a domain or subdomain (for example `explorer.privishine.info`) at that folder under **Domains & SSL**, and turn on the free SSL certificate.

If a Privi service ever moves, edit the `CFG` block at the top of the `<script>` in `index.html`.

Search accepts a Ledger block height, any 64-character hash, a `0x` Base transaction, a wallet address,
a `qa_` receipt id or a `pp_` passport id. Links like `?q=<anything>` open straight to a result.
