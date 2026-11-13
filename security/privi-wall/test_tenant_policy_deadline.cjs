'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {authorizeTenantActionWithDeadline: check} = require('./tenant_policy_deadline.cjs');
const context = {tenant:'tenant-a', agentId:'agent-1'};
const message = {tenant:'tenant-a', action:'agent.call'};
test('explicit allow before deadline succeeds', async () => assert.equal(await check({context,message,isAllowed:async()=>true}),true));
test('explicit deny fails closed', async () => assert.equal(await check({context,message,isAllowed:async()=>false}),false));
test('hung policy denies within bounded time', async () => {
  const start = performance.now();
  assert.equal(await check({context,message,isAllowed:()=>new Promise(()=>{}),timeoutMs:15}),false);
  assert.ok(performance.now()-start<1000);
});
test('policy rejection denies', async () => assert.equal(await check({context,message,isAllowed:async()=>{throw Error('offline')}}),false));
test('cross tenant denies without calling policy', async () => {
  let called=false;
  assert.equal(await check({context,message:{...message,tenant:'tenant-b'},isAllowed:()=>{called=true;return true}}),false);
  assert.equal(called,false);
});
test('invalid deadlines deny without invoking policy', async () => {
  for (const timeoutMs of [0,-1,NaN,Infinity,30001,1.2]) {
    let called=false;
    assert.equal(await check({context,message,timeoutMs,isAllowed:()=>{called=true;return true}}),false);
    assert.equal(called,false);
  }
});
test('ambiguous policy decision denies', async () => assert.equal(await check({context,message,isAllowed:async()=>1}),false));
