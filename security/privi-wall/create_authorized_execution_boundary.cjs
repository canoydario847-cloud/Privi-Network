'use strict';
// Execution-boundary adapter. The trusted executor MUST atomically enforce session
// revocation/expiry and action permission at its own side-effect boundary.
// This wrapper alone cannot guarantee atomicity across a distributed system.
function createAuthorizedExecutionBoundary({authorize, executeAuthorized}={}) {
  if (typeof authorize!=='function' || typeof executeAuthorized!=='function')
    throw new TypeError('trusted authorization and execution functions required');
  return Object.freeze({
    async execute({session,request}={}) {
      try {
        if ((await authorize({session,request}))!==true)
          return Object.freeze({ok:false,reason:'denied'});
        // Never execute through a caller-supplied callback. The trusted executor
        // must revalidate authorization atomically with the protected operation.
        const result=await executeAuthorized({session,request});
        if (!result || typeof result!=='object' || Array.isArray(result))
          return Object.freeze({ok:false,reason:'executor_error'});
        const ok=Object.getOwnPropertyDescriptor(result,'ok');
        if (!ok || !Object.prototype.hasOwnProperty.call(ok,'value') || ok.value!==true)
          return Object.freeze({ok:false,reason:'executor_denied'});
        return Object.freeze({ok:true});
      } catch (_) {
        return Object.freeze({ok:false,reason:'error'});
      }
    }
  });
}
module.exports={createAuthorizedExecutionBoundary};
