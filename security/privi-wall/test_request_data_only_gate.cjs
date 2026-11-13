'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {createTrustedTenantGate}=require('./create_trusted_tenant_gate.cjs');
const identity={tenantId:'tenant_1',agentId:'agent_1',actionId:'run_1',resolveTenantKey:()=>Buffer.from('key')};
function setup() {
  let calls=0;
  const gate=createTrustedTenantGate({
    gate:{verify:async()=>{calls++;return true;}},
    resolveIdentity:async()=>identity
  });
  return {gate,get calls(){return calls;}};
}
const good=()=>({receipt:'signed',signature:'sig',algorithm:'ed25519'});
test('valid own data fields are accepted by trusted verifier',async()=>{
  const x=setup();assert.equal(await x.gate.verify({request:good(),session:{}}),true);assert.equal(x.calls,1);
});
test('inherited receipt fields cannot authorize calls',async()=>{
  const x=setup();const request=Object.create(good());
  assert.equal(await x.gate.verify({request,session:{}}),false);assert.equal(x.calls,0);
});
test('request accessors are rejected without execution',async()=>{
  const x=setup();let reads=0;
  const request=good();
  Object.defineProperty(request,'signature',{enumerable:true,get(){reads++;return 'sig';}});
  assert.equal(await x.gate.verify({request,session:{}}),false);
  assert.equal(reads,0);assert.equal(x.calls,0);
});
test('throwing proxy descriptor traps fail closed',async()=>{
  const x=setup();
  const request=new Proxy(good(),{getOwnPropertyDescriptor(){throw Error('malformed');}});
  assert.equal(await x.gate.verify({request,session:{}}),false);assert.equal(x.calls,0);
});
