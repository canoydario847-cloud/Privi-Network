'use strict';
// Fail-closed admission gate. verifySignature MUST verify the complete signed
// envelope (tenant, agent, action, nonce, expiresAt, payload digest) with a
// trusted, non-revoked key. Never trust caller-supplied verification flags.
const {admitSignedAgentNonce} = require('./atomic_replay_admission.cjs');
const ID=/^[A-Za-z0-9_-]{1,64}$/;
async function admitAgentCall({sessionTenant, envelope, verifySignature, authorizeAction, reserve, clock, maxLifetimeMs}={}) {
  if (!ID.test(sessionTenant || '') || !envelope || typeof envelope !== 'object' ||
      Array.isArray(envelope) || envelope.tenant !== sessionTenant ||
      !ID.test(envelope.agent || '') || !ID.test(envelope.action || '') ||
      typeof verifySignature !== 'function' || typeof authorizeAction !== 'function') return false;
  try {
    // No replay-store mutation before signature and tenant-bound policy approval.
    if ((await verifySignature(envelope)) !== true) return false;
    if ((await authorizeAction(Object.freeze({
      tenant:sessionTenant, agent:envelope.agent, action:envelope.action
    }))) !== true) return false;
    return await admitSignedAgentNonce({
      tenant:sessionTenant, nonce:envelope.nonce, expiresAt:envelope.expiresAt,
      reserve, clock, maxLifetimeMs
    });
  } catch (_) { return false; }
}
module.exports={admitAgentCall};
