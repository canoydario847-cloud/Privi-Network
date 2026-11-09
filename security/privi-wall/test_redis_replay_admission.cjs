'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {createRedisReplayAdmission}=require('./redis_replay_admission.cjs');
const key='a'.repeat(64);
test('one winner across concurrent callers using atomic shared store',async()=>{
 const seen=new Set();const client={async set(k,v,opts){
   assert.equal(v,'1');assert.equal(opts.NX,true);
   assert.ok(opts.PXAT>Date.now());if(seen.has(k))return null;seen.add(k);return 'OK';
 }};
 const admit=createRedisReplayAdmission(client);
 const expiresAtMs=Date.now()+60000;
 const results=await Promise.all(Array.from({length:30},()=>admit({key,expiresAtMs})));
 assert.equal(results.filter(Boolean).length,1);
});
test('backend failure denies admission',async()=>{
 const admit=createRedisReplayAdmission({set:async()=>{throw Error('offline')}});
 assert.equal(await admit({key,expiresAtMs:Date.now()+60000}),false);
});
test('unexpected backend return fails closed',async()=>{
 const admit=createRedisReplayAdmission({set:async()=>true});
 assert.equal(await admit({key,expiresAtMs:Date.now()+60000}),false);
});
test('invalid key and expired deadline do not contact Redis',async()=>{
 let calls=0;const admit=createRedisReplayAdmission({set:async()=>{calls++;return 'OK'}});
 assert.equal(await admit({key:'bad',expiresAtMs:Date.now()+60000}),false);
 assert.equal(await admit({key,expiresAtMs:Date.now()-1}),false);
 assert.equal(calls,0);
});
test('invalid client and unsafe prefix rejected',()=>{
 assert.throws(()=>createRedisReplayAdmission({}),TypeError);
 assert.throws(()=>createRedisReplayAdmission({set(){}},{prefix:'bad key'}),TypeError);
});
