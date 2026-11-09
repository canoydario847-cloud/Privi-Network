'use strict';
// Bind receipt verification expectations to server-authenticated context, never request claims.
const ID=/^[A-Za-z0-9_-]{1,128}$/;
function createTrustedTenantGate({gate,resolveIdentity}={}) {
  if (!gate || typeof gate.verify!=='function' || typeof resolveIdentity!=='function')
    throw new TypeError('trusted gateway and identity resolver required');
  return Object.freeze({
    async verify({request,session}={}) {
      try {
        // resolveIdentity must validate the session against server-side auth state.
        const identity=await resolveIdentity(session);
        if (!identity || typeof identity!=='object' ||
            !ID.test(identity.tenantId||'') || !ID.test(identity.agentId||'') ||
            !ID.test(identity.actionId||'')) return false;
        if (!request || typeof request!=='object' || Array.isArray(request)) return false;
        const {receipt,signature,algorithm}=request;
        if (!receipt || !signature || !algorithm || typeof identity.resolveTenantKey!=='function') return false;
        return (await gate.verify({
          receipt,signature,algorithm,resolveTenantKey:identity.resolveTenantKey,
          expectedTenant:identity.tenantId,
          expectedAgent:identity.agentId,
          expectedAction:identity.actionId
        }))===true;
      } catch (_) { return false; }
    }
  });
}
module.exports={createTrustedTenantGate};
