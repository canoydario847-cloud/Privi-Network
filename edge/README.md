# Privi Edge (global entry point)

One Cloudflare Worker in front of every Privi MCP server. Agents in Tokyo, Lagos, Nairobi, Johannesburg,
São Paulo, Mumbai or anywhere else connect to the nearest of Cloudflare's 300+ cities; the Worker forwards to
the Privi server over Cloudflare's network. Nothing is stored at the edge: Ledger and Anchor keep one source of
truth on Render, and every response, signature and x402 payment is exactly what the origin produced.

| Edge URL | Origin |
|---|---|
| `https://ledger.privishine.info/mcp` | `https://privi-ledger.onrender.com/mcp` |
| `https://quantum.privishine.info/mcp` | `https://privi-quantum.onrender.com/mcp` |
| `https://verify.privishine.info/mcp` | `https://privi-verify.onrender.com/mcp` |
| `https://anchor.privishine.info/mcp` | `https://privi-anchor.onrender.com/mcp` |
| `https://call.privishine.info/mcp` | `https://privi-call.onrender.com/mcp` |
| `https://hub.privishine.info` | `https://privi-discovery.onrender.com` |

The path form also works on any of them or the `workers.dev` URL: `/ledger/mcp`, `/quantum/mcp`, and so on.
`GET /edge` shows which Cloudflare city served you.

What the Worker does:
- streams MCP (streamable HTTP and SSE) and passes WebSockets (Dream Scape) straight through;
- sends the caller's real IP as `X-Forwarded-For`, so per-client rate limits and audit logs stay correct;
- caches only public read-only pages for 2 minutes (`/benchmarks`, `/keys`, `/leaderboard`, `/llms.txt`,
  `/.well-known/*`); MCP calls, payments and writes are never cached;
- rewrites origin redirects to the edge hostname and adds `X-Privi-Edge: <city code>`.

## Deploy (Cloudflare dashboard, about 3 minutes)

1. Workers & Pages → Create → Worker → name it `privi-edge` → Deploy.
2. Edit code → replace everything with `worker.js` → Deploy.
3. Settings → Domains & Routes → Add → Custom domain → add each hostname in the table above
   (`privishine.info` must be on the same Cloudflare account).

Or with Wrangler: `cd edge && npx wrangler deploy` (uses `wrangler.toml`).

Free plan: 100,000 requests per day. Workers Paid ($5/month) lifts that to 10 million per month.
