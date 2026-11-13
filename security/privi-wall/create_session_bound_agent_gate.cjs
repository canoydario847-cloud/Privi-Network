'use strict';
// Per-message, server-authoritative authorization for long-lived agent sockets.
// This adapter does not open sockets or authenticate sessions itself.
function createSessionBoundAgentGate({verifySession,admitSignedCall,clock=Date.now}={}) {
  if (typeof verifySession!=='function' || typeof admitSignedCall!=='function' || typeof clock!=='function')
    throw new TypeError('trusted session verifier, admission function and clock required');
  return Object.freeze({
    async authorize({session,request}={}) {
      try {
        const state=await verifySession(session);
        if (!state || typeof state!=='object' || Array.isArray(state)) return false;
        const expiry=Object.getOwnPropertyDescriptor(state,'expiresAtMs');
        const active=Object.getOwnPropertyDescriptor(state,'active');
        if (!expiry || !Object.prototype.hasOwnProperty.call(expiry,'value') ||
            !active || !Object.prototype.hasOwnProperty.call(active,'value')) return false;
        if (active.value!==true || !Number.isSafeInteger(expiry.value)) return false;
        const now=clock();
        if (!Number.isSafeInteger(now) || now>=expiry.value) return false;
        return (await admitSignedCall({session,request}))===true;
      } catch (_) { return false; }
    }
  });
}
module.exports={createSessionBoundAgentGate};
