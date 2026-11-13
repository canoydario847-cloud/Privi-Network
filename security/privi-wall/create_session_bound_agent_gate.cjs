'use strict';
// Session-bound authorization for long-lived agent sockets.
// admitSignedCall must be a side-effect-free authorization check; execution occurs only after true.
function createSessionBoundAgentGate({verifySession,admitSignedCall,clock=Date.now}={}) {
  if (typeof verifySession!=='function' || typeof admitSignedCall!=='function' || typeof clock!=='function')
    throw new TypeError('trusted session verifier, admission function and clock required');
  async function valid(session) {
    const state=await verifySession(session);
    if (!state || typeof state!=='object' || Array.isArray(state)) return false;
    const expiry=Object.getOwnPropertyDescriptor(state,'expiresAtMs');
    const active=Object.getOwnPropertyDescriptor(state,'active');
    if (!expiry || !Object.prototype.hasOwnProperty.call(expiry,'value') ||
        !active || !Object.prototype.hasOwnProperty.call(active,'value')) return false;
    if (active.value!==true || !Number.isSafeInteger(expiry.value)) return false;
    const now=clock();
    return Number.isSafeInteger(now) && now<expiry.value;
  }
  return Object.freeze({
    async authorize({session,request}={}) {
      try {
        if (!(await valid(session))) return false;
        if ((await admitSignedCall({session,request}))!==true) return false;
        // Recheck after asynchronous verification: authorization may expire or be revoked in flight.
        return (await valid(session))===true;
      } catch (_) { return false; }
    }
  });
}
module.exports={createSessionBoundAgentGate};
