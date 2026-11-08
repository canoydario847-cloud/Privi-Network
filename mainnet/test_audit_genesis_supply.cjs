'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {audit}=require('./audit_genesis_supply.cjs');
const fixture=()=>({app_state:{bank:{balances:[{address:'addr1',coins:[{denom:'aprvi',amount:'600'}]},{address:'addr2',coins:[{denom:'aprvi',amount:'400'}]}],supply:[{denom:'aprvi',amount:'1000'}]}}});
test('valid bank allocation and supply',()=>assert.deepEqual(audit(fixture(),'aprvi','1000'),[]));
test('supply mismatch fails',()=>{const g=fixture();g.app_state.bank.supply[0].amount='999';assert.ok(audit(g,'aprvi','1000').some(x=>x.includes('mismatch')));});
test('duplicate accounts fail',()=>{const g=fixture();g.app_state.bank.balances[1].address='addr1';assert.ok(audit(g,'aprvi','1000').some(x=>x.includes('duplicate bank account')));});
test('duplicate denom fails',()=>{const g=fixture();g.app_state.bank.balances[0].coins.push({denom:'aprvi',amount:'0'});assert.ok(audit(g,'aprvi','1000').some(x=>x.includes('duplicate balance denom')));});
test('malformed integer fails',()=>{const g=fixture();g.app_state.bank.balances[0].coins[0].amount='1e3';assert.ok(audit(g,'aprvi','1000').some(x=>x.includes('invalid coin')));});
test('wrong expected amount fails',()=>assert.ok(audit(fixture(),'aprvi','999').some(x=>x.includes('expected PRVI supply'))));
test('missing bank module fails',()=>assert.ok(audit({},'aprvi','1000').length));
test('large integers stay exact',()=>{const g=fixture();const n='900719925474099300000';g.app_state.bank.balances=[{address:'a',coins:[{denom:'aprvi',amount:n}]}];g.app_state.bank.supply=[{denom:'aprvi',amount:n}];assert.deepEqual(audit(g,'aprvi',n),[]);});

test('missing expected denomination fails even for zero expected supply',()=>{const g=fixture();g.app_state.bank.balances=[];g.app_state.bank.supply=[];assert.ok(audit(g,'aprvi','0').some(x=>x.includes('denomination missing')));});
test('explicit zero supply denomination remains valid',()=>{const g=fixture();g.app_state.bank.balances=[];g.app_state.bank.supply=[{denom:'aprvi',amount:'0'}];assert.deepEqual(audit(g,'aprvi','0'),[]);});
