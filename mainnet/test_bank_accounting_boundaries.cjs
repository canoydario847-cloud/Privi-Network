'use strict';
// Offline financial-genesis accounting boundary regression tests.
// These tests do not authorize launch or validate runtime monetary rules.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {auditSupplyManifest}=require('./audit_supply_manifest.cjs');
const MAX=(1n<<256n)-1n;
const genesis=()=>({app_state:{bank:{balances:[{address:'addr1',coins:[{denom:'aprvi',amount:'100'}]}],supply:[{denom:'aprvi',amount:'100'}]}}});
const manifest=()=>({denom:'aprvi',expectedSupply:'100',maxSupply:'1000'});
test('accepts a minimal exactly reconciled bank supply',()=>{
 assert.deepEqual(auditSupplyManifest(genesis(),manifest()),[]);
});
test('rejects 79-digit monetary input before BigInt parsing',()=>{
 const g=genesis();g.app_state.bank.balances[0].coins[0].amount='9'.repeat(79);
 assert.ok(auditSupplyManifest(g,manifest()).some(e=>e.includes('invalid bank balance coin')));
});
test('rejects a 78-digit uint256 overflow',()=>{
 const g=genesis();g.app_state.bank.balances[0].coins[0].amount=(MAX+1n).toString();
 assert.ok(auditSupplyManifest(g,manifest()).some(e=>e.includes('invalid bank balance coin')));
});
test('rejects negative, fractional and scientific notation monetary strings',()=>{
 for(const amount of ['-1','1.0','1e2','+1','01',' 1']){
  const g=genesis();g.app_state.bank.supply[0].amount=amount;
  assert.ok(auditSupplyManifest(g,manifest()).some(e=>e.includes('invalid supply coin')),amount);
 }
});
test('rejects supply manifest whose expected amount exceeds cap',()=>{
 const m=manifest();m.expectedSupply='100';m.maxSupply='99';
 assert.ok(auditSupplyManifest(genesis(),m).some(e=>e.includes('manifest expectedSupply exceeds cap')));
});
test('rejects control characters in bank account identifiers',()=>{
 const g=genesis();g.app_state.bank.balances[0].address='addr\\n1'.replace('\\n','\n');
 assert.ok(auditSupplyManifest(g,manifest()).some(e=>e.includes('invalid or duplicate bank balance address')));
});
test('rejects absent manifest denomination even with balanced bank supply',()=>{
 const m=manifest();m.denom='uprvi';
 assert.ok(auditSupplyManifest(genesis(),m).some(e=>e.includes('manifest denomination missing')));
});
