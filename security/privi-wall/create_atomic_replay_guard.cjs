'use strict';
// Privi Wall: replay admission must be called only AFTER signature and trusted-context verification.
// The store must atomically reserve a key once with expiry (e.g. Redis SET key 1 NX PX ttl).
const { createHash } = require('node:crypto');
const IDENT = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
function canonical(value, label) {
  if (typeof value !== 'string' || !IDENT.test(value)) throw new TypeError('invalid ' + label);
  return value;
}
function createAtomicReplayGuard({ reserveOnce, clock = Date.now, maxWindowMs = 300000 }) {
  if (typeof reserveOnce !== 'function' || typeof clock !== 'function' ||
      !Number.isSafeInteger(maxWindowMs) || maxWindowMs < 1000 || maxWindowMs > 3600000) {
    throw new TypeError('invalid replay guard configuration');
  }
  return async function admitVerifiedCall(claims) {
    if (!claims || Object.getPrototypeOf(claims) !== Object.prototype ||
        Object.getOwnPropertySymbols(claims).length) throw new TypeError('invalid claims');
    const fields = ['tenantId', 'agentId', 'sessionId', 'nonce'];
    const values = fields.map(k => {
      const d = Object.getOwnPropertyDescriptor(claims, k);
      if (!d || !Object.hasOwn(d, k) || !('value' in d)) throw new TypeError('invalid ' + k);
      return canonical(d.value, k);
    });
    const issued = Object.getOwnPropertyDescriptor(claims, 'issuedAtMs');
    if (!issued || !('value' in issued) || !Number.isSafeInteger(issued.value)) {
      throw new TypeError('invalid timestamp');
    }
    const now = clock();
    if (!Number.isSafeInteger(now) || issued.value > now + 5000 ||
        issued.value < now - maxWindowMs) return false;
    // Length-prefix every field to prevent concatenation ambiguities.
    const material = values.map(v => v.length + ':' + v).join('|');
    const key = 'privi-wall:replay:v1:' + createHash('sha256').update(material).digest('hex');
    // Retain the nonce across the entire permitted acceptance window, including clock skew.
    const ttlMs = maxWindowMs + 5000;
    try {
      return (await reserveOnce(key, ttlMs)) === true;
    } catch {
      return false; // Storage failure must not authorize execution.
    }
  };
}
module.exports = { createAtomicReplayGuard };
