'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {authorizeWebSocketUpgrade} = require('./websocket_upgrade_gate.cjs');
const opts = {request:{headers:{origin:'https://app.privi.example'}}, allowedOrigins:['https://app.privi.example'], expectedTenant:'tenant-1', expectedAudience:'privi-agent', authenticate:async()=>({authenticated:true,tenant:'tenant-1',audience:'privi-agent',agentId:'agent-1'})};
test('accepts authenticated, tenant-and-audience-bound upgrade',async()=>{
  const p=await authorizeWebSocketUpgrade(opts);
  assert.deepEqual(p,{agentId:'agent-1',tenant:'tenant-1',audience:'privi-agent'});
  assert.equal(Object.isFrozen(p),true);
});
test('rejects untrusted origin before calling authentication',async()=>{
  let called=false;
  await assert.rejects(authorizeWebSocketUpgrade({...opts,request:{headers:{origin:'https://evil.example'}},authenticate:async()=>{called=true;return {};}}),/origin rejected/);
  assert.equal(called,false);
});
test('rejects missing auth callback and trusted context',async()=>{
  await assert.rejects(authorizeWebSocketUpgrade({...opts,authenticate:null}),/authentication required/);
  await assert.rejects(authorizeWebSocketUpgrade({...opts,expectedTenant:''}),/trusted context required/);
});
test('rejects tenant, audience and unauthenticated mismatches',async()=>{
  for(const principal of [{authenticated:false,tenant:'tenant-1',audience:'privi-agent',agentId:'a'},{authenticated:true,tenant:'tenant-2',audience:'privi-agent',agentId:'a'},{authenticated:true,tenant:'tenant-1',audience:'other',agentId:'a'},null])
    await assert.rejects(authorizeWebSocketUpgrade({...opts,authenticate:async()=>principal}),/upgrade unauthorized/);
});
test('propagates authentication failures closed',async()=>{
  await assert.rejects(authorizeWebSocketUpgrade({...opts,authenticate:async()=>{throw Error('expired');}}),/expired/);
});
