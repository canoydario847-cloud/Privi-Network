'use strict';
// Research-only, dependency-free admission guard. Not wired to production.
const { createHmac, timingSafeEqual } = require('node:crypto');
const MAX_SKEW_MS = 60_000;
const MAX_BODY_BYTES = 1_048_576;
const MAX_NONCES = 10_000;
function validateToken(v, name) {
  if (typeof v !== 'string' || !/^[A-Za-z0-9_-]{1,128}$/.test(v)) throw new Error('invalid ' + name);
  return v;
}
function canonical({ tenant, agent, nonce, timestamp, bodyHash }) {
  [tenant, agent, nonce].forEach((v,i)=>validateToken(v,['tenant','agent','nonce'][i]));
  if (!Number.isSafeInteger(timestamp) || timestamp < 0) throw new Error('invalid timestamp');
  if (typeof bodyHash !== 'string' || !/^[a-f0-9]{64}$/.test(bodyHash)) throw new Error('invalid body hash');
  return ['privi-wall-v1', tenant, agent, nonce, String(timestamp), bodyHash].join('\n');
}
function sign(key, request) {
  if (!Buffer.isBuffer(key) || key.length < 32) throw new Error('key must be >=32 bytes');
  return createHmac('sha256', key).update(canonical(request)).digest('hex');
}
function createGuard({ getKey, now = Date.now, maxCalls = 100, windowMs = 60_000 } = {}) {
  if (typeof getKey !== 'function' || typeof now !== 'function') throw new Error('getKey and now required');
  if (!Number.isSafeInteger(maxCalls) || maxCalls < 1 || !Number.isSafeInteger(windowMs) || windowMs < 1) throw new Error('invalid limits');
  const seen = new Map(), budgets = new Map();
  return function admit(req) {
    try {
      if (!req || typeof req !== 'object') return { ok:false, reason:'malformed' };
      const clock = now();
      if (!Number.isSafeInteger(clock) || !Number.isSafeInteger(req.timestamp) || Math.abs(clock - req.timestamp) > MAX_SKEW_MS) return {ok:false,reason:'expired'};
      const payload = canonical(req);
      if (!Number.isSafeInteger(req.bodyBytes) || req.bodyBytes < 0 || req.bodyBytes > MAX_BODY_BYTES) return {ok:false,reason:'body-size'};
      const key = getKey(req.tenant, req.agent);
      if (!Buffer.isBuffer(key) || key.length < 32 || typeof req.signature !== 'string' || !/^[a-f0-9]{64}$/.test(req.signature)) return {ok:false,reason:'unauthorized'};
      const expected = createHmac('sha256',key).update(payload).digest();
      if (!timingSafeEqual(expected, Buffer.from(req.signature,'hex'))) return {ok:false,reason:'unauthorized'};
      // Prune before insertion; fail closed if replay cache is at capacity.
      for (const [k, expiry] of seen) if (expiry <= clock) seen.delete(k);
      const replayKey = req.tenant + '\0' + req.agent + '\0' + req.nonce;
      if (seen.has(replayKey)) return {ok:false,reason:'replay'};
      if (seen.size >= MAX_NONCES) return {ok:false,reason:'capacity'};
      const budgetKey = req.tenant + '\0' + req.agent;
      const old = budgets.get(budgetKey);
      const bucket = !old || clock >= old.until ? { count:0, until:clock + windowMs } : old;
      if (bucket.count >= maxCalls) return {ok:false,reason:'rate-limit'};
      bucket.count++;
      budgets.set(budgetKey,bucket);
      seen.set(replayKey, clock + MAX_SKEW_MS * 2);
      return {ok:true};
    } catch (_) { return {ok:false,reason:'malformed'}; }
  };
}
module.exports = { canonical, sign, createGuard };
