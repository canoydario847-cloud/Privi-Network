# Privi Discovery Hub

One tiny service that makes **Dario Canoy / Privi World Co** discoverable by every kind of AI agent — A2A agents, MCP clients, LLM crawlers, search engines — from a single `manifest.json`.

No dependencies. Python 3.10+ standard library only. Lives in `Privi-Network/discovery/`.

## What it serves

| Path | Who reads it |
|---|---|
| `/.well-known/agent.json` (+ `agent-card.json`) | A2A agents — Agent Card listing your 3 MCP servers as skills plus a "Contact Dario Canoy" skill |
| `/.well-known/mcp.json` | MCP clients — all Privi MCP endpoints, pricing, auth, tool names |
| `/.well-known/ai-plugin.json` | legacy plugin crawlers |
| `/llms.txt`, `/llms-full.txt` | LLM crawlers (Claude, GPT, Perplexity, etc.) |
| `/` | humans + schema.org JSON-LD (`Organization`, `Person`, 3× `SoftwareApplication`) |
| `/robots.txt`, `/sitemap.xml` | 22 AI/search bots explicitly allowed |
| `/manifest.json`, `/openapi.json`, `/humans.txt`, `/icon.svg`, `/health` | everything else |

Every response carries `Access-Control-Allow-Origin: *` and an `X-Agent-Card` header pointing to the card.

## Run locally

```bash
PUBLIC_BASE_URL=http://localhost:8080 CONTACT_EMAIL=you@priviflow.us python app.py
```

## Deploy on Railway (same project as Verify / Ledger / Anchor)

1. Commit this folder to `canoydario847-cloud/Privi-Network` as `discovery/`.
2. Railway → project "Privi Verify MCP" → **New service → GitHub repo → Privi-Network**, set **Root Directory** to `discovery`.
3. Variables: `PUBLIC_BASE_URL=https://<your-domain>` and `CONTACT_EMAIL=<the inbox you want agents to use>`.
4. Generate a domain (or attach a custom one — `agents.priviflow.us` would read well). Set `PUBLIC_BASE_URL` to it and redeploy.
5. Check `https://<domain>/.well-known/agent.json` and `/llms.txt`.

`PUBLIC_BASE_URL` is the only thing that changes between environments; every URL in every file is derived from it.

## Make agents actually find it — registration checklist

Hosting the files is half of it. Agents find you through registries and crawlers, so do these once:

**Already done**
- [x] MCP Registry: `privi-ledger`, `privi-verify`, `privi-anchor` are listed.

**Do next (≈1 hour, all free)**
- [ ] **Point your real domain at this** (`priviflow.us` root or `agents.priviflow.us`). Agent cards and llms.txt on a Railway subdomain carry less trust than on your own domain.
- [ ] **Add `homepage` to each MCP server's `server.json`** → `https://<domain>` and bump the version so the registry republishes with a link back here.
- [ ] **Submit each MCP server** to the community directories agents' tooling actually scrapes: Smithery, Glama, PulseMCP, mcp.so, Cursor directory, and the `awesome-mcp-servers` GitHub list (PR).
- [ ] **A2A**: add the card URL to the A2A community agent directories / `awesome-a2a` list.
- [ ] **Google Search Console + Bing Webmaster**: submit the sitemap. Bing feeds Copilot; Google feeds Gemini and most RAG crawlers.
- [ ] **GitHub**: put `https://<domain>/llms.txt` in the Privi-Network README and the repo "Website" field; add topics `mcp-server`, `a2a`, `x402`, `ai-agents`, `audit-log`.
- [ ] **x402 ecosystem**: list Verify and Ledger in the x402 "Bazaar"/discovery index so paying agents find them.
- [ ] **Cloudflare** (if you use it for DNS): turn **off** "Block AI bots" for this hostname — the default setting blocks the exact crawlers you want.
- [ ] **LinkedIn / X / TikTok bios**: link to `https://<domain>` so social-crawling agents resolve "Dario Canoy" to this card.

**Keep it alive**
- Edit `manifest.json` whenever you ship a tool or change a price. Nothing else needs touching.
- The `ask_of_agents` paragraph is your pitch to agents. Tune it like ad copy — it's what an agent reads when deciding whether to call Privi.
