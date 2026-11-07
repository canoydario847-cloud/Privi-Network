'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const crypto=require('node:crypto');
const {verify}=require('./verify_artifacts.cjs');
const digest=x=>crypto.createHash('sha256').update(x).digest('hex');
function fixture(fn){
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'privi-integrity-'));
 try{
  const genesis=path.join(dir,'genesis.json'),binary=path.join(dir,'validator');
  fs.writeFileSync(genesis,'{"chain_id":"privi-mainnet-1"}');fs.writeFileSync(binary,'binary-test-fixture');
  const m={chain_id:'privi-mainnet-1',genesis_sha256:digest(fs.readFileSync(genesis)),binary_sha256:digest(fs.readFileSync(binary)),validator_signoffs:[1,2,3,4].map(i=>({validator_id:'v'+i,signature_reference:'reference-'+i})),audit_approval:'reference',rehearsal_report:'reference',rollback_plan:'reference'};
  fn({m,genesis,binary,dir});
 }finally{fs.rmSync(dir,{recursive:true,force:true});}
}
test('matching local artifacts pass digest comparison only',()=>fixture(x=>assert.deepEqual(verify(x.m,x),[])));
test('tampered genesis fails closed',()=>fixture(x=>{fs.appendFileSync(x.genesis,'x');assert.ok(verify(x.m,x).some(e=>e.includes('genesis_sha256')))}));
test('tampered binary fails closed',()=>fixture(x=>{fs.appendFileSync(x.binary,'x');assert.ok(verify(x.m,x).some(e=>e.includes('binary_sha256')))}));
test('missing artifact fails closed',()=>fixture(x=>{fs.unlinkSync(x.binary);assert.ok(verify(x.m,x).some(e=>e.includes('unreadable artifact')))}));
test('symlink artifacts rejected',()=>fixture(x=>{const link=path.join(x.dir,'link');fs.symlinkSync(x.binary,link);assert.ok(verify(x.m,{genesis:x.genesis,binary:link}).some(e=>e.includes('regular file')))}));
test('invalid manifest fails before artifact comparison',()=>fixture(x=>{x.m.audit_approval='';assert.ok(verify(x.m,x).some(e=>e.includes('audit')))}));

test('matching hash but wrong genesis chain ID fails closed',()=>fixture(x=>{
 fs.writeFileSync(x.genesis,JSON.stringify({chain_id:'privi-other-1'}));
 x.m.genesis_sha256=digest(fs.readFileSync(x.genesis));
 assert.ok(verify(x.m,x).some(e=>e.includes('genesis chain_id')));
}));
test('matching hash but malformed genesis JSON fails closed',()=>fixture(x=>{
 fs.writeFileSync(x.genesis,'not-json');
 x.m.genesis_sha256=digest(fs.readFileSync(x.genesis));
 assert.ok(verify(x.m,x).some(e=>e.includes('invalid genesis JSON')));
}));
