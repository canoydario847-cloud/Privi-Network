"use strict";
// HMAC-SHA256 request integrity for Privi website -> private Mr. Lee gateway.
// Signed request binds HTTP method, route, site, pseudonymous user, timestamp,
// nonce and exact request body. Shared key NEVER leaves server-side secret stores.
// In-memory nonce storage works only for one private gateway process;
// production multi-replica deployments MUST use a shared atomic replay store.
const { createHmac, createHash, randomBytes, timingSafeEqual } = require("node:crypto");
const MAX_AGE_MS = 60_000;
const MAX_NONCES = 10_000;
const ROUTES = new Set(["/internal/mr-lee/chat", "/internal/mr-lee/paper-trade"]);
const UID = /^[A-Za-z0-9_.:-]{8,128}$/;
const NONCE = /^[a-f0-9]{32}$/;
const SIG = /^[a-f0-9]{64}$/;

function requireKey(secret) {
  if (typeof secret !== "string" || Buffer.byteLength(secret, "utf8") < 32) {
    throw Error("256-bit-or-better backend HMAC secret is required");
  }
}
function sha256(data) { return createHash("sha256").update(data).digest("hex"); }
function canonical({ method, route, origin, userId, timestamp, nonce, body }) {
  if (method !== "POST" || !ROUTES.has(route) || typeof origin !== "string"
      || !UID.test(userId) || typeof timestamp !== "string"
      || !/^[0-9]{13}$/.test(timestamp) || !NONCE.test(nonce)
      || typeof body !== "string" || Buffer.byteLength(body) > 4096) {
    throw Error("Invalid signed request fields");
  }
  return ["privi-mr-lee-v1", method, route, origin, userId, timestamp, nonce,
    sha256(Buffer.from(body, "utf8"))].join("\n");
}
function sign(secret, params) {
  requireKey(secret);
  return createHmac("sha256", secret).update(canonical(params)).digest("hex");
}
function signedHeaders(secret, { route, origin, userId, body, now = Date.now(), nonce = randomBytes(16).toString("hex") }) {
  const timestamp = String(now);
  const signature = sign(secret, { method: "POST", route, origin, userId, body, timestamp, nonce });
  return {
    "X-Privi-Website-Origin": origin,
    "X-Privi-User-Id": userId,
    "X-Privi-Timestamp": timestamp,
    "X-Privi-Nonce": nonce,
    "X-Privi-Signature": "v1=" + signature
  };
}
class NonceCache {
  constructor() { this.entries = new Map(); }
  claim(nonce, now) {
    for (const [key, expiry] of this.entries) {
      if (expiry < now) this.entries.delete(key);
    }
    if (this.entries.has(nonce) || this.entries.size >= MAX_NONCES) return false;
    this.entries.set(nonce, now + MAX_AGE_MS);
    return true;
  }
}
function verifyRequest({ key, headers, route, rawBody, allowedOrigins, replayCache, now = Date.now() }) {
  try {
    requireKey(key);
    if (!replayCache || typeof replayCache.claim !== "function"
        || !allowedOrigins || typeof allowedOrigins.has !== "function"
        || headers.origin || headers.cookie || headers["x-forwarded-authorization"]) return false;
    const origin = headers["x-privi-website-origin"];
    const userId = headers["x-privi-user-id"];
    const timestamp = headers["x-privi-timestamp"];
    const nonce = headers["x-privi-nonce"];
    const signed = headers["x-privi-signature"];
    if (!allowedOrigins.has(origin) || typeof signed !== "string"
        || !signed.startsWith("v1=") || !SIG.test(signed.slice(3))
        || !/^[0-9]{13}$/.test(timestamp || "")
        || Math.abs(now - Number(timestamp)) > MAX_AGE_MS) return false;
    const expected = sign(key, {
      method: "POST", route, origin, userId, timestamp, nonce, body: rawBody
    });
    const a = Buffer.from(expected, "ascii"), b = Buffer.from(signed.slice(3), "ascii");
    if (a.length !== b.length || !timingSafeEqual(a, b)) return false;
    return replayCache.claim(nonce, now); // reserve nonce only on authentic request
  } catch { return false; }
}
function containsCredentialLikeText(value) {
  if (typeof value !== "string") return true;
  // Only high confidence checks; provider-side moderation and downstream
  // DLP are STILL required. False negatives are possible.
  return /(?:sk-(?:proj|svcacct|[A-Za-z0-9])[-A-Za-z0-9_]{16,}|-----BEGIN (?:RSA |EC |OPENSSH |)PRIVATE KEY-----|(?:seed phrase|recovery phrase|mnemonic)\s*:\s*[A-Za-z]+(?:\s+[A-Za-z]+){9,}|(?:password|api[_ -]?key|private[_ -]?key)\s*[:=]\s*\S{8,})/i.test(value);
}
module.exports = {
  MAX_AGE_MS, MAX_NONCES, ROUTES, UID, NonceCache,
  signedHeaders, verifyRequest, containsCredentialLikeText, sha256
};
