'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { createHash } = require('node:crypto');
const { sign, createGuard } = require('./agent_call_guard.cjs');
const key = Buffer.alloc(32, 7);
const hash = createHash('sha256').update('hello').digest('hex');
let time = 1_000_000;
const base = (overrides={}) => ({tenant:'tenantA',agent:'agent1',nonce:'nonce1',timestamp:time,bodyHash:hash,bodyBytes:5,...overrides});
const signed = (req) => ({...req,signature:sign(key,req)});
const guard = (opts={}) => createGuard({getKey:(tenant,agent)=> tenant==='tenantA' && agent==='agent1' ? key : undefined,now:()=>time,...opts});
test('accepts signed call then rejects replay',()=>{
  const admit=guard(); const req=signed(base());
  assert.deepEqual(admit(req),{ok:true});
  assert.equal(admit(req).reason,'replay');
});
test('rejects cross-tenant signature and body tampering',()=>{
  const admit=guard(); const req=signed(base());
  assert.equal(admit({...req,tenant:'tenantB'}).ok,false);
  assert.equal(admit({...req,bodyHash:'0'.repeat(64)}).ok,false);
  assert.equal(admit({...req,nonce:'nonce2',bodyBytes:1_048_577}).reason,'body-size');
});
test('rejects stale timestamps and invalid signatures',()=>{
  const admit=guard();
  assert.equal(admit(signed(base({timestamp:time-60_001}))).reason,'expired');
  assert.equal(admit({...signed(base()),signature:'0'.repeat(64)}).reason,'unauthorized');
});
test('per-agent call limit is fail closed',()=>{
  const admit=guard({maxCalls:1});
  assert.equal(admit(signed(base())).ok,true);
  assert.equal(admit(signed(base({nonce:'nonce2'}))).reason,'rate-limit');
});
test('rejects ambiguous delimiter tokens',()=>{
  assert.throws(()=>sign(key,base({tenant:'tenant\nB'})),/invalid tenant/);
});
