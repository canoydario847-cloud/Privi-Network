'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {createTrustedExecutionContextGate}=require('./create_trusted_execution_context_gate.cjs');
const trusted=()=>({tenantId:'tenant-a',agentId:'agent-a',actionId:'read',sessionId:'session-a'});
test('request cannot override trusted execution identity',async()=>{
 let seen;
 const gate=createTrustedExecutionContextGate({resolveTrustedContext:trusted,authorize:async ({session})=>{seen=session;return true;},executeAuthorized:async()=>({ok:true})});
 assert.equal((await gate.execute({request:{tenantId:'attacker',agentId:'attacker',actionId:'delete'}})).ok,true);
 assert.deepEqual(seen,{tenantId:'tenant-a',agentId:'agent-a',actionId:'read',sessionId:'session-a'});
 assert.equal(Object.isFrozen(seen),true);
});
test('missing trusted identity fails closed before authorization',async()=>{
 let calls=0;
 const gate=createTrustedExecutionContextGate({resolveTrustedContext:()=>({tenantId:'t'}),authorize:async()=>{calls++;return true;},executeAuthorized:async()=>({ok:true})});
 assert.deepEqual(await gate.execute({request:{tenantId:'t'}}),{ok:false,reason:'untrusted_context'});
 assert.equal(calls,0);
});
test('accessor identity never executes getter',async()=>{
 let reads=0;const ctx=trusted();Object.defineProperty(ctx,'tenantId',{get(){reads++;return 't';}});
 const gate=createTrustedExecutionContextGate({resolveTrustedContext:()=>ctx,authorize:async()=>true,executeAuthorized:async()=>({ok:true})});
 assert.equal((await gate.execute({})).ok,false);assert.equal(reads,0);
});
test('resolver errors fail closed',async()=>{
 const gate=createTrustedExecutionContextGate({resolveTrustedContext:async()=>{throw Error('unavailable');},authorize:async()=>true,executeAuthorized:async()=>({ok:true})});
 assert.equal((await gate.execute({})).ok,false);
});
test('execution-time backend denial remains final',async()=>{
 const gate=createTrustedExecutionContextGate({resolveTrustedContext:trusted,authorize:async()=>true,executeAuthorized:async()=>({ok:false})});
 assert.deepEqual(await gate.execute({}),{ok:false,reason:'executor_denied'});
});
