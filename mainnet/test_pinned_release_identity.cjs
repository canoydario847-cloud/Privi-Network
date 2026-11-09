'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {generateKeyPairSync,sign,createHash}=require('node:crypto');
const {approvalPayload}=require('./audit_signed_genesis_approval.cjs');
const {auditPinnedReleaseIdentity}=require('./audit_pinned_release_identity.cjs');
const genesis={app_state:{bank:{balances:[{address:'addr1',coins:[{denom:'aprvi',amount:'100'}]}],supply:[{denom:'aprvi',amount:'100'}]}}};
const raw=Buffer.from(JSON.stringify({denom:'aprvi',expectedSupply:'100',maxSupply:'1000'}));
const sha=createHash('sha256').update(raw).digest('hex');
const {privateKey,publicKey}=generateKeyPairSync('ed25519');
const pem=publicKey.export({type:'spki',format:'pem'});
function make(releaseId) {return {releaseId,manifestSha256:sha,signatureBase64:sign(null,approvalPayload(releaseId,sha),privateKey).toString('base64')};}
test('accepts valid signature with independently pinned release',()=>assert.deepEqual(auditPinnedReleaseIdentity(genesis,raw,make('v1'),pem,'v1'),[]));
test('rejects valid signature for a different release',()=>assert.match(auditPinnedReleaseIdentity(genesis,raw,make('v2'),pem,'v1')[0],/differs/));
test('rejects absent expected release',()=>assert.match(auditPinnedReleaseIdentity(genesis,raw,make('v1'),pem,undefined)[0],/missing/));
test('rejects malformed expected release',()=>assert.ok(auditPinnedReleaseIdentity(genesis,raw,make('v1'),pem,'../bad').length));
test('rejects malformed approval',()=>assert.ok(auditPinnedReleaseIdentity(genesis,raw,null,pem,'v1').length));
test('retains signature verification',()=>{const a=make('v1');a.signatureBase64=Buffer.alloc(64).toString('base64');assert.ok(auditPinnedReleaseIdentity(genesis,raw,a,pem,'v1').length);});
