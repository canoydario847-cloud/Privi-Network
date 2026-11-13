'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {auditSupplyManifest}=require('./audit_supply_manifest.cjs');
const MAX=((1n<<256n)-1n).toString();
const genesis=()=>({app_state:{bank:{balances:[{address:'a',coins:[{denom:'aprvi',amount:'100'}]}],supply:[{denom:'aprvi',amount:'100'}]}}});
const manifest=()=>({denom:'aprvi',expectedSupply:'100',maxSupply:'1000'});
test('rejects duplicate balance address even when totals appear correct',()=>{
 const g=genesis();g.app_state.bank.balances.push({address:'a',coins:[]});
 assert.ok(auditSupplyManifest(g,manifest()).some(e=>e.includes('duplicate bank balance address')));
});
test('rejects duplicate coin denomination within an account',()=>{
 const g=genesis();g.app_state.bank.balances[0].coins.push({denom:'aprvi',amount:'0'});
 assert.ok(auditSupplyManifest(g,manifest()).some(e=>e.includes('duplicate balance denom')));
});
test('rejects duplicate supply denomination',()=>{
 const g=genesis();g.app_state.bank.supply.push({denom:'aprvi',amount:'0'});
 assert.ok(auditSupplyManifest(g,manifest()).some(e=>e.includes('duplicate supply denom')));
});
test('rejects aggregate balance overflow even when each coin fits uint256',()=>{
 const g=genesis();
 g.app_state.bank.balances=[{address:'a',coins:[{denom:'aprvi',amount:MAX}]},{address:'b',coins:[{denom:'aprvi',amount:'1'}]}];
 g.app_state.bank.supply=[{denom:'aprvi',amount:MAX}];
 assert.ok(auditSupplyManifest(g,{denom:'aprvi',expectedSupply:MAX,maxSupply:MAX}).some(e=>e.includes('bank balance sum exceeds uint256')));
});
test('rejects unbacked nonzero supply in an unrelated denomination',()=>{
 const g=genesis();g.app_state.bank.supply.push({denom:'other',amount:'1'});
 assert.ok(auditSupplyManifest(g,manifest()).some(e=>e.includes('unbacked supply other')));
});
test('rejects malformed bank balances without throwing',()=>{
 const g=genesis();g.app_state.bank.balances=null;
 assert.ok(auditSupplyManifest(g,manifest()).length>0);
});
