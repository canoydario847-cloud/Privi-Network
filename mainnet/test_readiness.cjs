'use strict';const {test}=require('node:test');const assert=require('node:assert/strict');const {check}=require('./readiness.cjs');
const valid=()=>({chain_id:'privi-mainnet-1',genesis_sha256:'a'.repeat(64),binary_sha256:'b'.repeat(64),validator_signoffs:[1,2,3,4].map(i=>({validator_id:'v'+i,signature_reference:'signed-evidence-'+i})),audit_approval:'signed audit record',rehearsal_report:'rehearsal evidence',rollback_plan:'rollback evidence'});
test('reject missing evidence',()=>assert.ok(check({}).length>0));
test('accept structurally complete manifest only',()=>assert.deepEqual(check(valid()),[]));
test('reject duplicate validator identities',()=>{const x=valid();x.validator_signoffs[1].validator_id='v1';assert.ok(check(x).some(e=>e.includes('validator')))});
test('reject malformed binary digest',()=>{const x=valid();x.binary_sha256='bad';assert.ok(check(x).some(e=>e.includes('binary')))});
test('reject absent audit',()=>{const x=valid();x.audit_approval='';assert.ok(check(x).some(e=>e.includes('audit')))});
