'use strict';
// A bounded replay retention window limits attacker-controlled Redis key lifetime.
// Requires a shared authenticated Redis deployment; no production integration here.
const HEX=/^[a-f0-9]{64}$/;
function createRedisReplayAdmission(client,{prefix='privi-wall:replay:v1:',maxTtlMs=600000}={}) {
  if (!client || typeof client.set!=='function' ||
      typeof prefix!=='string' || !/^[-a-zA-Z0-9:_]{1,100}$/.test(prefix) ||
      !Number.isSafeInteger(maxTtlMs) || maxTtlMs<1 || maxTtlMs>86400000)
    throw new TypeError('Invalid replay store configuration');
  return async function consumeOnce({key,expiresAtMs}={}) {
    const now=Date.now();
    if (typeof key!=='string' || !HEX.test(key) ||
        !Number.isSafeInteger(expiresAtMs) ||
        expiresAtMs<=now || expiresAtMs-now>maxTtlMs) return false;
    try {
      // Atomic SET NX PXAT; no GET/SET race. Expiration is bounded.
      const result=await client.set(prefix+key,'1',{NX:true,PXAT:expiresAtMs});
      return result==='OK';
    } catch (_) { return false; }
  };
}
module.exports={createRedisReplayAdmission};
