'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {auditSupplyManifest}=require('./audit_supply_manifest.cjs');
const genesis=()=>({app_state:{bank:{balances:[{address:'a',coins:[{denom:'aprvi',amount:'100'}]}],supply:[{denom:'aprvi',amount:'100'}]}}});
const manifest=()=>({denom:'aprvi',expectedSupply:'100',maxSupply:'1000'});
test('matching supply and cap',()=>assert.deepEqual(auditSupplyManifest(genesis(),manifest()),[]));
test('missing manifest fails',()=>assert.ok(auditSupplyManifest(genesis(),null).length));
test('supply mismatch fails',()=>{const m=manifest();m.expectedSupply='99';assert.ok(auditSupplyManifest(genesis(),m).some(x=>x.includes('differs')));});
test('cap breach fails',()=>{const m=manifest();m.maxSupply='99';assert.ok(auditSupplyManifest(genesis(),m).some(x=>x.includes('exceeds')));});
test('missing denomination fails',()=>{const m=manifest();m.denom='other';assert.ok(auditSupplyManifest(genesis(),m).length);});
test('malformed numeric cap fails',()=>{const m=manifest();m.maxSupply='1e3';assert.ok(auditSupplyManifest(genesis(),m).length);});
test('malformed identifier fails',()=>{const m=manifest();m.denom='a prvi';assert.ok(auditSupplyManifest(genesis(),m).length);});
test('bank mismatch fails even if manifest matches supply',()=>{const g=genesis();g.app_state.bank.balances[0].coins[0].amount='99';assert.ok(auditSupplyManifest(g,manifest()).length);});

test('rejects expected supply above uint256 maximum',()=>{const m=manifest();m.expectedSupply=(1n<<256n).toString();assert.ok(auditSupplyManifest(genesis(),m).some(x=>x.includes('expectedSupply')));});
test('rejects cap above uint256 maximum',()=>{const m=manifest();m.maxSupply=(1n<<256n).toString();assert.ok(auditSupplyManifest(genesis(),m).some(x=>x.includes('maxSupply')));});
test('accepts uint256 maximum as a syntactically valid cap',()=>{const m=manifest();m.maxSupply=((1n<<256n)-1n).toString();assert.deepEqual(auditSupplyManifest(genesis(),m),[]);});
test('rejects bank supply above uint256 maximum',()=>{const g=genesis();const amount=(1n<<256n).toString();g.app_state.bank.supply[0].amount=amount;g.app_state.bank.balances[0].coins[0].amount=amount;assert.ok(auditSupplyManifest(g,manifest()).some(x=>x.includes('uint256')));});
test('rejects excessive decimal digit strings before bigint parsing',()=>{const m=manifest();m.maxSupply='9'.repeat(100000);assert.ok(auditSupplyManifest(genesis(),m).some(x=>x.includes('maxSupply')));});

test('rejects oversized expected supply before numeric conversion',()=>{const m=manifest();m.expectedSupply='9'.repeat(100000);assert.ok(auditSupplyManifest(genesis(),m).some(x=>x.includes('expectedSupply')));});
test('rejects overlength zero-padded cap before numeric conversion',()=>{const m=manifest();m.maxSupply='0'.repeat(100000);assert.ok(auditSupplyManifest(genesis(),m).some(x=>x.includes('maxSupply')));});
