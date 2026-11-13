'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {generateKeyPairSync,sign}=require('node:crypto');
const {receiptTranscript}=require('./receipt_transcript.cjs');
const {verifyFreshTenantReceipt:check}=require('./verify_fresh_tenant_receipt.cjs');
const pair=generateKeyPairSync('ed25519');
const receipt={tenant:'tenantA',agent:'agentA',action:'execute',nonce:'a'.repeat(32),
 requestSha256:'b'.repeat(64),outcomeSha256:'c'.repeat(64),keyId:'key1',executedAt:100000,status:'success'};
const signature=sign(null,receiptTranscript(receipt),pair.privateKey);
const args={receipt,signature,algorithm:'Ed25519',expectedTenant:'tenantA',expectedAgent:'agentA',
 expectedAction:'execute',resolveTenantKey:()=>pair.publicKey,nowMs:100100,maxAgeMs:30000,maxFutureSkewMs:1000};
test('fresh correctly signed tenant receipt accepted',()=>assert.equal(check(args),true));
test('expired receipt rejected before key resolver',()=>{
 let calls=0;
 assert.equal(check({...args,nowMs:130001,resolveTenantKey:()=>{calls++;return pair.publicKey;}}),false);
 assert.equal(calls,0);
});
test('receipt exactly at age boundary accepted',()=>assert.equal(check({...args,nowMs:130000}),true));
test('future receipt outside skew rejected',()=>assert.equal(check({...args,nowMs:98999}),false));
test('future receipt at skew boundary accepted',()=>assert.equal(check({...args,nowMs:99000}),true));
test('missing time policy fails closed',()=>assert.equal(check({...args,maxAgeMs:undefined}),false));
test('oversized time policy fails closed',()=>assert.equal(check({...args,maxAgeMs:300001}),false));
test('unsafe integer time fails closed',()=>assert.equal(check({...args,nowMs:Number.MAX_SAFE_INTEGER+1}),false));
test('tampered receipt fails signature verification',()=>assert.equal(check({...args,receipt:{...receipt,status:'failure'}}),false));
test('tenant mismatch remains denied',()=>assert.equal(check({...args,expectedTenant:'tenantB'}),false));
