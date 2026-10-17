"use strict";
const http = require("node:http");
const { getConfig, checkPriviNetwork, askMrLee } = require("./core");
const { simulatePaperTrade } = require("./paper-trade");
const { NonceCache, verifyRequest, containsCredentialLikeText, sha256 } = require("./security");

// The gateway MUST be reachable only through mTLS / private-network ingress,
// behind the authenticated Privi website. No public domain or wildcard CORS.
const config = getConfig();
const MAX_BODY = 4096;
const RATE_WINDOW_MS = 60_000;
const MAX_PER_WINDOW = 8;
const MAX_CONCURRENT_REQUESTS = 8;
const windows = new Map();
const nonces = new NonceCache();
let active = 0;

function json(res, status, data) {
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store, max-age=0",
    "Pragma": "no-cache",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'",
    "Referrer-Policy": "no-referrer"
  });
  res.end(JSON.stringify(data));
}

function throttle(identity, now = Date.now()) {
  // Hash pseudonymous identity before indexing memory. No chat content stored.
  const key = sha256(identity);
  if (windows.size >= 10000) {
    for (const [k, v] of windows) {
      if (now - v.start >= RATE_WINDOW_MS) windows.delete(k);
    }
    if (windows.size >= 10000 && !windows.has(key)) return true;
  }
  const entry = windows.get(key);
  if (!entry || now - entry.start >= RATE_WINDOW_MS) {
    windows.set(key, { start: now, count: 1 });
    return false;
  }
  entry.count++;
  return entry.count > MAX_PER_WINDOW;
}

async function readRawBody(req) {
  if (req.headers["content-type"]?.split(";")[0].trim() !== "application/json"
      || req.headers["content-encoding"]) {
    throw Error("JSON body required");
  }
  const rawLen = req.headers["content-length"];
  if (rawLen !== undefined
      && (!/^[0-9]+$/.test(rawLen) || Number(rawLen) > MAX_BODY)) {
    throw Error("Request body too large");
  }
  let size = 0;
  const chunks = [];
  for await (const chunk of req) {
    size += chunk.length;
    if (size > MAX_BODY) throw Error("Request body too large");
    chunks.push(chunk);
  }
  const bytes = Buffer.concat(chunks);
  const raw = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  return raw;
}

async function handler(req, res) {
  if (req.method === "GET" && req.url === "/internal/health") {
    return json(res, 200, { status: "ok" }); // never exposes activation/secrets
  }
  if (req.method !== "POST" ||
      !["/internal/mr-lee/chat", "/internal/mr-lee/paper-trade"].includes(req.url)) {
    return json(res, 404, { error: "not_found" });
  }
  if (!config.enabled) return json(res, 503, { error: "mr_lee_not_activated" });
  if (active >= MAX_CONCURRENT_REQUESTS) return json(res, 429, { error: "busy" });
  active++;
  try {
    let raw;
    try { raw = await readRawBody(req); }
    catch { return json(res, 400, { error: "invalid_request" }); }
    const allowed = verifyRequest({
      key: config.internalToken,
      headers: req.headers,
      route: req.url,
      rawBody: raw,
      allowedOrigins: config.allowedOrigins,
      replayCache: nonces
    });
    if (!allowed) return json(res, 403, { error: "signed_website_authentication_required" });
    const userId = req.headers["x-privi-user-id"];
    if (throttle(userId)) return json(res, 429, { error: "rate_limited" });
    let payload;
    try { payload = JSON.parse(raw); }
    catch { return json(res, 400, { error: "invalid_json" }); }
    if (!payload || Array.isArray(payload) || typeof payload !== "object") {
      return json(res, 400, { error: "invalid_json" });
    }
    if (JSON.stringify(payload).length > MAX_BODY
        || (req.url.endsWith("/chat") && containsCredentialLikeText(payload.message))) {
      return json(res, 422, { error: "unsafe_or_invalid_message" });
    }
    // ALWAYS verify Privi's production chain & block-zero fingerprint.
    const network = await checkPriviNetwork(config);
    if (!network.ok) return json(res, 503, { error: "approved_privi_network_not_verified" });
    if (req.url.endsWith("/paper-trade")) {
      try { return json(res, 200, simulatePaperTrade(payload)); }
      catch { return json(res, 422, { error: "invalid_paper_trade_scenario" }); }
    }
    if (typeof payload.message !== "string" || payload.message.length < 1 ||
        payload.message.length > 1500
        || !["utility", "network", "markets", "support"].includes(payload.category)) {
      return json(res, 422, { error: "invalid_message" });
    }
    try {
      const answer = await askMrLee(config, payload.message, payload.category, network);
      return json(res, 200, {
        name: "Mr. Lee", category: payload.category, reply: answer,
        verified_chain_id: network.chainId,
        mode: "read_only", trading: "simulation_only"
      });
    } catch {
      // Never log user messages, credentials, provider responses, or private RPC.
      return json(res, 502, { error: "assistant_temporarily_unavailable" });
    }
  } finally { active--; }
}

if (require.main === module) {
  const port = Number(process.env.PORT || 8091);
  const host = process.env.MR_LEE_BIND_HOST || "127.0.0.1";
  if (!Number.isSafeInteger(port) || port < 1 || port > 65535) throw Error("Invalid PORT");
  // Public listening requires a separately audited reverse proxy / mTLS boundary.
  if (!["127.0.0.1", "::1"].includes(host)) {
    throw Error("Mr. Lee gateway must bind to loopback only");
  }
  const server = http.createServer((req, res) => {
    handler(req, res).catch(() => json(res, 503, { error: "service_unavailable" }));
  });
  server.requestTimeout = 30_000;
  server.headersTimeout = 10_000;
  server.maxRequestsPerSocket = 50;
  server.listen(port, host, () => console.log("Mr. Lee private gateway initialized"));
}

module.exports = { handler, json, throttle, readRawBody, nonces };
