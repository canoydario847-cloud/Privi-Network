import test from 'node:test';
import assert from 'node:assert/strict';
import {
  MAX_QUBITS,MAX_SHOTS,QuantumInputError,validateCircuit,parseQasm,
  quantumRequest,simulateCircuit,formatQuantumAnswer,
} from '../src/privi-quantum-simulator.js';

const run=(qubits,gates,options={})=>simulateCircuit({qubits,gates,...options});
const p=(result,state)=>result.probabilities.find(row=>row.state===state)?.probability||0;
const sum=result=>Object.values(result.counts).reduce((a,b)=>a+b,0);
const H=target=>({gate:'h',target});
const CX=(control,target)=>({gate:'cx',control,target});

test('Privi Quantum Bell pair has equal |00> and |11> exact probabilities',()=>{
  const r=run(2,[H(0),CX(0,1)],{shots:1024,seed:12});
  assert.equal(p(r,'00'),0.5);
  assert.equal(p(r,'11'),0.5);
  assert.equal(p(r,'01'),0);
  assert.equal(p(r,'10'),0);
  assert.equal(sum(r),1024);
  assert.equal(r.physicalQpu,false);
  assert.equal(r.quantumAdvantageClaimed,false);
  assert.equal(r.paymentRequired,false);
  assert.equal(r.networkWrites,false);
  assert.match(formatQuantumAnswer(r),/classical exact-statevector simulator/);
});
test('X, Z, H preserve expected basis measurements and q0 bit ordering',()=>{
  assert.equal(p(run(2,[{gate:'x',target:0}]),'01'),1);
  assert.equal(p(run(2,[{gate:'x',target:1}]),'10'),1);
  assert.equal(p(run(1,[H(0),{gate:'z',target:0},H(0)]),'1'),1);
  assert.equal(p(run(1,[{gate:'x',target:0},{gate:'x',target:0}]),'0'),1);
});
test('GHZ family produces only all-zeros and all-ones states',()=>{
  for(const n of [2,3,6,8]){
    const gates=[H(0),...Array.from({length:n-1},(_,i)=>CX(i,i+1))];
    const r=run(n,gates,{seed:42});
    assert.equal(r.probabilities.length,2);
    assert.equal(p(r,'0'.repeat(n)),0.5);
    assert.equal(p(r,'1'.repeat(n)),0.5);
    assert.equal(sum(r),1024);
  }
});
test('RX and RZ rotations are unitary and do not fabricate measurements',()=>{
  const r=run(1,[{gate:'rx',target:0,angle:Math.PI}]);
  assert.ok(p(r,'1')>0.999999999);
  assert.equal(p(r,'0'),0);
  const z=run(1,[{gate:'rz',target:0,angle:Math.PI}]);
  assert.equal(p(z,'0'),1);
  const mix=run(3,[H(0),{gate:'rx',target:2,angle:1.15},
    {gate:'rz',target:1,angle:-0.25},CX(0,1)]);
  assert.ok(Math.abs(mix.totalProbability-1)<1e-12);
  assert.ok(Math.abs(mix.probabilities.reduce((acc,v)=>acc+v.probability,0)-1)<1e-10);
});
test('simulated shots are seeded, reproducible, and sum exactly to requested shots',()=>{
  const c={qubits:3,gates:[H(0),H(1),H(2)],shots:2001,seed:777};
  const first=simulateCircuit(c);
  assert.deepEqual(first.counts,simulateCircuit(c).counts);
  assert.equal(sum(first),2001);
  assert.equal(first.amplitudes.length,8);
  const different=simulateCircuit({...c,seed:778});
  assert.notDeepEqual(first.counts,different.counts);
});
test('restricted OpenQASM 2.0 runs same Bell state as JSON input',()=>{
  const c=parseQasm('OPENQASM 2.0; include "qelib1.inc"; qreg q[2]; creg c[2]; h q[0]; cx q[0],q[1]; measure q[0] -> c[0]; measure q[1] -> c[1];');
  assert.equal(c.qubits,2);
  assert.deepEqual(c.gates,[H(0),CX(0,1)]);
  assert.equal(p(simulateCircuit(c),'11'),0.5);
  const phase=parseQasm('OPENQASM 2.0; qreg q[1]; rx(pi) q[0]; rz(-pi/2) q[0];');
  assert.equal(phase.gates[0].angle,Math.PI);
  assert.equal(phase.gates[1].angle,-Math.PI/2);
});
test('natural language Bell/GHZ requests are deterministic local simulations',()=>{
  const bell=quantumRequest('Simulate a 2-qubit Bell state with Privi Quantum');
  assert.equal(bell.type,'simulate');
  assert.equal(p(simulateCircuit(bell.circuit),'11'),0.5);
  const ghz=quantumRequest('Please run a 4 qubit GHZ simulation');
  assert.equal(ghz.circuit.qubits,4);
  assert.equal(p(simulateCircuit(ghz.circuit),'1111'),0.5);
  assert.equal(quantumRequest('What is quantum physics?'),null);
  assert.equal(quantumRequest('Privi Quantum run simulation in qubits').type,'help');
});
test('structured chat JSON and QASM circuit commands work',()=>{
  const structured=quantumRequest('/quantum simulate {"qubits":1,"gates":[{"gate":"x","target":0}]}');
  assert.equal(p(simulateCircuit(structured.circuit),'1'),1);
  const qasm=quantumRequest('/quantum qasm OPENQASM 2.0; qreg q[1]; x q[0];');
  assert.equal(p(simulateCircuit(qasm.circuit),'1'),1);
  assert.throws(()=>quantumRequest('/quantum simulate {nonsense}'),QuantumInputError);
});
test('qubit, gate, shot and angle limits reject unsafe or expensive inputs',()=>{
  const invalid=[
    {qubits:0,gates:[]},{qubits:MAX_QUBITS+1,gates:[]},
    {qubits:2,gates:[CX(0,0)]},{qubits:1,gates:[CX(0,2)]},
    {qubits:1,gates:[{gate:'h',target:1}]},
    {qubits:1,gates:[{gate:'hack',target:0}]},
    {qubits:1,gates:[{gate:'rx',target:0,angle:Infinity}]},
    {qubits:1,gates:[{gate:'rx',target:0,angle:'pi'}]},
    {qubits:1,gates:[{gate:'h',target:0,extra:'hi'}]},
    {qubits:1,gates:[H(0)],shots:MAX_SHOTS+1},
    {qubits:1,gates:[H(0)],seed:-1},
    {qubits:1,gates:Array.from({length:81},()=>H(0))},
    {qubits:1,gates:[H(0)],secretKey:'no'},
  ];
  for(const v of invalid)assert.throws(()=>simulateCircuit(v),QuantumInputError);
  assert.throws(()=>parseQasm('OPENQASM 2.0; qreg q[2]; measure q[0] -> c[0]; h q[0];'),QuantumInputError);
  assert.throws(()=>parseQasm('OPENQASM 2.0; qreg q[2]; system("rm -rf /");'),QuantumInputError);
  assert.throws(()=>parseQasm('OPENQASM 3.0; qubit[2] q;'),QuantumInputError);
});
