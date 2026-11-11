'use strict';
// Offline-only integration gate. Trust anchors must be independently authorized.
const {verifySignedPolicy}=require('./verify_signed_policy.cjs');
const {auditMonetaryPolicy}=require('./audit_monetary_policy.cjs');
const {auditBankSupply}=require('./audit_bank_supply.cjs');
function auditSignedGenesis(genesis,envelope,trust){
  if(!trust || typeof trust.chainId!=='string' || !Number.isSafeInteger(trust.minVersion) ||
     !trust.trustedKeys || typeof trust.trustedKeys!=='object') return ['missing trusted monetary-policy configuration'];
  if(!genesis || genesis.chain_id!==trust.chainId) return ['genesis chain identifier mismatch'];
  if(!verifySignedPolicy(envelope,trust.trustedKeys,trust.chainId,trust.minVersion))
    return ['invalid or unauthorized signed monetary policy'];
  // The legacy auditor requires approved=true. Only this adapter sets it after verification.
  const {denom,maxSupply}=envelope.policy;
  return [...auditMonetaryPolicy(genesis,{approved:true,denom,maxSupply}),...auditBankSupply(genesis)];
}
module.exports={auditSignedGenesis};
