"use strict";
const http = require("node:http");
const { getConfig, authorize, checkPriviNetwork, askMrLee } = require("./core");
const { simulatePaperTrade } = require("./paper-trade");

// Deploy behind the AUTHENTICATED Privi website's server-side proxy only.
// Never expose this private gateway directly to browsers or the public web.
const config = getConfig();
const MAX_BODY = 4096;
const RATE_WINDOW_MS = 60_000;
const MAX_PER_WINDOW = 8;
const windows = new Map();

function json(res, status, data) {
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'",
    "Referrer-Policy": "no-referrer"
  });
  res.end(JSON.stringify(data));
}

function throttle(identity, now = Date.now()) {
  if (windows.size > 10000) {
    for (const [k, v] of windows) {
      if (now - v.start >= RATE_WINDOW_MS) windows.delete(k);
    }
    if (windows.size > 10000) return true; // bound growth, deny excess
  }
  const entry = windows.get(identity);
  if (!entry || now - entry.start >= RATE_WINDOW_MS) {
    windows.set(identity, { start: now, count: 1 });
    return false;
  }
  entry.count++;
  return entry.count > MAX_PER_WINDOW;
}

async function readBody(req) {
  if (req.headers["content-type"]?.split(";")[0].trim() !== "application/json") {
    throw Error("JSON body required");
  }
  const declared = Number(req.headers["content-length"] || 0);
  if (!Number.isSafeInteger(declared) || declared > MAX_BODY || declared < 0) {
    throw Error("Request body too large");
  }
  let size = 0, chunks = [];
  for await (const chunk of req) {
    size += chunk.length;
    if (size > MAX_BODY) throw Error("Request body too large");
    chunks.push(chunk);
  }
  const data = JSON.parse(Buffer.concat(chunks).toString("utf8"));
  if (!data || Array.isArray(data) || typeof data !== "object") throw Error("JSON object required");
  return data;
}

async function handler(req, res) {
  if (req.method === "GET" && req.url === "/health") {
    return json(res, 200, { name: "Mr. Lee", enabled: config.enabled,
      mode: "private-Privi-website-gateway", live_trading: false });
  }
  if (req.method !== "POST" ||
      !["/internal/mr-lee/chat", "/internal/mr-lee/paper-trade"].includes(req.url)) {
    return json(res, 404, { error: "not_found" });
  }
  if (!config.enabled) return json(res, 503, { error: "mr_lee_not_activated" });
  if (!authorize(config, req.headers)) return json(res, 403, { error: "website_authorization_required" });
  const userId = req.headers["x-privi-user-id"];
  if (typeof userId !== "string" || !/^[A-Za-z0-9_.:-]{8,128}$/.test(userId)) {
    return json(res, 403, { error: "authenticated_user_required" });
  }
  if (throttle(userId)) return json(res, 429, { error: "rate_limited" });
  let payload;
  try { payload = await readBody(req); }
  catch { return json(res, 400, { error: "invalid_request" }); }

  const network = await checkPriviNetwork(config);
  if (!network.ok) return json(res, 503, { error: "approved_privi_network_not_verified" });
  if (req.url === "/internal/mr-lee/paper-trade") {
    try { return json(res, 200, simulatePaperTrade(payload)); }
    catch { return json(res, 422, { error: "invalid_paper_trade_scenario" }); }
  }
  if (typeof payload.message !== "string" || payload.message.length < 1 ||
      payload.message.length > 1500 || !["utility","network","markets","support"].includes(payload.category)) {
    return json(res, 422, { error: "invalid_message" });
  }
  try {
    const answer = await askMrLee(config, payload.message, payload.category, network);
    return json(res, 200, { name: "Mr. Lee", category: payload.category,
      reply: answer, verified_chain_id: network.chainId,
      mode: "read_only", trading: "simulation_only" });
  } catch {
    // Deliberately do not log model response bodies, prompts or credentials.
    return json(res, 502, { error: "assistant_temporarily_unavailable" });
  }
}

if (require.main === module) {
  const port = Number(process.env.PORT || 8091);
  const host = process.env.MR_LEE_BIND_HOST || "127.0.0.1";
  if (!Number.isSafeInteger(port) || port < 1 || port > 65535) throw Error("Invalid PORT");
  const server = http.createServer((req, res) => {
    handler(req, res).catch(() => json(res, 503, { error: "service_unavailable" }));
  });
  server.requestTimeout = 30_000;
  server.headersTimeout = 10_000;
  server.listen(port, host, () => console.log("Mr. Lee private gateway started; enabled=" + config.enabled));
}

module.exports = { handler, json, throttle, readBody };
