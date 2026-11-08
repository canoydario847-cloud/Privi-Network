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
 // Establish a clock floor before asynchronous admission; wall-clock rollback fails closed.
 const clock=typeof options.clock==='function'?options.clock:Date.now;
 let admissionStart;
 try { admissionStart=clock(); if(!Number.isSafeInteger(admissionStart))return {admitted:false}; }
 catch(_){return {admitted:false};}
 const admitted=await admitBoundAgentCall({...options,envelope:safeEnvelope,payload:safePayload});
 if(!admitted)return {admitted:false};
 // Admission can succeed just before expiry; do not execute after expiry.
 // Treat invalid clocks and rollback as authorization failures.
 try {
   const now = clock();
   if(!Number.isSafeInteger(now)||!Number.isSafeInteger(safeEnvelope.expiresAt)||
      now<admissionStart||now>=safeEnvelope.expiresAt)return {admitted:false};
 }catch(_){return {admitted:false};}
 // Never execute from mutable caller-owned objects. Errors do not become approvals.
 try{
   const result=await execute(Object.freeze({...safeEnvelope}),Buffer.from(safePayload));
   return {admitted:true,executed:true,result};
 }catch(_){return {admitted:true,executed:false};}
}
module.exports={executeAdmittedAgentCall};
