'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {createAuthorizedExecutionBoundary}=require('./create_authorized_execution_boundary.cjs');
test('denied admission never invokes executor',async()=>{
  let calls=0;
  const gate=createAuthorizedExecutionBoundary({authorize:async()=>false,executeAuthorized:async()=>{calls++;return {ok:true};}});
  assert.equal((await gate.execute({})).ok,false);assert.equal(calls,0);
});
test('truthy non-boolean admission fails closed',async()=>{
  let calls=0;
  const gate=createAuthorizedExecutionBoundary({authorize:async()=>1,executeAuthorized:async()=>{calls++;return {ok:true};}});
  assert.equal((await gate.execute({})).ok,false);assert.equal(calls,0);
});
test('executor revocation denial is final',async()=>{
  const gate=createAuthorizedExecutionBoundary({authorize:async()=>true,executeAuthorized:async()=>({ok:false})});
  assert.deepEqual(await gate.execute({}),{ok:false,reason:'executor_denied'});
});
test('trusted executor success acknowledged',async()=>{
  let args;
  const gate=createAuthorizedExecutionBoundary({authorize:async()=>true,executeAuthorized:async x=>{args=x;return {ok:true};}});
  const request={action:'read'},session='s';
  assert.deepEqual(await gate.execute({session,request}),{ok:true});
  assert.deepEqual(args,{session,request});
});
test('executor throws and accessor results fail closed',async()=>{
  const throwing=createAuthorizedExecutionBoundary({authorize:async()=>true,executeAuthorized:async()=>{throw Error('down');}});
  assert.equal((await throwing.execute({})).ok,false);
  let reads=0;const result={};Object.defineProperty(result,'ok',{get(){reads++;return true;}});
  const accessor=createAuthorizedExecutionBoundary({authorize:async()=>true,executeAuthorized:async()=>result});
  assert.equal((await accessor.execute({})).ok,false);assert.equal(reads,0);
});
