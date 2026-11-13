'use strict';
const assert = require('node:assert/strict');
const test = require('node:test');
const {check} = require('./readiness.cjs');
const good = () => ({
  chain_id:'privi-production-1',
  genesis_sha256:'a'.repeat(64),
  binary_sha256:'b'.repeat(64),
  validator_signoffs:Array.from({length:4},(_,i)=>({validator_id:'validator-'+i,signature_reference:'attestation-'+i})),
  audit_approval:'external audit reference',
  rehearsal_report:'rehearsal reference',
  rollback_plan:'rollback reference'
});
test('structurally complete manifest remains advisory',()=>assert.deepEqual(check(good()),[]));
test('rejects inherited evidence keys',()=>{
  const m=Object.create({audit_approval:'inherited'});
  Object.assign(m,good()); delete m.audit_approval;
  assert.ok(check(m).some(e=>e.includes('missing audit_approval')));
});
test('rejects blank signoffs and duplicate validator ids',()=>{
  const m=good();m.validator_signoffs[0].signature_reference='  ';
  assert.ok(check(m).some(e=>e.includes('signoff')));
  m.validator_signoffs[0].signature_reference='attestation';
  m.validator_signoffs[1].validator_id=m.validator_signoffs[0].validator_id;
  assert.ok(check(m).some(e=>e.includes('signoff')));
});
test('rejects non-object validator signoffs and malformed release hashes',()=>{
 const m=good();m.validator_signoffs[0]='string entry';m.binary_sha256='not-a-hash';
 const errors=check(m);
 assert.ok(errors.some(e=>e.includes('signoff')));
 assert.ok(errors.some(e=>e.includes('binary_sha256')));
});
test('rejects missing evidence and never accepts a list as manifest',()=>{
 const m=good();m.rollback_plan=' ';
 assert.ok(check(m).some(e=>e.includes('rollback_plan')));
 assert.ok(check([]).length>0);
});
