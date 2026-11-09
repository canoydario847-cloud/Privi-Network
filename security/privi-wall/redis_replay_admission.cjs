'use strict';
// Redis SET NX PXAT provides a single atomic admission decision across replicas.
// Requires a shared, authenticated Redis deployment with persistence configured.
const HEX=/^[a-f0-9]{64}$/;
function createRedisReplayAdmission(client,{prefix='privi-wall:replay:v1:'}={}) {
  if (!client || typeof client.set!=='function' ||
      typeof prefix!=='string' || !/^[-a-zA-Z0-9:_]{1,100}$/.test(prefix))
    throw new TypeError('Invalid replay store configuration');
  return async function consumeOnce({key,expiresAtMs}={}) {
    if (typeof key!=='string' || !HEX.test(key) ||
        !Number.isSafeInteger(expiresAtMs) || expiresAtMs<=Date.now()) return false;
    try {
      // node-redis v4/v5: SET key value {NX:true,PXAT:timestamp}.
      // No GET/SET split: concurrent replicas cannot both admit the same key.
      const result=await client.set(prefix+key,'1',{NX:true,PXAT:expiresAtMs});
      return result==='OK';
    } catch (_) { return false; }
  };
}
module.exports={createRedisReplayAdmission};
