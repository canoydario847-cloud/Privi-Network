'use strict';
/**
 * Asynchronous fail-closed authorization for privileged WebSocket agent calls.
 * The caller MUST await the returned boolean before processing the message.
 * The revocation authority MUST return exactly false to authorize.
 * A timeout, rejected promise, malformed result, or missing authority denies.
 */
async function enforceAsyncActiveSession({socket, context, isRevoked, now = Date.now(), timeoutMs = 1000}) {
  if (!socket || typeof socket.close !== 'function') throw Error('socket required');
  const deny = () => {
    try { socket.close(1008, 'Session unauthorized'); } catch (_) { /* deny regardless */ }
    return false;
  };
  if (typeof isRevoked !== 'function' || !Number.isSafeInteger(timeoutMs) ||
      timeoutMs < 1 || timeoutMs > 30000 ||
      !context || typeof context !== 'object' ||
      typeof context.agentId !== 'string' || !context.agentId ||
      typeof context.tenant !== 'string' || !context.tenant ||
      typeof context.audience !== 'string' || !context.audience ||
      !Number.isSafeInteger(context.expiresAt) ||
      !Number.isSafeInteger(now) || now >= context.expiresAt) return deny();

  // Monotonic elapsed time prevents an in-flight revocation check from
  // authorizing an agent after the credential's remaining lifetime.
  const started = process.hrtime.bigint();
  const remainingMs = context.expiresAt - now;
  const budgetMs = Math.min(timeoutMs, remainingMs);
  let timer;
  try {
    const revoked = await Promise.race([
      Promise.resolve().then(() => isRevoked(context)),
      new Promise((_, reject) => { timer = setTimeout(() => reject(Error('revocation timeout')), budgetMs); })
    ]);
    const elapsedMs = Number(process.hrtime.bigint() - started) / 1e6;
    return revoked === false && elapsedMs < remainingMs ? true : deny();
  } catch (_) {
    return deny();
  } finally {
    if (timer !== undefined) clearTimeout(timer);
  }
}
module.exports = {enforceAsyncActiveSession};
