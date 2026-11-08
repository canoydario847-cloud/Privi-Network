'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {admitSignedAgentNonce: admit} = require('./atomic_replay_admission.cjs');
const base = {tenant:'tenant_a', nonce:'a'.repeat(32), expiresAt:2000, clock:()=>1000};
test('atomic insert admits once, duplicate denies', async()=>{
 const seen=new Set();
 const reserve=async(k,ttl)=>{assert.equal(ttl,1000);if(seen.has(k))return false;seen.add(k);return true;};
 assert.equal(await admit({...base,reserve}),true);
 assert.equal(await admit({...base,reserve}),false);
});
test('concurrent duplicate attempts only admit one',async()=>{
 const seen=new Set();
 const reserve=async k=>{if(seen.has(k))return false;seen.add(k);return true;};
 const results=await Promise.all(Array.from({length:30},()=>admit({...base,reserve})));
 assert.equal(results.filter(Boolean).length,1);
});
test('different tenants have separate replay namespaces',async()=>{
 const keys=[];
 const reserve=async k=>{keys.push(k);return true;};
 assert.equal(await admit({...base,reserve}),true);
 assert.equal(await admit({...base,tenant:'tenant_b',reserve}),true);
 assert.notEqual(keys[0],keys[1]);
});
test('expired and excessive lifetime reject before storage',async()=>{
 let called=false;const reserve=()=>{called=true;return true;};
 for(const expiresAt of [1000,999,61001,NaN,Infinity,1.5]){
  assert.equal(await admit({...base,expiresAt,reserve}),false);
 }
 assert.equal(called,false);
});
test('invalid identities and missing store deny',async()=>{
 for(const tenant of ['', 'a/b', 'a'.repeat(65)])assert.equal(await admit({...base,tenant,reserve:async()=>true}),false);
 for(const nonce of ['bad','A'.repeat(32),'z'.repeat(32)])assert.equal(await admit({...base,nonce,reserve:async()=>true}),false);
 assert.equal(await admit({...base}),false);
});
test('store errors and ambiguous acknowledgements deny',async()=>{
 for(const reserve of [async()=>{throw Error('offline')},async()=>1,async()=>undefined,async()=>({ok:true}),async()=>false]){
  assert.equal(await admit({...base,reserve}),false);
 }
});
test('invalid clock and configuration deny',async()=>{
 const reserve=async()=>true;
 assert.equal(await admit({...base,reserve,clock:()=>NaN}),false);
 assert.equal(await admit({...base,reserve,maxLifetimeMs:0}),false);
 assert.equal(await admit({...base,reserve,clock:null}),false);
});
