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

// Always-on fallback for the Discovery Hub. The live hub runs on Render's free plan and sleeps when idle,
// so cold starts answer 503. sites/hub/discovery-mirror/ (exported by discovery/export_static.py) is served
// by the always-on privi-hub static site; the edge serves it whenever the live hub is down.
const HUB_MIRROR = "https://privi-hub.onrender.com/discovery-mirror";
const HUB_PUBLIC = "https://privi-discovery.onrender.com";

// Every AI crawler and agent is welcome. Served at the edge so a sleeping origin never blocks discovery.
const AI_BOTS = ["GPTBot", "ChatGPT-User", "OAI-SearchBot", "ClaudeBot", "Claude-User", "Claude-SearchBot",
  "anthropic-ai", "PerplexityBot", "Perplexity-User", "Google-Extended", "Googlebot", "Bingbot", "Applebot",
  "Applebot-Extended", "Amazonbot", "CCBot", "cohere-ai", "DuckAssistBot", "meta-externalagent", "YouBot",
  "MistralAI-User"];

function robots(host) {
  const lines = ["User-agent: *", "Allow: /", ""];
  for (const b of AI_BOTS) lines.push(`User-agent: ${b}`, "Allow: /", "");
  lines.push(`Sitemap: ${HUB_PUBLIC}/sitemap.xml`, `# LLM summary: ${HUB_PUBLIC}/llms.txt`,
             `# Agent card: ${HUB_PUBLIC}/.well-known/agent.json`, `# MCP endpoint: https://${host}/mcp`);
  return new Response(lines.join("\n") + "\n", {
    headers: { "content-type": "text/plain; charset=utf-8", "cache-control": "public, max-age=3600",
               "access-control-allow-origin": "*" },
  });
}

// Discovery for a single MCP server (crawlers such as histor and mcp-icon-survey look for it).
function mcpWellKnown(name, host) {
  return new Response(JSON.stringify({
    name: `Privi ${name[0].toUpperCase()}${name.slice(1)}`, publisher: "Privi World Co",
    mcp: { url: `https://${host}/mcp`, transport: "streamable-http" },
    registry: `io.github.canoydario847-cloud/privi-${name}`,
    hub: `${HUB_PUBLIC}/.well-known/mcp.json`, llms: `${HUB_PUBLIC}/llms.txt`,
    agent_card: `${HUB_PUBLIC}/.well-known/agent.json`,
  }, null, 2), { headers: { "content-type": "application/json", "access-control-allow-origin": "*",
                            "cache-control": "public, max-age=600" } });
}

export function mirrorPath(path) {
  const p = path.replace(/\/+$/, "") || "/";
  if (p === "/") return "/index.html";
  if (p === "/health" || !/^\/[A-Za-z0-9._\-\/]+$/.test(p)) return null;
  return p.replace(/^\/\.well-known\//, "/well-known/");
}

async function hubFallback(path, why) {
  const mp = mirrorPath(path);
  if (!mp) return null;
  try {
    const r = await fetch(HUB_MIRROR + mp, { cf: { cacheEverything: true, cacheTtl: 300 } });
    if (!r.ok) return null;
    const type = mp.endsWith(".json") ? "application/json; charset=utf-8"
      : mp.endsWith(".html") ? "text/html; charset=utf-8" : mp.endsWith(".svg") ? "image/svg+xml"
      : mp.endsWith(".xml") ? "application/xml" : "text/plain; charset=utf-8";
    return new Response(r.body, { status: 200, headers: { "content-type": type, "access-control-allow-origin": "*",
      "cache-control": "public, max-age=60", "x-privi-edge-fallback": why } });
  } catch (e) {
    return null;
  }
}

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
    if (target.path === "/robots.txt") return robots(url.host);

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
      if (target.name === "hub" && isGet) {
        const fb = await hubFallback(target.path, "origin-unreachable");
        if (fb) return fb;
      }
      return new Response(JSON.stringify({ error: "Privi server unreachable from the edge", server: target.name,
                                           detail: String(e) }), { status: 502, headers: { "content-type": "application/json" } });
    }

    // Sleeping free-plan hub: answer from the always-on mirror instead of a 503.
    if (target.name === "hub" && isGet && res.status >= 500) {
      const fb = await hubFallback(target.path, `origin-${res.status}`);
      if (fb) return fb;
    }
    // MCP servers have no /.well-known/mcp.json of their own; describe them at the edge.
    if (target.name !== "hub" && isGet && res.status === 404 && target.path === "/.well-known/mcp.json") {
      return mcpWellKnown(target.name, url.host);
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
