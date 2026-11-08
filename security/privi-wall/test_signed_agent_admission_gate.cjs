'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {admitAgentCall:admit}=require('./signed_agent_admission_gate.cjs');
const envelope={tenant:'t1',agent:'agent1',action:'run',nonce:'a'.repeat(32),expiresAt:2000};
function fixture(overrides={}){
 const events=[],seen=new Set();
 return {events, args:{sessionTenant:'t1',envelope,
   verifySignature:async()=>{events.push('verify');return true;},
   authorizeAction:async()=>{events.push('authorize');return true;},
   reserve:async k=>{events.push('reserve');if(seen.has(k))return false;seen.add(k);return true;},
   clock:()=>1000,...overrides}};
}
test('successful ordered gate, then replay denied',async()=>{
 const f=fixture();assert.equal(await admit(f.args),true);
 assert.deepEqual(f.events,['verify','authorize','reserve']);
 assert.equal(await admit(f.args),false);
});
test('invalid signature never reaches policy or store',async()=>{
 const f=fixture({verifySignature:async()=>false});
 assert.equal(await admit(f.args),false);assert.deepEqual(f.events,[]);
});
test('cross tenant rejected before any callbacks',async()=>{
 const f=fixture({sessionTenant:'t2'});
 assert.equal(await admit(f.args),false);assert.deepEqual(f.events,[]);
});
test('policy denial never consumes nonce',async()=>{
 const f=fixture({authorizeAction:async()=>false});
 assert.equal(await admit(f.args),false);assert.deepEqual(f.events,['verify']);
});
test('ambiguous results fail closed',async()=>{
 for(const field of ['verifySignature','authorizeAction']){
  const f=fixture({[field]:async()=>({allowed:true})});
  assert.equal(await admit(f.args),false);assert.ok(!f.events.includes('reserve'));
 }
});
test('exceptions deny without replay admission',async()=>{
 for(const field of ['verifySignature','authorizeAction']){
  const f=fixture({[field]:async()=>{throw Error('offline')}});
  assert.equal(await admit(f.args),false);assert.ok(!f.events.includes('reserve'));
 }
});
test('invalid envelope and missing callbacks deny',async()=>{
 for(const patch of [{envelope:{...envelope,agent:'bad/name'}},{envelope:{...envelope,action:''}},
  {verifySignature:null},{authorizeAction:null},{envelope:null}]){
  const f=fixture(patch);assert.equal(await admit(f.args),false);
 }
});
test('expired signature envelope cannot reach execution',async()=>{
 const f=fixture({envelope:{...envelope,expiresAt:1000}});
 assert.equal(await admit(f.args),false);assert.deepEqual(f.events,['verify','authorize']);
});
