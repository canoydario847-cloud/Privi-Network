'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const Module=require('node:module');
const originalLoad=Module._load;
let received;
Module._load=function(request,parent,isMain){
  if(parent && parent.filename.endsWith('/create_gateway_replay_gate.cjs') && request==='./verify_once_tenant_receipt.cjs')
    return {verifyOnceTenantReceipt:async options=>{received=options;return true;}};
  return originalLoad.apply(this,arguments);
};
const {createGatewayReplayGate}=require('./create_gateway_replay_gate.cjs');
Module._load=originalLoad;
const client={set:async()=> 'OK'};
const base={client,maxAgeMs:100,maxFutureSkewMs:10,maxReplayTtlMs:111};
test('fails startup on insufficient replay retention',()=>{
 assert.throws(()=>createGatewayReplayGate({...base,maxReplayTtlMs:110}),RangeError);
});
test('fails startup without shared replay backend',()=>{
 assert.throws(()=>createGatewayReplayGate({...base,client:null}),TypeError);
});
test('pins immutable policy and ignores per-request overrides',async()=>{
 const gate=createGatewayReplayGate(base);
 assert.equal(Object.isFrozen(gate),true);
 assert.equal(await gate.verify({maxAgeMs:999999,maxFutureSkewMs:999999,consumeOnce:()=>false}),true);
 assert.equal(received.maxAgeMs,100);
 assert.equal(received.maxFutureSkewMs,10);
 assert.equal(typeof received.consumeOnce,'function');
});
test('rejects malformed verification arguments without invoking verifier',async()=>{
 received=null;
 const gate=createGatewayReplayGate(base);
 assert.equal(await gate.verify(null),false);
 assert.equal(received,null);
});
