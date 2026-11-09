'use strict';
// Privi Wall: only server-side resolver may select execution identity.
// The caller must not supply tenant/agent/action identity through the request.
// Backend still MUST enforce revocation and authorization atomically with effects.
const {createAuthorizedExecutionBoundary}=require('./create_authorized_execution_boundary.cjs');
// Canonical ASCII identifiers avoid whitespace/control-character and Unicode-normalization
// ambiguity across tenant policy stores. Integrators must map external IDs first.
const CANONICAL_ID=/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;\nfunction createTrustedExecutionContextGate({resolveTrustedContext,authorize,executeAuthorized}={}) {
  if (typeof resolveTrustedContext!=='function') throw new TypeError('trusted context resolver required');
  const boundary=createAuthorizedExecutionBoundary({authorize,executeAuthorized});
  return Object.freeze({
    async execute({connection,request}={}) {
      try {
        const context=await resolveTrustedContext(connection);
        if (!context || typeof context!=='object' || Array.isArray(context)) return Object.freeze({ok:false,reason:'untrusted_context'});
        const identity={};
        for (const key of ['tenantId','agentId','actionId','sessionId']) {
          const d=Object.getOwnPropertyDescriptor(context,key);
          if (!d || !Object.prototype.hasOwnProperty.call(d,'value') ||
              typeof d.value!=='string' || !CANONICAL_ID.test(d.value)) return Object.freeze({ok:false,reason:'untrusted_context'});
          identity[key]=d.value;
        }
        return boundary.execute({session:Object.freeze(identity),request});
      } catch (_) { return Object.freeze({ok:false,reason:'untrusted_context'}); }
    }
  });
}
module.exports={createTrustedExecutionContextGate};
