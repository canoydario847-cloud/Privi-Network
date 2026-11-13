'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {generateKeyPairSync,sign}=require('node:crypto');
const {receiptTranscript}=require('./receipt_transcript.cjs');
const {verifyTenantBoundReceipt:check}=require('./verify_tenant_bound_receipt.cjs');
const a=generateKeyPairSync('ed25519'),b=generateKeyPairSync('ed25519');
const receipt={tenant:'tenantA',agent:'agentA',action:'execute',nonce:'a'.repeat(32),
 requestSha256:'b'.repeat(64),outcomeSha256:'c'.repeat(64),keyId:'key1',executedAt:100,status:'success'};
const signature=sign(null,receiptTranscript(receipt),a.privateKey);
const resolveTenantKey=(tenant,id,alg)=>tenant==='tenantA'&&id==='key1'&&alg==='Ed25519'?a.publicKey:null;
const args={receipt,signature,algorithm:'Ed25519',expectedTenant:'tenantA',
 expectedAgent:'agentA',expectedAction:'execute',resolveTenantKey};
test('valid receipt is bound to server tenant agent and action',()=>assert.equal(check(args),true));
test('cross tenant replay denied before resolver',()=>{
 let calls=0;
 assert.equal(check({...args,expectedTenant:'tenantB',resolveTenantKey:()=>{calls++;return a.publicKey;}}),false);
 assert.equal(calls,0);
});
test('cross agent receipt denied',()=>assert.equal(check({...args,expectedAgent:'agentB'}),false));
test('cross action receipt denied',()=>assert.equal(check({...args,expectedAction:'delete'}),false));
test('tenant-scoped resolver cannot use another tenant key',()=>{
 const sig=sign(null,receiptTranscript(receipt),b.privateKey);
 assert.equal(check({...args,signature:sig}),false);
});
test('missing authenticated context denied',()=>assert.equal(check({...args,expectedTenant:undefined}),false));
test('malformed context denied',()=>assert.equal(check({...args,expectedTenant:'tenant A'}),false));
test('resolver exceptions fail closed',()=>assert.equal(check({...args,resolveTenantKey:()=>{throw Error('offline')}}),false));
test('unsupported post-quantum algorithm fails closed',()=>assert.equal(check({...args,algorithm:'ML-DSA-65'}),false));
