"use strict";

// Website-side integration seam. Must run INSIDE the authenticated Privi
// website server (NOT inside browser JavaScript / IONOS HTML widgets).
// The website supplies its REAL existing session validation and CSRF checks.
const { randomUUID } = require("node:crypto");

function makeMrLeeWebsiteHandler({ getAuthenticatedSession, fetchImpl = globalThis.fetch, env = process.env }) {
  if (typeof getAuthenticatedSession !== "function") {
    throw Error("Website must provide a real server-side session verifier");
  }
  const origin = env.MR_LEE_WEBSITE_ORIGIN;
  const gateway = env.MR_LEE_PRIVATE_GATEWAY_URL;
  const token = env.MR_LEE_GATEWAY_TOKEN;
  if (typeof origin !== "string" || !origin.startsWith("https://")
      || new URL(origin).origin !== origin) {
    throw Error("Mr. Lee requires exact official HTTPS website origin");
  }
  if (typeof gateway !== "string" || !/^https:\/\/[^/?#]+$/.test(gateway)) {
    throw Error("Mr. Lee requires dedicated private HTTPS API gateway");
  }
  if (!token || token.length < 32) throw Error("Missing server-to-server secret");
  return async function handle(request) {
    if (request.method !== "POST") {
      return new Response(JSON.stringify({ error: "method_not_allowed" }), { status: 405 });
    }
    // Exact browser Origin + Fetch Metadata helps defend session-cookie CSRF.
    // Authentication is ALWAYS checked independently by the real site session.
    if (request.headers.get("origin") !== origin
        || request.headers.get("sec-fetch-site") === "cross-site") {
      return new Response(JSON.stringify({ error: "wrong_website_origin" }), { status: 403 });
    }
    const session = await getAuthenticatedSession(request);
    if (!session || typeof session.userId !== "string"
        || !/^[A-Za-z0-9_.:-]{8,128}$/.test(session.userId)) {
      return new Response(JSON.stringify({ error: "login_required" }), { status: 401 });
    }
    const route = new URL(request.url).pathname;
    if (route !== "/api/mr-lee/chat" && route !== "/api/mr-lee/paper-trade") {
      return new Response(JSON.stringify({ error: "not_found" }), { status: 404 });
    }
    const raw = await request.text();
    if (Buffer.byteLength(raw) > 4096) {
      return new Response(JSON.stringify({ error: "too_large" }), { status: 413 });
    }
    // Only forward fixed trusted route. The browser CANNOT choose the
    // private gateway address, model, API key, Privi RPC, or deployment.
    const endpoint = route.endsWith("/paper-trade")
      ? "/internal/mr-lee/paper-trade" : "/internal/mr-lee/chat";
    try {
      const result = await fetchImpl(gateway + endpoint, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": "Bearer " + token,
          "X-Privi-Website-Origin": origin,
          "X-Privi-User-Id": session.userId,
          "X-Request-Id": randomUUID()
        },
        body: raw, signal: AbortSignal.timeout(28000)
      });
      const body = await result.text();
      return new Response(body.slice(0, 16000), {
        status: result.status,
        headers: {
          "Content-Type": "application/json; charset=utf-8",
          "Cache-Control": "no-store",
          "X-Content-Type-Options": "nosniff"
        }
      });
    } catch {
      return new Response(JSON.stringify({ error: "mr_lee_unavailable" }), { status: 503 });
    }
  };
}
module.exports = { makeMrLeeWebsiteHandler };
