'use strict';
// Bind receipt verification expectations to server-authenticated context, never request claims.
const ID=/^[A-Za-z0-9_-]{1,128}$/;
const ownData=(obj,key)=>{
  const descriptor=Object.getOwnPropertyDescriptor(obj,key);
  return descriptor && Object.prototype.hasOwnProperty.call(descriptor,'value') ? descriptor.value : undefined;
};
function validIdentity(identity) {
  if (!identity || typeof identity!=='object' || Array.isArray(identity)) return false;
  for (const key of ['tenantId','agentId','actionId']) {
    const value=ownData(identity,key);
    if (typeof value!=='string' || !ID.test(value)) return false;
  }
  return typeof ownData(identity,'resolveTenantKey')==='function';
}
function createTrustedTenantGate({gate,resolveIdentity}={}) {
  if (!gate || typeof gate.verify!=='function' || typeof resolveIdentity!=='function')
    throw new TypeError('trusted gateway and identity resolver required');
  return Object.freeze({
    async verify({request,session}={}) {
      try {
        // resolveIdentity must validate the session against server-side auth state.
        const identity=await resolveIdentity(session);
        if (!validIdentity(identity)) return false;
        if (!request || typeof request!=='object' || Array.isArray(request)) return false;
        // Never invoke accessors or trust inherited request fields during admission.
        const receipt=ownData(request,'receipt');
        const signature=ownData(request,'signature');
        const algorithm=ownData(request,'algorithm');
        if (!receipt || !signature || !algorithm) return false;
        return (await gate.verify({
          receipt,signature,algorithm,resolveTenantKey:ownData(identity,'resolveTenantKey'),
          expectedTenant:ownData(identity,'tenantId'),
          expectedAgent:ownData(identity,'agentId'),
          expectedAction:ownData(identity,'actionId')
        }))===true;
      } catch (_) { return false; }
    }
  });
}
module.exports={createTrustedTenantGate};
