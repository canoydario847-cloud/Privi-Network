'use strict';
// Enforce a bounded authenticated execution-receipt time window before key lookup.
// This guard does NOT replace atomic nonce replay protection.
const {verifyTenantBoundReceipt}=require('./verify_tenant_bound_receipt.cjs');
function verifyFreshTenantReceipt(options={}){
 try{
  if(!options||typeof options!=='object'||Array.isArray(options))return false;
  const {receipt,nowMs,maxAgeMs,maxFutureSkewMs}=options;
  if(!receipt||typeof receipt!=='object'||Array.isArray(receipt)||
     !Number.isSafeInteger(nowMs)||nowMs<0||
     !Number.isSafeInteger(maxAgeMs)||maxAgeMs<1||maxAgeMs>300000||
     !Number.isSafeInteger(maxFutureSkewMs)||maxFutureSkewMs<0||maxFutureSkewMs>30000||
     !Object.hasOwn(receipt,'executedAt')||
     !Number.isSafeInteger(receipt.executedAt)||receipt.executedAt<0)return false;
  // Avoid unsafe arithmetic and reject both expired and future-dated receipts.
  if(receipt.executedAt>nowMs){
   if(receipt.executedAt-nowMs>maxFutureSkewMs)return false;
  }else if(nowMs-receipt.executedAt>maxAgeMs)return false;
  return verifyTenantBoundReceipt(options);
 }catch(_){return false;}
}
module.exports={verifyFreshTenantReceipt};
