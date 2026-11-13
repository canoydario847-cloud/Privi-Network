'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {validateReplayPolicy}=require('./validate_replay_policy.cjs');
test('accepts policy when replay retention covers receipt horizon',()=>{
 const policy=validateReplayPolicy({maxAgeMs:300000,maxFutureSkewMs:30000,maxReplayTtlMs:600000});
 assert.equal(policy.requiredTtlMs,330001);
 assert.equal(Object.isFrozen(policy),true);
});
test('rejects TTL shorter than possible receipt acceptance horizon',()=>{
 assert.throws(()=>validateReplayPolicy({maxAgeMs:300000,maxFutureSkewMs:30000,maxReplayTtlMs:300000}),RangeError);
});
test('requires the final inclusive millisecond of replay retention',()=>{
 assert.throws(()=>validateReplayPolicy({maxAgeMs:1,maxFutureSkewMs:0,maxReplayTtlMs:1}),RangeError);
 assert.equal(validateReplayPolicy({maxAgeMs:1,maxFutureSkewMs:0,maxReplayTtlMs:2}).requiredTtlMs,2);
});
test('rejects unsafe, negative, or excessive configuration',()=>{
 for(const value of [-1,NaN,Infinity,1.5,'100',Number.MAX_SAFE_INTEGER]){
  assert.throws(()=>validateReplayPolicy({maxAgeMs:value,maxFutureSkewMs:0,maxReplayTtlMs:600000}));
 }
 assert.throws(()=>validateReplayPolicy({maxAgeMs:1,maxFutureSkewMs:30001,maxReplayTtlMs:600000}));
 assert.throws(()=>validateReplayPolicy({maxAgeMs:1,maxFutureSkewMs:0,maxReplayTtlMs:86400001}));
});
