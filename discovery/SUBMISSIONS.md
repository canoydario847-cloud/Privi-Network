# Submissions — copy-paste pack

Everything below is pre-written. Each one takes 2–5 minutes and needs your own sign-in, which is why it isn't automated. Order is by expected payoff.

## Already done automatically
- Official MCP Registry: privi-ledger, privi-verify, privi-anchor republished at 0.2.0 with discovery-hub links (GitHub Action, Oct 20).
- IndexNow: hub URLs pushed to Bing / Yandex / Naver / Seznam (feeds Copilot and DuckDuckGo). Key served at `/<INDEXNOW_KEY>.txt`.
- Each MCP server's `instructions` now names you and links the hub.


## 0. x402 Bazaar (Coinbase's discovery index for paying agents) — highest leverage

Privi Verify and Privi Ledger now declare `extensions.bazaar` on every paid tool (x402 specs/extensions/bazaar.md),
with the real MCP endpoint, input schema, example and output. The Coinbase facilitator indexes a tool after its
first settled payment (up to 15 minutes). Trigger each once with a throwaway wallet holding a few cents of USDC on Base:

    cd mcp-server && pip install eth-account
    python scripts/test_payment.py --new-wallet        # prints an address; send it ~0.25 USDC on Base
    python scripts/test_payment.py --allow-mainnet --url https://privi-verify.onrender.com/mcp --tool privi_verify_lot
    python scripts/test_payment.py --allow-mainnet --url https://privi-verify.onrender.com/mcp --tool privi_chain_of_custody

Usage is public at https://privi-ledger.onrender.com/stats and https://privi-verify.onrender.com/stats.

## Shared copy

**Name:** Privi Ledger · Privi Verify · Privi Anchor (list separately where directories want one server per entry)

**One-liner:** Verifiable infrastructure for AI agents — pay, prove, and audit on-chain.

**Short description (≤160 chars):**
Tamper-evident audit logs, sealed compliance reports, and paid lot verification for AI agents. MCP + x402 (USDC on Base). Free tier, no sales call.

**Long description:**
Privi gives AI agents the trust layer they need to do real work for companies and governments. Privi Ledger records every agent action in a hash-linked stream, issues sealed PDF compliance reports, produces OMB M-25-21 AI use-case inventories and EO 14409 post-quantum migration plans, and lets two companies seal a shared record with Privi Handshake. Privi Verify checks manufacturing lot provenance and chain of custody, paid per call with x402. Privi Anchor timestamps any hash on the Privi chain so proofs don't depend on trusting us. Everything is callable over MCP; paid tools settle in USDC on Base; the free tier is self-serve via `ledger_signup`. Built by Dario Canoy, Privi World Co, Port Huron, Michigan.

**Endpoints:**
- Ledger `https://privi-ledger.onrender.com/mcp` (streamable-http)
- Verify `https://privi-verify.onrender.com/mcp`
- Anchor `https://privi-anchor.onrender.com/mcp`
- Hub / docs `https://privi-discovery.onrender.com`
- Repo `https://github.com/canoydario847-cloud/Privi-Network`

**Categories/tags:** Security & Compliance, Blockchain, Developer Tools, Finance, Supply Chain · `audit-log` `compliance` `x402` `usdc` `base` `proof-of-existence` `supply-chain` `government` `a2a`

## 1. Smithery (biggest MCP directory; agents search it directly)
https://smithery.ai → Sign in with GitHub → Add server → "Remote server" → paste each endpoint URL. Use the short description. Three entries.

## 2. PulseMCP
https://www.pulsemcp.com/submit → one form per server; link the repo subfolder and the hub.

## 3. Glama
https://glama.ai/mcp/servers → "Claim" each listing with your GitHub (they already crawl the repo; `glama.json` is in place). Claimed servers rank higher.

## 4. mcp.so
https://mcp.so → Submit → repo URL + hub URL. One submission covers the repo.

## 5. Cursor directory + Cline marketplace
https://cursor.directory/mcp → Submit. https://github.com/cline/mcp-marketplace → "New issue → Server submission" with the repo URL and a 400×400 logo (use `https://privi-discovery.onrender.com/icon.svg`, exported to PNG).

## 6. Search engines (drives every RAG/browse agent)
- Bing Webmaster: https://www.bing.com/webmasters → Add site → URL `https://privi-discovery.onrender.com` → verify by meta tag (I'll add it to the hub if you paste it) → Sitemaps → submit `/sitemap.xml`.
- Google Search Console: https://search.google.com/search-console → same flow → submit `/sitemap.xml`.

## 7. x402 ecosystem (paying agents)
- Coinbase x402 Bazaar / ecosystem page: https://www.x402.org/ecosystem → "Add your project" PR or form → list Privi Verify and Privi Ledger as sellers with the Ledger pricing.

## 8. GitHub repo settings (2 minutes, you only)
Repo → About (gear icon) → Website: `https://privi-discovery.onrender.com` → Topics: `mcp-server mcp ai-agents x402 a2a audit-log blockchain usdc base compliance supply-chain llms-txt`.

## 9. Your own domain (biggest trust multiplier)
Attach `agents.priviflow.us` to the `privi-discovery` Railway service, set `PUBLIC_BASE_URL` to it, then redo 6 and update the three `server.json` `websiteUrl` fields. I can do all of that the moment you say the word.

## 10. Social bios
LinkedIn, X, TikTok, Instagram: link → the hub (or `agents.priviflow.us`). Agents that resolve "Dario Canoy" via social crawls will land on the card.
