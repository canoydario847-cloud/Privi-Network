'use strict';
// Bounded, deny-by-default authorization. Timeout is not cancellation:
// Policy callbacks MUST be read-only and MUST NOT execute privileged actions.
const {authorizeTenantAction} = require('./tenant_action_guard.cjs');
async function authorizeTenantActionWithDeadline({context, message, isAllowed, timeoutMs = 1000}) {
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 30000 ||
      typeof isAllowed !== 'function') return false;
  let timer;
  try {
    const result = await Promise.race([
      authorizeTenantAction({context, message, isAllowed}),
      new Promise(resolve => { timer = setTimeout(() => resolve(false), timeoutMs); })
    ]);
    return result === true;
  } catch (_) { return false; }
  finally { if (timer !== undefined) clearTimeout(timer); }
}
module.exports = {authorizeTenantActionWithDeadline};
