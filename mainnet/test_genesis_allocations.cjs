'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {auditGenesisAllocations}=require('./audit_genesis_allocations.cjs');
const genesis={app_state:{bank:{balances:[{address:'vesting1',coins:[{denom:'aprvi',amount:'100'}]},{address:'liquid1',coins:[{denom:'aprvi',amount:'900'}]}],supply:[{denom:'aprvi',amount:'1000'}]}}};
const allocations=[{address:'vesting1',denom:'aprvi',amount:'100'},{address:'liquid1',denom:'aprvi',amount:'900'}];
test('accepts matching explicit allocations',()=>assert.deepEqual(auditGenesisAllocations(genesis,{allocations}),[]));
test('rejects missing manifest',()=>assert.match(auditGenesisAllocations(genesis,null)[0],/missing/));
test('rejects wrong vesting allocation amount',()=>assert.ok(auditGenesisAllocations(genesis,{allocations:[{...allocations[0],amount:'101'},allocations[1]]}).length));
test('rejects unknown address',()=>assert.ok(auditGenesisAllocations(genesis,{allocations:[{address:'unknown',denom:'aprvi',amount:'100'}]}).length));
test('rejects duplicate allocations',()=>assert.ok(auditGenesisAllocations(genesis,{allocations:[allocations[0],allocations[0]]}).length));
test('rejects invalid numeric amount',()=>assert.ok(auditGenesisAllocations(genesis,{allocations:[{...allocations[0],amount:'-1'}]}).length));
test('rejects bank supply mismatch',()=>{const bad=structuredClone(genesis);bad.app_state.bank.supply[0].amount='999';assert.ok(auditGenesisAllocations(bad,{allocations}).length);});
test('rejects empty manifest',()=>assert.ok(auditGenesisAllocations(genesis,{allocations:[]}).length));

test('rejects omitted liquid bank allocation despite balanced supply',()=>{
 const errors=auditGenesisAllocations(genesis,{allocations:[allocations[0]]});
 assert.ok(errors.some(e=>/missing from allocation manifest/.test(e)));
});
test('rejects omitted denom on a multi-denom bank address',()=>{
 const extra=structuredClone(genesis);
 extra.app_state.bank.balances[0].coins.push({denom:'other',amount:'7'});
 extra.app_state.bank.supply.push({denom:'other',amount:'7'});
 const errors=auditGenesisAllocations(extra,{allocations});
 assert.ok(errors.some(e=>/missing from allocation manifest/.test(e)));
});
test('accepts complete multi-denom allocations',()=>{
 const extra=structuredClone(genesis);
 extra.app_state.bank.balances[0].coins.push({denom:'other',amount:'7'});
 extra.app_state.bank.supply.push({denom:'other',amount:'7'});
 assert.deepEqual(auditGenesisAllocations(extra,{allocations:[...allocations,{address:'vesting1',denom:'other',amount:'7'}]}),[]);
});

test('rejects whitespace-only allocation address',()=>{
 const bad={allocations:[{...allocations[0],address:'  '},allocations[1]]};
 assert.ok(auditGenesisAllocations(genesis,bad).some(e=>/invalid allocation/.test(e)));
});
test('rejects control characters in allocation denomination',()=>{
 const bad={allocations:[{...allocations[0],denom:'aprvi\n'},allocations[1]]};
 assert.ok(auditGenesisAllocations(genesis,bad).some(e=>/invalid allocation/.test(e)));
});
test('rejects whitespace in otherwise valid allocation address',()=>{
 const bad={allocations:[{...allocations[0],address:'vesting 1'},allocations[1]]};
 assert.ok(auditGenesisAllocations(genesis,bad).some(e=>/invalid allocation/.test(e)));
});
