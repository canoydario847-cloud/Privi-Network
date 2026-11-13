'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const Module=require('node:module');
const originalLoad=Module._load;
let behavior=async()=>true;
Module._load=function(request,parent,isMain){
 if(parent && parent.filename.endsWith('/create_gateway_replay_gate.cjs') && request==='./verify_once_tenant_receipt.cjs')
  return {verifyOnceTenantReceipt:(options)=>behavior(options)};
 return originalLoad.apply(this,arguments);
};
const {createGatewayReplayGate}=require('./create_gateway_replay_gate.cjs');
Module._load=originalLoad;
function gate(){return createGatewayReplayGate({client:{set:async()=> 'OK'},maxAgeMs:100,maxFutureSkewMs:10,maxReplayTtlMs:111});}
test('request getter throwing fails closed rather than rejecting',async()=>{
 const hostile=Object.defineProperty({},'receipt',{enumerable:true,get(){throw Error('hostile getter')}});
 assert.equal(await gate().verify(hostile),false);
});
test('synchronous verifier exception fails closed',async()=>{
 behavior=()=>{throw Error('verification exception')};
 assert.equal(await gate().verify({}),false);
});
test('asynchronous verifier rejection fails closed',async()=>{
 behavior=async()=>{throw Error('verification rejection')};
 assert.equal(await gate().verify({}),false);
});
test('non-boolean truthy verifier result is rejected',async()=>{
 behavior=async()=>({accepted:true});
 assert.equal(await gate().verify({}),false);
});
test('successful strict boolean verifier result is accepted',async()=>{
 behavior=async()=>true;
 assert.equal(await gate().verify({}),true);
});
