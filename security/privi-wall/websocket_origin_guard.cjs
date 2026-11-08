'use strict';
/** Fail-closed browser WebSocket Origin gate. Call before handleUpgrade.
 * This checks browser origin only; authenticate and authorize each connection
 * and each privileged message separately. Never use Origin as identity.
 */
function normalizeOrigin(value) {
  if (typeof value !== 'string' || value.length > 2048 || !value ||
      /[\s,\\]/.test(value) || value === 'null') throw Error('invalid origin');
  let url;
  try { url = new URL(value); } catch { throw Error('invalid origin'); }
  if (!['https:', 'http:'].includes(url.protocol) || url.username ||
      url.password || url.pathname !== '/' || url.search || url.hash ||
      url.origin !== value) throw Error('invalid origin');
  return url.origin;
}
function assertWebSocketOrigin({origin, allowedOrigins}) {
  if (!Array.isArray(allowedOrigins) || !allowedOrigins.length ||
      allowedOrigins.length > 128) throw Error('invalid origin policy');
  const allowed = new Set(allowedOrigins.map(normalizeOrigin));
  const candidate = normalizeOrigin(origin);
  if (!allowed.has(candidate)) throw Error('origin rejected');
  return true;
}
module.exports = {assertWebSocketOrigin};
