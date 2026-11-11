'use strict';
// Offline-only integration gate. Trust anchors must be independently authorized.
const {verifySignedPolicy}=require('./verify_signed_policy.cjs');
const {auditMonetaryPolicy}=require('./audit_monetary_policy.cjs');
const {auditBankSupply}=require('./audit_bank_supply.cjs');
function auditSignedGenesis(genesis,envelope,trust){
  if(!trust || typeof trust.chainId!=='string' || !Number.isSafeInteger(trust.minVersion) ||
     !trust.trustedKeys || typeof trust.trustedKeys!=='object' ||
     typeof trust.denom!=='string' || !/^[a-zA-Z][a-zA-Z0-9/._-]{0,127}$/.test(trust.denom) ||
     typeof trust.maxSupply!=='string' || !/^(0|[1-9][0-9]*)$/.test(trust.maxSupply) ||
     BigInt(trust.maxSupply)>(1n<<256n)-1n) return ['missing trusted monetary-policy configuration'];
  if(!genesis || genesis.chain_id!==trust.chainId) return ['genesis chain identifier mismatch'];
  if(!verifySignedPolicy(envelope,trust.trustedKeys,trust.chainId,trust.minVersion))
    return ['invalid or unauthorized signed monetary policy'];
  if(envelope.policy.denom!==trust.denom || envelope.policy.maxSupply!==trust.maxSupply)
    return ['signed monetary policy differs from independently authorized parameters'];
  // The legacy auditor requires approved=true. Only this adapter sets it after verification.
  const {denom,maxSupply}=envelope.policy;
  return [...auditMonetaryPolicy(genesis,{approved:true,denom,maxSupply}),...auditBankSupply(genesis)];
}
module.exports={auditSignedGenesis};
