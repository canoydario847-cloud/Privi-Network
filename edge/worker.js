// Copyright (c) 2026 Privi World Co. All rights reserved.
// Privi Edge: one Cloudflare Worker in front of every Privi MCP server.
//
// Agents anywhere (Tokyo, Lagos, Nairobi, Johannesburg, Sao Paulo, Mumbai...) connect to the nearest of
// Cloudflare's 300+ cities; the Worker forwards to the Privi server over Cloudflare's network. Nothing is
// stored here: Ledger and Anchor keep one source of truth on Render, and every response, signature and
// x402 payment is exactly what the origin produced.
//
// Hostnames (attach each as a Custom Domain on this Worker):
//   ledger.privishine.info  -> privi-ledger.onrender.com
//   quantum.privishine.info -> privi-quantum.onrender.com
//   verify.privishine.info  -> privi-verify.onrender.com
//   anchor.privishine.info  -> privi-anchor.onrender.com
//   call.privishine.info    -> privi-call.onrender.com
//   hub.privishine.info     -> privi-discovery.onrender.com
// A path prefix also works on any of them or on the workers.dev URL: /ledger/mcp, /quantum/mcp, ...

const ORIGINS = {
  ledger: "https://privi-ledger.onrender.com",
  quantum: "https://privi-quantum.onrender.com",
  verify: "https://privi-verify.onrender.com",
  anchor: "https://privi-anchor.onrender.com",
  call: "https://privi-call.onrender.com",
  hub: "https://privi-discovery.onrender.com",
};

// Public, read-only pages that are safe to cache briefly at the edge (never MCP, payments or writes).
const CACHEABLE = [/^\/benchmarks(\.json)?$/, /^\/keys$/, /^\/leaderboard(\.json)?$/, /^\/llms\.txt$/,
                   /^\/\.well-known\//, /^\/icon\.svg$/, /^\/sitemap\.xml$/, /^\/robots\.txt$/];
const CACHE_SECONDS = 120;

// Hop-by-hop headers that must not be forwarded.
const HOP = ["connection", "keep-alive", "proxy-connection", "transfer-encoding", "upgrade", "te", "trailer"];

function pick(url) {
  const sub = url.hostname.split(".")[0];
  if (ORIGINS[sub]) return { origin: ORIGINS[sub], path: url.pathname, name: sub };
  const m = url.pathname.match(/^\/(ledger|quantum|verify|anchor|call|hub)(\/.*)?$/);
  if (m) return { origin: ORIGINS[m[1]], path: m[2] || "/", name: m[1] };
  return null;
}

function index(req) {
  const host = new URL(req.url).host;
  const servers = Object.keys(ORIGINS).map((k) => ({
    name: k, mcp: k === "hub" ? null : `https://${k}.privishine.info/mcp`, path_form: `https://${host}/${k}/mcp`,
    origin: ORIGINS[k],
  }));
  return new Response(JSON.stringify({
    service: "Privi Edge", about: "Global entry point for Privi's MCP servers, served from the nearest Cloudflare city.",
    you_are_served_from: req.cf ? req.cf.colo : null, servers,
  }, null, 2), { headers: { "content-type": "application/json", "access-control-allow-origin": "*" } });
}

export default {
  async fetch(req, env, ctx) {
    const url = new URL(req.url);
    const target = pick(url);
    if (!target) {
      if (url.pathname === "/" || url.pathname === "/edge") return index(req);
      return new Response("Not found. See / for the list of Privi servers.", { status: 404 });
    }
    if (url.pathname === "/edge" || target.path === "/edge") return index(req);

    const dest = new URL(target.path + url.search, target.origin);

    // WebSockets (Dream Scape) are passed straight through.
    if ((req.headers.get("upgrade") || "").toLowerCase() === "websocket") {
      return fetch(new Request(dest, req));
    }

    const headers = new Headers(req.headers);
    for (const h of HOP) headers.delete(h);
    headers.delete("host");
    // Keep the caller's real address so per-client rate limits and audit logs stay correct.
    const ip = req.headers.get("cf-connecting-ip");
    if (ip) headers.set("x-forwarded-for", ip);
    headers.set("x-forwarded-host", url.host);
    headers.set("x-forwarded-proto", "https");
    headers.set("x-privi-edge", (req.cf && req.cf.colo) || "edge");

    const isGet = req.method === "GET" || req.method === "HEAD";
    const cacheable = isGet && !req.headers.get("authorization") && CACHEABLE.some((re) => re.test(target.path));

    const init = {
      method: req.method, headers, redirect: "manual",
      body: isGet ? undefined : req.body,
      cf: cacheable ? { cacheEverything: true, cacheTtl: CACHE_SECONDS } : { cacheTtl: 0, cacheEverything: false },
    };
    if (!isGet) init.duplex = "half";

    let res;
    try {
      res = await fetch(dest, init);
    } catch (e) {
      return new Response(JSON.stringify({ error: "Privi server unreachable from the edge", server: target.name,
                                           detail: String(e) }), { status: 502, headers: { "content-type": "application/json" } });
    }

    // Stream the response back as-is (MCP streamable HTTP / SSE), adding where it was served.
    const out = new Headers(res.headers);
    for (const h of HOP) out.delete(h);
    out.set("x-privi-edge", (req.cf && req.cf.colo) || "edge");
    // Keep redirects on the edge hostname.
    const loc = out.get("location");
    if (loc && loc.startsWith(target.origin)) out.set("location", loc.slice(target.origin.length) || "/");
    if (!cacheable) out.set("cache-control", out.get("cache-control") || "no-store");
    return new Response(res.body, { status: res.status, statusText: res.statusText, headers: out });
  },
};
