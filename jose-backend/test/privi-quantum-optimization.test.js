import test from 'node:test';
import assert from 'node:assert/strict';
import {
 MAX_QUBO_VARIABLES,QuantumOptimizationError,validateQubo,solveExactQubo,
 validateBalanceLines,optimizeBalanceLines,optimizationRequest,OPTIMIZATION_HELP,formatOptimizationResult,
} from '../src/privi-quantum-optimization.js';

test('QUBO exact optimum respects Privi Quantum x^T Q x convention',()=>{
 const r=solveExactQubo({Q:[[1,-2],[-2,1]],names:['a','b']});
 assert.equal(r.variables,2);
 assert.equal(r.configurationsEvaluated,4);
 assert.equal(r.optimumCost,-2);
 assert.deepEqual(r.optimalBits,[1,1]);
 assert.equal(r.optimalBitstring,'11');
 assert.deepEqual(r.optimalAssignments,{a:1,b:1});
 assert.equal(r.quantumHardware,false);
 assert.equal(r.qaoaExecuted,false);
 assert.equal(r.paymentRequired,false);
 assert.equal(r.remoteJobsSubmitted,false);
 assert.match(formatOptimizationResult(r),/classical exact QUBO baseline/);
});
test('Asymmetric off-diagonal QUBO and degeneracy are computed exactly',()=>{
 const nonSym=solveExactQubo({Q:[[0,-4],[0,0]]});
 assert.equal(nonSym.optimumCost,-4);
 assert.deepEqual(nonSym.optimalBits,[1,1]);
 const flat=solveExactQubo({Q:[[0,0,0],[0,0,0],[0,0,0]]});
 assert.equal(flat.degenerateOptima,8);
 assert.equal(flat.optimumCost,0);
 assert.equal(flat.optimalBitstring,'000');
});
test('Sixteen-variable exact reference checks 65536 classical assignments',()=>{
 const n=MAX_QUBO_VARIABLES;
 const Q=Array.from({length:n},(_,i)=>Array.from({length:n},(_,j)=>i===j?-1:0));
 const r=solveExactQubo({Q});
 assert.equal(r.configurationsEvaluated,65536);
 assert.equal(r.optimumCost,-16);
 assert.equal(r.optimalBitstring,'1'.repeat(16));
 assert.equal(r.degenerateOptima,1);
});
test('Balanced manufacturing lines have mathematically exact minimum difference',()=>{
 const jobs=[{name:'A',minutes:42},{name:'B',minutes:17},{name:'C',minutes:33}];
 const r=optimizeBalanceLines({jobs});
 assert.equal(r.problem,'balance_lines');
 assert.equal(r.differenceMinutes,8);
 assert.equal(r.optimumCost,64);
 assert.equal(r.lineAMinutes+r.lineBMinutes,92);
 assert.equal(r.configurationsEvaluated,8);
 assert.match(formatOptimizationResult(r),/classical exact line-balancing/);
});
test('Large but bounded jobs can be allocated without violating matrix caps',()=>{
 const jobs=Array.from({length:16},(_,i)=>({name:'Job'+i,minutes:10000}));
 const r=optimizeBalanceLines({jobs});
 assert.equal(r.differenceMinutes,0);
 assert.equal(r.optimumCost,0);
 assert.equal(r.configurationsEvaluated,65536);
});
test('Optimization refuses malformed or oversized QUBO matrices and job submissions',()=>{
 for(const input of [null,{Q:[]},{Q:[[1,2]]},{Q:[[1,NaN],[0,1]]},
   {Q:[[1,Infinity],[0,1]]},{Q:[[1]],names:['']},
   {Q:[[1]],names:['a','b']},{Q:[[1,-2],[-2,1]],names:['a','a']},
   {Q:[[1]],offset:Infinity},{Q:[[1]],other:1},
   {Q:Array.from({length:17},()=>Array(17).fill(0))}]){
  assert.throws(()=>validateQubo(input),QuantumOptimizationError);
 }
 for(const jobs of [[],[{name:'A',minutes:10}],[{name:'A',minutes:10},{name:'A',minutes:20}],
   [{name:'A',minutes:-1},{name:'B',minutes:2}],
   [{name:'A',minutes:1e8},{name:'B',minutes:2}],
   [{name:'A',minutes:1},{name:'B',minutes:2,delete:true}]]){
  assert.throws(()=>validateBalanceLines({jobs}),QuantumOptimizationError);
 }
});
test('Chat optimization commands accept JSON, require explicit data, and label QAOA separately',()=>{
 const a=optimizationRequest('/quantum optimize {"Q":[[-1]]}');
 assert.equal(a.type,'qubo');
 assert.equal(solveExactQubo(a.input).optimumCost,-1);
 const b=optimizationRequest('/quantum balance {"jobs":[{"name":"A","minutes":2},{"name":"B","minutes":3}]}');
 assert.equal(b.type,'balance');
 assert.equal(optimizeBalanceLines(b.input).differenceMinutes,1);
 assert.equal(optimizationRequest('Privi Quantum optimization').type,'help');
 assert.equal(optimizationRequest('What is a qubit?'),null);
 assert.throws(()=>optimizationRequest('/quantum optimize {bad}'),QuantumOptimizationError);
 assert.match(OPTIMIZATION_HELP,/QAOA/);
});
