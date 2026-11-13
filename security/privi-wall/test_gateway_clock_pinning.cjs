'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const Module=require('node:module');
const originalLoad=Module._load;
let observed;
Module._load=function(request,parent,isMain){
 if(parent && parent.filename.endsWith('/create_gateway_replay_gate.cjs') && request==='./verify_once_tenant_receipt.cjs')
  return {verifyOnceTenantReceipt:async options=>{observed=options;return true;}};
 return originalLoad.apply(this,arguments);
};
const {createGatewayReplayGate}=require('./create_gateway_replay_gate.cjs');
Module._load=originalLoad;
const gate=createGatewayReplayGate({client:{set:async()=> 'OK'},maxAgeMs:100,maxFutureSkewMs:10,maxReplayTtlMs:111});
test('pins gateway clock instead of accepting a caller supplied future clock',async()=>{
 const before=Date.now();
 assert.equal(await gate.verify({nowMs:before+86400000}),true);
 const after=Date.now();
 assert.ok(observed.nowMs>=before && observed.nowMs<=after);
});
test('pins gateway clock instead of accepting a caller supplied past clock',async()=>{
 const before=Date.now();
 assert.equal(await gate.verify({nowMs:0}),true);
 assert.ok(observed.nowMs>=before && observed.nowMs<=Date.now());
});
test('ignores a nonnumeric caller supplied clock',async()=>{
 const before=Date.now();
 assert.equal(await gate.verify({nowMs:'untrusted'}),true);
 assert.ok(Number.isSafeInteger(observed.nowMs));
 assert.ok(observed.nowMs>=before && observed.nowMs<=Date.now());
});
