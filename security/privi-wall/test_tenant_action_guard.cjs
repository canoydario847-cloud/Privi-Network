'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {authorizeTenantAction}=require('./tenant_action_guard.cjs');
const context={agentId:'agent1',tenant:'tenant-a'};
const message={tenant:'tenant-a',action:'tools.invoke'};
const run=(overrides={})=>authorizeTenantAction({context,message,isAllowed:async()=>true,...overrides});
test('authorized tenant and action passes',async()=>assert.equal(await run(),true));
test('cross-tenant message denied without policy invocation',async()=>{
  let called=false;
  assert.equal(await run({message:{...message,tenant:'tenant-b'},isAllowed:()=>{called=true;return true;}}),false);
  assert.equal(called,false);
});
test('missing claimed tenant denied',async()=>assert.equal(await run({message:{action:'tools.invoke'}}),false));
test('untrusted missing authenticated tenant denied',async()=>assert.equal(await run({context:{agentId:'agent1'}}),false));
test('invalid action denied',async()=>assert.equal(await run({message:{...message,action:'../admin'}}),false));
test('missing policy denied',async()=>assert.equal(await run({isAllowed:undefined}),false));
test('ambiguous policy result denied',async()=>assert.equal(await run({isAllowed:async()=>1}),false));
test('policy failure denied',async()=>assert.equal(await run({isAllowed:async()=>{throw Error('offline');}}),false));
test('policy receives only authenticated tenant, agent and action',async()=>{
 let seen;
 assert.equal(await run({isAllowed:async p=>{seen=p;return true;}}),true);
 assert.deepEqual({...seen},{tenant:'tenant-a',agentId:'agent1',action:'tools.invoke'});
 assert.equal(Object.isFrozen(seen),true);
});
