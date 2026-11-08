'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {audit}=require('./audit_genesis_supply.cjs');
const fixture=()=>({app_state:{bank:{balances:[{address:'addr1',coins:[{denom:'aprvi',amount:'1000'}]}],supply:[{denom:'aprvi',amount:'1000'}]}}});
test('duplicate supply denomination is rejected even if total equals allocations',()=>{
 const g=fixture();g.app_state.bank.supply=[{denom:'aprvi',amount:'1000'},{denom:'aprvi',amount:'0'}];
 assert.ok(audit(g,'aprvi','1000').some(e=>e.includes('duplicate supply denom')));
});
test('negative supply is rejected',()=>{
 const g=fixture();g.app_state.bank.supply[0].amount='-1000';
 assert.ok(audit(g,'aprvi','1000').some(e=>e.includes('invalid coin')));
});
test('noncanonical supply amount is rejected',()=>{
 const g=fixture();g.app_state.bank.supply[0].amount='01000';
 assert.ok(audit(g,'aprvi','1000').some(e=>e.includes('invalid coin')));
});
test('missing declared supply is rejected',()=>{
 const g=fixture();g.app_state.bank.supply=[];
 assert.ok(audit(g,'aprvi','1000').some(e=>e.includes('mismatch')));
});
