'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {receiptDigest,receiptTranscript}=require('./receipt_transcript.cjs');
const base={tenant:'tenant-A',agent:'agent-1',action:'read',nonce:'a'.repeat(32),requestSha256:'b'.repeat(64),outcomeSha256:'c'.repeat(64),keyId:'key-1',executedAt:1000,status:'success'};
test('deterministic canonical transcript independent of input property order',()=>{
 assert.equal(receiptDigest(base),receiptDigest(Object.fromEntries(Object.entries(base).reverse())));
 assert.ok(receiptTranscript(base).subarray(0,Buffer.byteLength('PRIVI-WALL-AGENT-EXECUTION-RECEIPT-V1')).toString()==='PRIVI-WALL-AGENT-EXECUTION-RECEIPT-V1');
});
test('tenant and agent identity bind digest',()=>{
 for(const k of ['tenant','agent','action','nonce','requestSha256','outcomeSha256','keyId','executedAt','status']){
  const value=k==='executedAt'?1001:k==='status'?'failure':k==='nonce'?'d'.repeat(32):k.endsWith('Sha256')?'e'.repeat(64):'changed';
  assert.notEqual(receiptDigest(base),receiptDigest({...base,[k]:value}),k);
 }
});
test('reject missing fields, invalid hashes, unsafe timestamp and status',()=>{
 for(const [k,v] of [['tenant',undefined],['requestSha256','BAD'],['outcomeSha256','0'.repeat(63)],['executedAt',NaN],['executedAt',-1],['status','pending'],['nonce','x'.repeat(32)]]){
  const x={...base};if(v===undefined)delete x[k];else x[k]=v;
  assert.throws(()=>receiptTranscript(x),{name:'TypeError',message:k});
 }
});
test('reject prototype inherited fields and non-object input',()=>{
 const x=Object.create(base);assert.throws(()=>receiptTranscript(x));
 assert.throws(()=>receiptTranscript(null));
});
test('returned transcript is isolated from subsequent caller mutation',()=>{
 const x={...base},original=receiptTranscript(x);x.tenant='changed';
 assert.notDeepEqual(original,receiptTranscript(x));
});
