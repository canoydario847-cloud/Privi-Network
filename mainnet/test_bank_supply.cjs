'use strict';
// Offline regression coverage. No claim of production monetary-policy enforcement.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {auditBankSupply}=require('./audit_bank_supply.cjs');
const base=()=>({app_state:{bank:{balances:[{address:'account1',coins:[{denom:'aprvi',amount:'100'}]}],supply:[{denom:'aprvi',amount:'100'}]}}});
test('accepts balanced bank supply',()=>assert.deepEqual(auditBankSupply(base()),[]));
test('rejects supply mismatch',()=>{const g=base();g.app_state.bank.supply[0].amount='101';assert.ok(auditBankSupply(g).some(e=>/supply mismatch/.test(e)));});
test('rejects duplicate bank addresses',()=>{const g=base();g.app_state.bank.balances.push(structuredClone(g.app_state.bank.balances[0]));assert.ok(auditBankSupply(g).some(e=>/duplicate bank balance/.test(e)));});
test('rejects duplicate coin denomination within an address',()=>{const g=base();g.app_state.bank.balances[0].coins.push({denom:'aprvi',amount:'0'});assert.ok(auditBankSupply(g).some(e=>/duplicate balance denom/.test(e)));});
test('rejects unbacked nonzero supply',()=>{const g=base();g.app_state.bank.supply.push({denom:'other',amount:'1'});assert.ok(auditBankSupply(g).some(e=>/unbacked supply/.test(e)));});
test('documents current acceptance of zero-supply unbacked denomination (policy gap)',()=>{const g=base();g.app_state.bank.supply.push({denom:'other',amount:'0'});assert.deepEqual(auditBankSupply(g),[]);});
test('rejects amount exceeding uint256',()=>{const g=base();g.app_state.bank.balances[0].coins[0].amount=(1n<<256n).toString();assert.ok(auditBankSupply(g).some(e=>/invalid bank balance coin/.test(e)));});
test('rejects summed balances exceeding uint256',()=>{const g=base();g.app_state.bank.balances=[{address:'a',coins:[{denom:'aprvi',amount:((1n<<256n)-1n).toString()}]},{address:'b',coins:[{denom:'aprvi',amount:'1'}]}];g.app_state.bank.supply[0].amount=((1n<<256n)-1n).toString();assert.ok(auditBankSupply(g).some(e=>/sum exceeds uint256/.test(e)));});
test('rejects malformed supply denomination',()=>{const g=base();g.app_state.bank.supply[0].denom='aprvi\n';assert.ok(auditBankSupply(g).some(e=>/invalid supply coin/.test(e)));});

test('rejects missing bank state',()=>assert.match(auditBankSupply({}).join(';'),/missing bank balances or supply/));
test('rejects duplicate supply denominations',()=>{const g=base();g.app_state.bank.supply.push({denom:'aprvi',amount:'0'});assert.ok(auditBankSupply(g).some(e=>/duplicate supply denom/.test(e)));});
test('rejects negative balance amount',()=>{const g=base();g.app_state.bank.balances[0].coins[0].amount='-1';assert.ok(auditBankSupply(g).some(e=>/invalid bank balance coin/.test(e)));});
test('rejects leading-zero supply amount',()=>{const g=base();g.app_state.bank.supply[0].amount='0100';assert.ok(auditBankSupply(g).some(e=>/invalid supply coin/.test(e)));});
test('rejects whitespace-only bank address',()=>{const g=base();g.app_state.bank.balances[0].address=' ';assert.ok(auditBankSupply(g).some(e=>/invalid or duplicate bank balance address/.test(e)));});
test('rejects non-string bank amount',()=>{const g=base();g.app_state.bank.balances[0].coins[0].amount=100;assert.ok(auditBankSupply(g).some(e=>/invalid bank balance coin/.test(e)));});
