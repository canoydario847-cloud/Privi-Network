'use strict';
// Fail-closed replay admission. consumeOnce must be atomic across all gateway replicas.
const {createHash}=require('node:crypto');
const {verifyFreshTenantReceipt}=require('./verify_fresh_tenant_receipt.cjs');
const ID=/^[A-Za-z0-9_-]{1,128}$/;
const NONCE=/^[a-f0-9]{32,128}$/;
async function verifyOnceTenantReceipt(options={}) {
  try {
    if (!options || typeof options!=='object' || Array.isArray(options)) return false;
    const {receipt,expectedTenant,consumeOnce,nowMs,maxAgeMs,maxFutureSkewMs}=options;
    if (!receipt || !ID.test(expectedTenant||'') || !NONCE.test(receipt.nonce||'') ||
        typeof consumeOnce!=='function' || !Number.isSafeInteger(nowMs) ||
        !Number.isSafeInteger(maxAgeMs) || !Number.isSafeInteger(maxFutureSkewMs)) return false;
    if (!verifyFreshTenantReceipt(options)) return false;
    // Domain-separated, tenant-scoped opaque identifier; do not store raw nonce.
    const replayKey=createHash('sha256').update('privi-wall-replay-v1\0').update(expectedTenant).update('\0').update(receipt.nonce).digest('hex');
    const expiresAtMs=Math.min(Number.MAX_SAFE_INTEGER,receipt.executedAt+maxAgeMs+maxFutureSkewMs+1);
    if (!Number.isSafeInteger(expiresAtMs) || expiresAtMs<=nowMs) return false;
    // Backend must atomically insert only if absent, with expiry, and fail closed on outage.
    return (await consumeOnce({key:replayKey,expiresAtMs}))===true;
  } catch (_) { return false; }
}
module.exports={verifyOnceTenantReceipt};
