'use strict';
// Offline release-approval gate. Public key must be pinned through an independently
// authenticated governance process; this module does not confer authorization itself.
const {createPublicKey,verify,createHash,timingSafeEqual}=require('node:crypto');
const {auditPinnedSupplyManifest}=require('./audit_pinned_supply_manifest.cjs');
const HEX=/^[0-9a-f]{64}$/;
const RELEASE=/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;
function approvalPayload(releaseId,manifestSha256) {
 return Buffer.from('PRIVI-GENESIS-APPROVAL-v1\n'+releaseId+'\n'+manifestSha256+'\n','utf8');
}
function auditSignedGenesisApproval(genesis,manifestBytes,approval,pinnedPublicKeyPem) {
 if(!approval||typeof approval!=='object'||Array.isArray(approval)||
    !RELEASE.test(approval.releaseId||'')||!HEX.test(approval.manifestSha256||''))
  return ['invalid release approval metadata'];
 if(typeof approval.signatureBase64!=='string'||! /^[A-Za-z0-9+/]+={0,2}$/.test(approval.signatureBase64)||
    approval.signatureBase64.length>128)
  return ['invalid release approval signature encoding'];
 const sig=Buffer.from(approval.signatureBase64,'base64');
 if(sig.length!==64||sig.toString('base64')!==approval.signatureBase64)
  return ['invalid release approval signature length or canonical encoding'];
 let key;
 try {key=createPublicKey(pinnedPublicKeyPem);}
 catch {return ['invalid independently pinned approval public key'];}
 if(key.asymmetricKeyType!=='ed25519')return ['approval key must be Ed25519'];
 let valid=false;
 try {valid=verify(null,approvalPayload(approval.releaseId,approval.manifestSha256),key,sig);}
 catch {return ['release approval signature verification failed'];}
 if(!valid)return ['release approval signature verification failed'];
 return auditPinnedSupplyManifest(genesis,manifestBytes,approval.manifestSha256);
}
module.exports={approvalPayload,auditSignedGenesisApproval};
