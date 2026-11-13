'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {enforceAsyncActiveSession} = require('./async_active_session_guard.cjs');
const context = Object.freeze({agentId:'a',tenant:'t',audience:'privi-agent',expiresAt:2000});
const socket = () => {const closed=[];return {closed,close:(...args)=>closed.push(args)};};
test('explicit async not-revoked authorizes',async()=>{const s=socket();assert.equal(await enforceAsyncActiveSession({socket:s,context,now:1000,isRevoked:async()=>false}),true);assert.equal(s.closed.length,0);});
test('revoked agent denied and closed',async()=>{const s=socket();assert.equal(await enforceAsyncActiveSession({socket:s,context,now:1000,isRevoked:async()=>true}),false);assert.equal(s.closed[0][0],1008);});
test('rejected revocation backend fails closed',async()=>{const s=socket();assert.equal(await enforceAsyncActiveSession({socket:s,context,now:1000,isRevoked:async()=>{throw Error('offline');}}),false);assert.equal(s.closed.length,1);});
test('never resolving revocation backend times out',async()=>{const s=socket();assert.equal(await enforceAsyncActiveSession({socket:s,context,now:1000,timeoutMs:5,isRevoked:()=>new Promise(()=>{})}),false);assert.equal(s.closed[0][0],1008);});
test('missing authority, ambiguous results and expired session deny',async()=>{for(const opts of [{},{isRevoked:async()=>undefined},{isRevoked:async()=>0},{isRevoked:async()=>false,now:2000}]){const s=socket();assert.equal(await enforceAsyncActiveSession({socket:s,context,now:1000,...opts}),false);assert.equal(s.closed.length,1);}});
test('invalid timeout and socket close failure deny',async()=>{const s={close(){throw Error('closed');}};assert.equal(await enforceAsyncActiveSession({socket:s,context,now:1000,timeoutMs:0,isRevoked:async()=>false}),false);});

test('revocation response after credential expiry is denied', async () => {
  const s = socket();
  const result = await enforceAsyncActiveSession({
    socket:s, context:{...context,expiresAt:1015}, now:1000,
    timeoutMs:100, isRevoked:()=>new Promise(resolve=>setTimeout(()=>resolve(false),30))
  });
  assert.equal(result,false);
  assert.equal(s.closed[0][0],1008);
});
test('fast revocation response before credential expiry is allowed', async () => {
  const s = socket();
  const result = await enforceAsyncActiveSession({
    socket:s, context:{...context,expiresAt:1100}, now:1000,
    timeoutMs:200, isRevoked:async()=>false
  });
  assert.equal(result,true);
  assert.equal(s.closed.length,0);
});
