'use strict';
// Privi Wall: privileged execution is strictly downstream of signed admission.
// The executor receives a private copy of the verified request, never caller-owned data.
const {admitBoundAgentCall}=require('./signed_claims_binding.cjs');
const FIELDS=['tenant','agent','action','nonce','expiresAt'];
async function executeAdmittedAgentCall(options={}){
 const {envelope,payload,execute}=options;
 if(typeof execute!=='function'||!Buffer.isBuffer(payload)||payload.length>65536||
    !envelope||typeof envelope!=='object'||Array.isArray(envelope))return {admitted:false};
 const safeEnvelope=Object.create(null);
 for(const field of FIELDS){
   if(!Object.prototype.hasOwnProperty.call(envelope,field))return {admitted:false};
   safeEnvelope[field]=envelope[field];
 }
 const safePayload=Buffer.from(payload);
 const admitted=await admitBoundAgentCall({...options,envelope:safeEnvelope,payload:safePayload});
 if(!admitted)return {admitted:false};
 // Never execute from mutable caller-owned objects. Errors do not become approvals.
 try{
   const result=await execute(Object.freeze({...safeEnvelope}),Buffer.from(safePayload));
   return {admitted:true,executed:true,result};
 }catch(_){return {admitted:true,executed:false};}
}
module.exports={executeAdmittedAgentCall};
