'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {createSessionBoundAgentGate}=require('./create_session_bound_agent_gate.cjs');
function setup(state) {
  let calls=0;
  const gate=createSessionBoundAgentGate({
    verifySession:async()=>state,
    admitSignedCall:async()=>{calls++;return true;},
    clock:()=>1000
  });
  return {gate,get calls(){return calls;}};
}
test('active unexpired session admits through signed-call verifier',async()=>{
  const x=setup({active:true,expiresAtMs:1001});
  assert.equal(await x.gate.authorize({session:'server-session',request:{}}),true);
  assert.equal(x.calls,1);
});
test('expired session rejected before signed-call verification',async()=>{
  const x=setup({active:true,expiresAtMs:1000});
  assert.equal(await x.gate.authorize({}),false);assert.equal(x.calls,0);
});
test('revoked session rejected',async()=>{
  const x=setup({active:false,expiresAtMs:2000});
  assert.equal(await x.gate.authorize({}),false);assert.equal(x.calls,0);
});
test('missing trusted expiry rejected',async()=>{
  const x=setup({active:true});
  assert.equal(await x.gate.authorize({}),false);assert.equal(x.calls,0);
});
test('accessor-based expiry rejected without invoking getter',async()=>{
  let reads=0;const state={active:true};
  Object.defineProperty(state,'expiresAtMs',{get(){reads++;return 2000;}});
  const x=setup(state);
  assert.equal(await x.gate.authorize({}),false);assert.equal(reads,0);assert.equal(x.calls,0);
});
test('session validation failure rejects',async()=>{
  const gate=createSessionBoundAgentGate({verifySession:async()=>{throw Error('offline');},admitSignedCall:async()=>true});
  assert.equal(await gate.authorize({}),false);
});
test('non-boolean admission result rejects',async()=>{
  const gate=createSessionBoundAgentGate({verifySession:async()=>({active:true,expiresAtMs:2000}),admitSignedCall:async()=>1,clock:()=>1000});
  assert.equal(await gate.authorize({}),false);
});

test('revocation during asynchronous admission rejects before execution',async()=>{
  let checks=0;
  const gate=createSessionBoundAgentGate({
    verifySession:async()=>({active:++checks===1,expiresAtMs:2000}),
    admitSignedCall:async()=>true,clock:()=>1000
  });
  assert.equal(await gate.authorize({session:'s',request:{}}),false);
  assert.equal(checks,2);
});
test('expiry during asynchronous admission rejects',async()=>{
  let now=1000;
  const gate=createSessionBoundAgentGate({
    verifySession:async()=>({active:true,expiresAtMs:1002}),
    admitSignedCall:async()=>{now=1002;return true;},clock:()=>now
  });
  assert.equal(await gate.authorize({}),false);
});
test('revalidation backend failure rejects',async()=>{
  let checks=0;
  const gate=createSessionBoundAgentGate({
    verifySession:async()=>{if(++checks===2)throw Error('session store unavailable');return {active:true,expiresAtMs:2000};},
    admitSignedCall:async()=>true,clock:()=>1000
  });
  assert.equal(await gate.authorize({}),false);
});
test('valid session is checked before and after admission',async()=>{
  let checks=0;
  const gate=createSessionBoundAgentGate({
    verifySession:async()=>{checks++;return {active:true,expiresAtMs:2000};},
    admitSignedCall:async()=>true,clock:()=>1000
  });
  assert.equal(await gate.authorize({}),true);
  assert.equal(checks,2);
});
