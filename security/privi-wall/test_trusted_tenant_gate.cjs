'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {createTrustedTenantGate}=require('./create_trusted_tenant_gate.cjs');
const trusted=()=>({tenantId:'tenantA',agentId:'agentA',actionId:'run',resolveTenantKey:()=>({})});
const request={receipt:{tenant:'tenantA'},signature:'sig',algorithm:'Ed25519'};
test('trusted identity pins tenant agent action and key resolver',async()=>{
 let seen;
 const gate=createTrustedTenantGate({gate:{verify:async o=>(seen=o,true)},resolveIdentity:async()=>trusted()});
 assert.equal(await gate.verify({request:{...request,expectedTenant:'attacker',resolveTenantKey:()=>null},session:{}}),true);
 assert.equal(seen.expectedTenant,'tenantA');
 assert.equal(seen.expectedAgent,'agentA');
 assert.equal(seen.expectedAction,'run');
 assert.equal(typeof seen.resolveTenantKey,'function');
});
test('missing authenticated identity fails closed',async()=>{
 const gate=createTrustedTenantGate({gate:{verify:async()=>true},resolveIdentity:async()=>null});
 assert.equal(await gate.verify({request}),false);
});
test('malformed trusted identity fails closed',async()=>{
 const gate=createTrustedTenantGate({gate:{verify:async()=>true},resolveIdentity:async()=>({...trusted(),tenantId:'bad/tenant'})});
 assert.equal(await gate.verify({request}),false);
});
test('missing trusted key resolver fails closed',async()=>{
 const gate=createTrustedTenantGate({gate:{verify:async()=>true},resolveIdentity:async()=>({tenantId:'t',agentId:'a',actionId:'run'})});
 assert.equal(await gate.verify({request}),false);
});
test('resolver exceptions and verifier errors fail closed',async()=>{
 const a=createTrustedTenantGate({gate:{verify:async()=>true},resolveIdentity:async()=>{throw Error('auth unavailable')}});
 const b=createTrustedTenantGate({gate:{verify:async()=>{throw Error('verify failed')}},resolveIdentity:async()=>trusted()});
 assert.equal(await a.verify({request}),false);assert.equal(await b.verify({request}),false);
});
test('only strict true permits admission',async()=>{
 const gate=createTrustedTenantGate({gate:{verify:async()=>({ok:true})},resolveIdentity:async()=>trusted()});
 assert.equal(await gate.verify({request}),false);
});

test('inherited tenant identity fields are rejected',async()=>{
 let invoked=false;
 const inherited=Object.create(trusted());
 const gate=createTrustedTenantGate({gate:{verify:async()=>{invoked=true;return true;}},resolveIdentity:async()=>inherited});
 assert.equal(await gate.verify({request}),false);
 assert.equal(invoked,false);
});
test('coercible identity objects cannot masquerade as identifiers',async()=>{
 const identity={...trusted(),tenantId:{toString:()=> 'tenantA'}};
 const gate=createTrustedTenantGate({gate:{verify:async()=>true},resolveIdentity:async()=>identity});
 assert.equal(await gate.verify({request}),false);
});
test('inherited signing-key resolver is rejected',async()=>{
 const identity=Object.assign(Object.create({resolveTenantKey:()=>({})}),{tenantId:'tenantA',agentId:'agentA',actionId:'run'});
 const gate=createTrustedTenantGate({gate:{verify:async()=>true},resolveIdentity:async()=>identity});
 assert.equal(await gate.verify({request}),false);
});
