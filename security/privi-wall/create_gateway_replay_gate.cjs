'use strict';
// Construct before accepting traffic; invalid replay policies abort startup.
const {validateReplayPolicy}=require('./validate_replay_policy.cjs');
const {createRedisReplayAdmission}=require('./redis_replay_admission.cjs');
const {verifyOnceTenantReceipt}=require('./verify_once_tenant_receipt.cjs');
function createGatewayReplayGate({client,maxAgeMs,maxFutureSkewMs,maxReplayTtlMs,prefix}={}) {
  const policy=validateReplayPolicy({maxAgeMs,maxFutureSkewMs,maxReplayTtlMs});
  const consumeOnce=createRedisReplayAdmission(client,{prefix,maxTtlMs:policy.maxReplayTtlMs});
  return Object.freeze({
    policy,
    async verify(options={}) {
      if (!options || typeof options!=='object' || Array.isArray(options)) return false;
      // Caller cannot override the startup-validated policy or replay backend.
      return verifyOnceTenantReceipt({...options,maxAgeMs:policy.maxAgeMs,
        maxFutureSkewMs:policy.maxFutureSkewMs,consumeOnce});
    }
  });
}
module.exports={createGatewayReplayGate};
