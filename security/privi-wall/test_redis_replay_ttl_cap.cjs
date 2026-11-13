'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {createRedisReplayAdmission}=require('./redis_replay_admission.cjs');
const key='b'.repeat(64);
test('rejects excessive replay key lifetime without writing',async()=>{
 let calls=0;
 const admit=createRedisReplayAdmission({async set(){calls++;return 'OK';}});
 assert.equal(await admit({key,expiresAtMs:Date.now()+3600000}),false);
 assert.equal(calls,0);
});
test('allows policy-bounded lifetime and forwards absolute expiration',async()=>{
 const calls=[];
 const admit=createRedisReplayAdmission({async set(...args){calls.push(args);return 'OK';}},{maxTtlMs:120000});
 const expiresAtMs=Date.now()+60000;
 assert.equal(await admit({key,expiresAtMs}),true);
 assert.equal(calls.length,1);
 assert.deepEqual(calls[0][2],{NX:true,PXAT:expiresAtMs});
});
test('rejects invalid maximum TTL policy',()=>{
 const client={set(){}};
 for(const maxTtlMs of [0,-1,1.5,NaN,86400001,'60000']){
   assert.throws(()=>createRedisReplayAdmission(client,{maxTtlMs}),TypeError);
 }
});
test('rejects deadline exactly at or before current time',async()=>{
 let calls=0;const admit=createRedisReplayAdmission({async set(){calls++;return 'OK';}});
 assert.equal(await admit({key,expiresAtMs:Date.now()-100}),false);
 assert.equal(calls,0);
});
