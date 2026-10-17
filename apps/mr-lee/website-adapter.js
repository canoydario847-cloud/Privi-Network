"use strict";
// Authenticated Privi website server ONLY. Never run this code in a browser.
// The site's trusted identity provider must validate an MFA-backed session,
// expirations, logout/revocation and a per-session anti-CSRF token.
const { signedHeaders } = require("./security");

const SESSION_MAX_AGE_MS = 12 * 60 * 60 * 1000;
function securityHeaders() {
  return {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store, max-age=0",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'none'"
  };
}
function respond(status, error) {
  return new Response(JSON.stringify({ error }), {
    status, headers: securityHeaders()
  });
}
function makeMrLeeWebsiteHandler({
  getAuthenticatedSession, verifyCsrf, fetchImpl = globalThis.fetch,
  env = process.env, now = Date.now
}) {
  if (typeof getAuthenticatedSession !== "function"
      || typeof verifyCsrf !== "function") {
    throw Error("Privi website MUST supply trusted MFA session and CSRF verifiers");
  }
  const origin = env.MR_LEE_WEBSITE_ORIGIN;
  const gateway = env.MR_LEE_PRIVATE_GATEWAY_URL;
  const secret = env.MR_LEE_GATEWAY_TOKEN;
  let originUrl, gatewayUrl;
  try { originUrl = new URL(origin); gatewayUrl = new URL(gateway); }
  catch { throw Error("Privi requires exact HTTPS server-side origins"); }
  if (originUrl.protocol !== "https:" || originUrl.origin !== origin
      || originUrl.username || originUrl.password || originUrl.hostname === "localhost"
      || gatewayUrl.protocol !== "https:" || gatewayUrl.origin !== gateway
      || gatewayUrl.username || gatewayUrl.password || !gatewayUrl.hostname) {
    throw Error("Only fixed official HTTPS Privi website and private gateway origins allowed");
  }
  if (typeof secret !== "string" || Buffer.byteLength(secret) < 32) {
    throw Error("Private HMAC key must be stored in website and gateway secret vaults");
  }
  return async function handle(request) {
    if (request.method !== "POST") return respond(405, "method_not_allowed");
    const url = new URL(request.url);
    const route = url.pathname;
    if (url.origin !== origin || url.search || url.hash ||
        !["/api/mr-lee/chat", "/api/mr-lee/paper-trade"].includes(route)) {
      return respond(404, "not_found");
    }
    if (request.headers.get("origin") !== origin
        || request.headers.get("sec-fetch-site") !== "same-origin"
        || request.headers.get("content-type")?.split(";")[0].trim() !== "application/json") {
      return respond(403, "website_origin_or_format_rejected");
    }
    let session, csrfOk;
    try {
      session = await getAuthenticatedSession(request);
      csrfOk = session ? await verifyCsrf(request, session) : false;
    } catch { return respond(403, "website_authentication_failed"); }
    const current = now();
    if (!session || !/^[A-Za-z0-9_.:-]{8,128}$/.test(session.userId || "")
        || session.mfaVerified !== true || session.active !== true
        || !Number.isSafeInteger(session.authTimeMs)
        || current - session.authTimeMs < 0
        || current - session.authTimeMs > SESSION_MAX_AGE_MS
        || csrfOk !== true) {
      return respond(403, "mfa_session_and_csrf_required");
    }
    // Cookies must be Secure/HttpOnly/SameSite; these live on the website, NOT Mr Lee.
    // For multi-tenant sites: userId must be an opaque site-scoped pseudonym.
    if (request.headers.get("content-length")
        && (!/^[0-9]+$/.test(request.headers.get("content-length"))
            || Number(request.headers.get("content-length")) > 4096)) {
      return respond(413, "too_large");
    }
    let raw;
    try { raw = await request.text(); }
    catch { return respond(400, "invalid_json"); }
    if (Buffer.byteLength(raw, "utf8") > 4096) return respond(413, "too_large");
    try {
      const obj = JSON.parse(raw);
      if (!obj || typeof obj !== "object" || Array.isArray(obj)) {
        return respond(400, "invalid_json");
      }
    } catch { return respond(400, "invalid_json"); }
    const endpoint = route.endsWith("/paper-trade")
      ? "/internal/mr-lee/paper-trade" : "/internal/mr-lee/chat";
    const headers = signedHeaders(secret, {
      route: endpoint, origin, userId: session.userId, body: raw, now: current
    });
    try {
      const result = await fetchImpl(gateway + endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...headers },
        body: raw, signal: AbortSignal.timeout(28000)
      });
      const body = await result.text();
      if (body.length > 16000 || !/^\s*\{/.test(body)) {
        return respond(502, "invalid_private_gateway_response");
      }
      return new Response(body, { status: result.status, headers: securityHeaders() });
    } catch { return respond(503, "mr_lee_unavailable"); }
  };
}
module.exports = { makeMrLeeWebsiteHandler, securityHeaders, SESSION_MAX_AGE_MS };
