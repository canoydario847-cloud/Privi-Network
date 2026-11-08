'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {auditBankSupply}=require('./audit_bank_supply.cjs');
const fixture=()=>({app_state:{bank:{balances:[{address:'a',coins:[{denom:'aprvi',amount:'900719925474099300000'}]},{address:'b',coins:[{denom:'aprvi',amount:'100'}]}],supply:[{denom:'aprvi',amount:'900719925474099300100'}]}}});
test('exact BigInt reconciliation',()=>assert.deepEqual(auditBankSupply(fixture()),[]));
test('missing supply fails',()=>{const g=fixture();delete g.app_state.bank.supply;assert.ok(auditBankSupply(g).length);});
test('mismatched supply fails',()=>{const g=fixture();g.app_state.bank.supply[0].amount='1';assert.ok(auditBankSupply(g).some(x=>x.includes('supply mismatch')));});
test('duplicate balance address fails',()=>{const g=fixture();g.app_state.bank.balances.push(g.app_state.bank.balances[0]);assert.ok(auditBankSupply(g).length);});
test('duplicate balance denom fails',()=>{const g=fixture();g.app_state.bank.balances[0].coins.push({denom:'aprvi',amount:'1'});assert.ok(auditBankSupply(g).length);});
test('duplicate supply denom fails',()=>{const g=fixture();g.app_state.bank.supply.push({denom:'aprvi',amount:'1'});assert.ok(auditBankSupply(g).length);});
test('unbacked supply fails',()=>{const g=fixture();g.app_state.bank.supply.push({denom:'other',amount:'1'});assert.ok(auditBankSupply(g).length);});
test('malformed amount fails',()=>{const g=fixture();g.app_state.bank.balances[0].coins[0].amount='01';assert.ok(auditBankSupply(g).length);});

test('whitespace-only bank address fails',()=>{const g=fixture();g.app_state.bank.balances[0].address='  ';assert.ok(auditBankSupply(g).length);});
test('control character in bank address fails',()=>{const g=fixture();g.app_state.bank.balances[0].address='a\n';assert.ok(auditBankSupply(g).length);});
test('whitespace in balance denomination fails',()=>{const g=fixture();g.app_state.bank.balances[0].coins[0].denom='a prvi';assert.ok(auditBankSupply(g).length);});
test('whitespace in declared supply denomination fails',()=>{const g=fixture();g.app_state.bank.supply[0].denom=' aprvi';assert.ok(auditBankSupply(g).length);});
