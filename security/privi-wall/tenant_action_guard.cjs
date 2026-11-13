'use strict';
// Deny-by-default tenant and action boundary for privileged agent messages.
// Context MUST originate from verified authentication, never from the message.
async function authorizeTenantAction({context, message, isAllowed}) {
  if (!context || typeof context !== 'object' ||
      typeof context.agentId !== 'string' || !context.agentId ||
      typeof context.tenant !== 'string' || !context.tenant ||
      !message || typeof message !== 'object' || Array.isArray(message) ||
      typeof message.tenant !== 'string' || !message.tenant ||
      message.tenant !== context.tenant ||
      typeof message.action !== 'string' ||
      !/^[a-z][a-z0-9_.:-]{0,63}$/.test(message.action) ||
      typeof isAllowed !== 'function') return false;
  try {
    // Explicit true only. A missing, throwing, or ambiguous policy denies.
    return (await isAllowed(Object.freeze({
      tenant: context.tenant, agentId: context.agentId,
      action: message.action
    }))) === true;
  } catch (_) { return false; }
}
module.exports = {authorizeTenantAction};
