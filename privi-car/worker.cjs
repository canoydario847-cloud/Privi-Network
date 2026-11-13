'use strict';
const crypto = require('node:crypto');
const MAX_BYTES = 65536;
function verifyJob(job, policy, seen, now = Date.now()) {
  if (!job || typeof job !== 'object' || Array.isArray(job)) throw Error('invalid job');
  if (!policy || policy.ownerOptIn !== true || policy.parked !== true || policy.externalPower !== true || policy.thermalSafe !== true) throw Error('worker disabled');
  if (typeof job.tenant !== 'string' || job.tenant !== policy.tenant || !/^[a-zA-Z0-9_-]{1,64}$/.test(job.tenant)) throw Error('tenant mismatch');
  if (typeof job.nonce !== 'string' || !/^[a-f0-9]{32}$/.test(job.nonce)) throw Error('invalid nonce');
  if (!Number.isSafeInteger(job.expiresAt) || job.expiresAt < now || job.expiresAt > now + 60000) throw Error('invalid expiry');
  if (typeof job.payload !== 'string' || Buffer.byteLength(job.payload, 'utf8') > MAX_BYTES) throw Error('invalid payload');
  if (!seen || typeof seen.has !== 'function' || typeof seen.add !== 'function') throw Error('invalid replay store');
  const id = job.tenant + ':' + job.nonce;
  if (seen.has(id)) throw Error('replay');
  // Prototype: no remote authentication; do not expose as a network endpoint.
  seen.add(id);
  const digest = crypto.createHash('sha256').update(job.payload).digest('hex');
  return Object.freeze({status:'simulated', tenant:job.tenant, nonce:job.nonce, digest, credits:0});
}
module.exports = {verifyJob};
