'use strict';
const {assertWebSocketOrigin} = require('./websocket_origin_guard.cjs');
/** Gate to invoke before ws.handleUpgrade; auth must resolve to a trusted principal. */
async function authorizeWebSocketUpgrade({request, allowedOrigins, authenticate, expectedTenant, expectedAudience}) {
  if (!request || typeof request !== 'object' || !request.headers ||
      typeof request.headers !== 'object') throw Error('invalid upgrade request');
  if (typeof authenticate !== 'function') throw Error('authentication required');
  if (typeof expectedTenant !== 'string' || !expectedTenant ||
      typeof expectedAudience !== 'string' || !expectedAudience) throw Error('trusted context required');
  const origin = request.headers.origin;
  if (typeof origin !== 'string') throw Error('invalid origin');
  assertWebSocketOrigin({origin, allowedOrigins});
  const principal = await authenticate(request);
  if (!principal || typeof principal !== 'object' ||
      principal.authenticated !== true ||
      principal.tenant !== expectedTenant || principal.audience !== expectedAudience ||
      typeof principal.agentId !== 'string' || !principal.agentId ||
      !Number.isSafeInteger(principal.expiresAt) || principal.expiresAt <= Date.now()) throw Error('upgrade unauthorized');
  return Object.freeze({agentId:principal.agentId, tenant:expectedTenant, audience:expectedAudience, expiresAt:principal.expiresAt});
}
module.exports = {authorizeWebSocketUpgrade};
