'use strict';
// Release identity is an independent deployment input, not taken from the signed record.
// The expected release identifier must be approved and pinned outside this module.
const {auditSignedGenesisApproval}=require('./audit_signed_genesis_approval.cjs');
const RELEASE=/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;
function auditPinnedReleaseIdentity(genesis,manifestBytes,approval,pinnedPublicKeyPem,expectedReleaseId) {
  if(typeof expectedReleaseId!=='string'||!RELEASE.test(expectedReleaseId))
    return ['missing or invalid independently approved release identifier'];
  if(!approval||typeof approval!=='object'||Array.isArray(approval)||
     approval.releaseId!==expectedReleaseId)
    return ['release identifier differs from independently approved release'];
  return auditSignedGenesisApproval(genesis,manifestBytes,approval,pinnedPublicKeyPem);
}
module.exports={auditPinnedReleaseIdentity};
