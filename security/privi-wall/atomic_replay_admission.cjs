'use strict';
// Shared-store replay admission interface. Not an RFC 9421 verifier.
// reserve(key, ttlMs) MUST atomically create only if absent across all nodes,
// and return true only on successful insertion. Never use get-then-set.
// Storage failures and ambiguous results deny. Call only AFTER signature,
// authenticated tenant, and expiration verification.
const {createHash} = require('node:crypto');
async function admitSignedAgentNonce({tenant, nonce, expiresAt, reserve, clock = Date.now, maxLifetimeMs = 60000}) {
  if (typeof tenant !== 'string' || !/^[A-Za-z0-9_-]{1,64}$/.test(tenant) ||
      typeof nonce !== 'string' || !/^[a-f0-9]{32,64}$/.test(nonce) ||
      typeof reserve !== 'function' || typeof clock !== 'function' ||
      !Number.isSafeInteger(maxLifetimeMs) || maxLifetimeMs < 1) return false;
  try {
    const now = clock();
    if (!Number.isSafeInteger(now) || !Number.isSafeInteger(expiresAt) ||
        expiresAt <= now || expiresAt - now > maxLifetimeMs) return false;
    const key = 'privi-wall:replay:v1:' + createHash('sha256')
      .update(JSON.stringify([tenant, nonce])).digest('hex');
    // Store TTL must not be shorter than remaining validity; never round down.
    return (await reserve(key, expiresAt - now)) === true;
  } catch (_) { return false; }
}
module.exports = {admitSignedAgentNonce};
