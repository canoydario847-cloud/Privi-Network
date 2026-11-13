'use strict';
/**
 * Fail-closed guard for already-open WebSocket agent sessions.
 * Call before every privileged message; close expired/revoked sessions.
 * Requires an explicit revocation authority; missing authority denies access.\n * Does not replace upgrade authentication, per-message authorization or TLS.
 */
function enforceActiveSession({socket, context, now = Date.now(), isRevoked}) {
  if (!socket || typeof socket.close !== 'function') throw Error('socket required');
  if (typeof isRevoked !== 'function') {
    try { socket.close(1008, 'Session unauthorized'); } catch (_) { /* still deny */ }
    return false;
  }
  const valid = context && typeof context === 'object' &&
    typeof context.agentId === 'string' && context.agentId.length > 0 &&
    typeof context.tenant === 'string' && context.tenant.length > 0 &&
    typeof context.audience === 'string' && context.audience.length > 0 &&
    Number.isSafeInteger(context.expiresAt) &&
    Number.isSafeInteger(now) && now < context.expiresAt;
  let authorized = false;
  if (valid) {
    try { authorized = isRevoked(context) === false; }
    catch (_) { authorized = false; }
  }
  if (!authorized) {
    try { socket.close(1008, 'Session unauthorized'); } catch (_) { /* still deny */ }
    return false;
  }
  return true;
}
module.exports = {enforceActiveSession};
