'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {generateKeyPairSync,sign}=require('node:crypto');
const {canonicalPolicy}=require('./verify_signed_policy.cjs');
const {auditSignedGenesis}=require('./audit_signed_genesis.cjs');
const {publicKey,privateKey}=generateKeyPairSync('ed25519');
const trust={chainId:'privi-1',minVersion:2,denom:'aprvi',maxSupply:'1000',trustedKeys:{root:publicKey.export({type:'spki',format:'pem'})}};
const policy={chainId:'privi-1',denom:'aprvi',maxSupply:'1000',version:2};
const envelope=()=>({keyId:'root',policy:{...policy},signature:sign(null,canonicalPolicy(policy),privateKey).toString('base64')});
const genesis=()=>({chain_id:'privi-1',app_state:{bank:{balances:[{address:'alice',coins:[{denom:'aprvi',amount:'100'}]}],supply:[{denom:'aprvi',amount:'100'}]}}});
test('accepts signed monetary policy and valid genesis bank',()=>assert.deepEqual(auditSignedGenesis(genesis(),envelope(),trust),[]));
test('rejects unsigned policy despite approved flag',()=>assert.match(auditSignedGenesis(genesis(),{policy:{...policy,approved:true}},trust)[0],/unauthorized/));
test('rejects modified supply cap after signing',()=>{const e=envelope();e.policy.maxSupply='2000';assert.match(auditSignedGenesis(genesis(),e,trust)[0],/unauthorized/);});
test('rejects genesis chain mismatch',()=>{const g=genesis();g.chain_id='other';assert.match(auditSignedGenesis(g,envelope(),trust)[0],/chain identifier/);});
test('rejects missing trust configuration',()=>assert.match(auditSignedGenesis(genesis(),envelope(),null)[0],/trusted/));
test('rejects supply above signed cap',()=>{const g=genesis();g.app_state.bank.supply[0].amount='1001';assert.match(auditSignedGenesis(g,envelope(),trust)[0],/exceeds/);});
test('rejects obsolete policy version',()=>assert.match(auditSignedGenesis(genesis(),envelope(),{...trust,minVersion:3})[0],/unauthorized/));

test('rejects signed genesis with native supply larger than account balances',()=>{const g=genesis();g.app_state.bank.supply[0].amount='101';assert.ok(auditSignedGenesis(g,envelope(),trust).some(e=>e.includes('supply mismatch')));});
test('rejects signed genesis with duplicate bank balance addresses',()=>{const g=genesis();g.app_state.bank.balances.push({...g.app_state.bank.balances[0]});assert.ok(auditSignedGenesis(g,envelope(),trust).some(e=>e.includes('duplicate bank balance address')));});
test('rejects signed genesis with unbacked native supply',()=>{const g=genesis();g.app_state.bank.balances=[];assert.ok(auditSignedGenesis(g,envelope(),trust).some(e=>e.includes('unbacked supply')));});

test('rejects correctly signed but independently unauthorized supply cap',()=>{
 const p={...policy,maxSupply:'2000'};
 const e={keyId:'root',policy:p,signature:sign(null,canonicalPolicy(p),privateKey).toString('base64')};
 assert.match(auditSignedGenesis(genesis(),e,trust).join(';'),/independently authorized/);
});
test('rejects correctly signed but independently unauthorized denomination',()=>{
 const p={...policy,denom:'other'};
 const e={keyId:'root',policy:p,signature:sign(null,canonicalPolicy(p),privateKey).toString('base64')};
 assert.match(auditSignedGenesis(genesis(),e,trust).join(';'),/independently authorized/);
});
test('rejects missing independently authorized supply cap',()=>{
 const {maxSupply,...missing}=trust;
 assert.match(auditSignedGenesis(genesis(),envelope(),missing).join(';'),/missing trusted/);
});
test('rejects malformed independently authorized supply cap',()=>{
 assert.match(auditSignedGenesis(genesis(),envelope(),{...trust,maxSupply:'01000'}).join(';'),/missing trusted/);
});
test('rejects missing independently authorized denomination',()=>{
 const {denom,...missing}=trust;
 assert.match(auditSignedGenesis(genesis(),envelope(),missing).join(';'),/missing trusted/);
});

test('rejects signed genesis with unauthorized balance denomination',()=>{
 const g=genesis();g.app_state.bank.balances[0].coins.push({denom:'other',amount:'1'});
 g.app_state.bank.supply.push({denom:'other',amount:'1'});
 assert.ok(auditSignedGenesis(g,envelope(),trust).some(e=>e.includes('unauthorized balance denomination')));
});
test('rejects signed genesis with missing native supply',()=>{
 const g=genesis();g.app_state.bank.supply=[];
 assert.ok(auditSignedGenesis(g,envelope(),trust).some(e=>e.includes('missing native supply')));
});
test('rejects signed genesis with duplicate native supply entries',()=>{
 const g=genesis();g.app_state.bank.supply.push({denom:'aprvi',amount:'100'});
 assert.ok(auditSignedGenesis(g,envelope(),trust).some(e=>e.includes('duplicate supply')));
});
