'use strict';
// Contract for trusted signature verifier: it MUST cryptographically verify
// the signed bytes and return the exact claims actually covered by the signature.
// This adapter does not implement signature cryptography.
const {createHash,timingSafeEqual}=require('node:crypto');
const {admitAgentCall}=require('./signed_agent_admission_gate.cjs');
const FIELDS=['tenant','agent','action','nonce','expiresAt'];
function own(o,k){return Object.prototype.hasOwnProperty.call(o,k);}
function digest(payload){return createHash('sha256').update(payload).digest();}
async function admitBoundAgentCall({sessionTenant,envelope,payload,verifySignedClaims,authorizeAction,reserve,clock,maxLifetimeMs}={}){
 if(!Buffer.isBuffer(payload)||payload.length>65536||!envelope||typeof envelope!=='object'||Array.isArray(envelope)||typeof verifySignedClaims!=='function')return false;
 // Snapshot prevents caller mutation across asynchronous verifier and policy calls.
 const snapshot={};
 for(const k of FIELDS){if(!own(envelope,k))return false;snapshot[k]=envelope[k];}
 if(!FIELDS.slice(0,4).every(k=>typeof snapshot[k]==='string')||!Number.isSafeInteger(snapshot.expiresAt))return false;
 const payloadCopy=Buffer.from(payload), expected=digest(payloadCopy);
 try{
  const verified=await verifySignedClaims(Object.freeze({...snapshot}),Buffer.from(payloadCopy));
  if(!verified||verified.verified!==true||!verified.claims||typeof verified.claims!=='object'||Array.isArray(verified.claims))return false;
  const claims=verified.claims;
  if(!FIELDS.every(k=>own(claims,k)&&claims[k]===snapshot[k]))return false;
  if(typeof claims.payloadSha256!=='string'||!/^[a-f0-9]{64}$/.test(claims.payloadSha256))return false;
  if(!timingSafeEqual(expected,Buffer.from(claims.payloadSha256,'hex')))return false;
  return await admitAgentCall({sessionTenant,envelope:Object.freeze(snapshot),verifySignature:async()=>true,authorizeAction,reserve,clock,maxLifetimeMs});
 }catch(_){return false;}
}
module.exports={admitBoundAgentCall};
