'use strict';
// Bind a signed receipt to the authenticated caller's server-side context.
// Caller-supplied receipt fields must never select the authorization tenant.
const {verifyExecutionReceipt}=require('./verify_execution_receipt.cjs');
const ID=/^[A-Za-z0-9_-]{1,128}$/;
function verifyTenantBoundReceipt({receipt,signature,algorithm,expectedTenant,expectedAgent,expectedAction,resolveTenantKey}={}){
 try {
  if(!receipt||typeof receipt!=='object'||Array.isArray(receipt)||
     !ID.test(expectedTenant||'')||!ID.test(expectedAgent||'')||!ID.test(expectedAction||'')||
     receipt.tenant!==expectedTenant||receipt.agent!==expectedAgent||receipt.action!==expectedAction||
     typeof resolveTenantKey!=='function')return false;
  // A trusted tenant comes from authenticated server context, never from receipt claims.
  return verifyExecutionReceipt({receipt,signature,algorithm,
   keyResolver:(keyId,alg)=>resolveTenantKey(expectedTenant,keyId,alg)});
 }catch(_){return false;}
}
module.exports={verifyTenantBoundReceipt};
