'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {generateKeyPairSync,sign}=require('node:crypto');
const {receiptTranscript}=require('./receipt_transcript.cjs');
const {verifyExecutionReceipt:check}=require('./verify_execution_receipt.cjs');
const {publicKey,privateKey}=generateKeyPairSync('ed25519');
const other=generateKeyPairSync('ed25519');
const receipt={tenant:'tenantA',agent:'agentA',action:'execute',nonce:'a'.repeat(32),
 requestSha256:'b'.repeat(64),outcomeSha256:'c'.repeat(64),keyId:'key1',executedAt:100,status:'success'};
const signature=sign(null,receiptTranscript(receipt),privateKey);
const resolver=id=>id==='key1'?publicKey:null;
test('valid trusted receipt verifies',()=>assert.equal(check({receipt,signature,algorithm:'Ed25519',keyResolver:resolver}),true));
test('tampered tenant fails',()=>assert.equal(check({receipt:{...receipt,tenant:'tenantB'},signature,algorithm:'Ed25519',keyResolver:resolver}),false));
test('tampered result fails',()=>assert.equal(check({receipt:{...receipt,outcomeSha256:'d'.repeat(64)},signature,algorithm:'Ed25519',keyResolver:resolver}),false));
test('untrusted key id fails',()=>assert.equal(check({receipt:{...receipt,keyId:'key2'},signature,algorithm:'Ed25519',keyResolver:resolver}),false));
test('unsupported algorithms fail closed',()=>assert.equal(check({receipt,signature,algorithm:'ML-DSA-65',keyResolver:resolver}),false));
test('wrong trusted key fails',()=>assert.equal(check({receipt,signature,algorithm:'Ed25519',keyResolver:()=>other.publicKey}),false));
test('resolver failure fails closed',()=>assert.equal(check({receipt,signature,algorithm:'Ed25519',keyResolver:()=>{throw Error('offline')}}),false));
test('async resolver fails closed',()=>assert.equal(check({receipt,signature,algorithm:'Ed25519',keyResolver:async()=>publicKey}),false));
test('malformed signature fails',()=>assert.equal(check({receipt,signature:Buffer.alloc(1),algorithm:'Ed25519',keyResolver:resolver}),false));

test('trusted PEM public key verifies',()=>assert.equal(check({receipt,signature,algorithm:'Ed25519',keyResolver:()=>publicKey.export({type:'spki',format:'pem'})}),true));
test('private key rejected as trusted verifier key',()=>assert.equal(check({receipt,signature,algorithm:'Ed25519',keyResolver:()=>privateKey}),false));

test('private PEM rejected as verifier key',()=>assert.equal(check({receipt,signature,algorithm:'Ed25519',keyResolver:()=>privateKey.export({type:'pkcs8',format:'pem'})}),false));
test('ambiguous resolver object rejected',()=>assert.equal(check({receipt,signature,algorithm:'Ed25519',keyResolver:()=>({key:privateKey.export({type:'pkcs8',format:'pem'})})}),false));
test('raw buffer resolver key rejected',()=>assert.equal(check({receipt,signature,algorithm:'Ed25519',keyResolver:()=>Buffer.from(publicKey.export({type:'spki',format:'pem'}))}),false));
