import test from 'node:test';
import assert from 'node:assert/strict';
import {
  QUANTUM_PROJECT_STATUS_URL,readQuantumProjectStatus,formatQuantumProjectStatus
} from '../src/privi-quantum-project.js';

const ok=(data,{status=200,type='application/json'}={})=>({
 status,ok:status>=200&&status<300,
 headers:{get:()=>type},text:async()=>JSON.stringify(data)
});
test('Privi Quantum public status is read-only, bounded and explicitly self-reported',async()=>{
 let called=0;
 const result=await readQuantumProjectStatus({fetchImpl:async(url,request)=>{
  called++;
  assert.equal(url,QUANTUM_PROJECT_STATUS_URL);
  assert.equal(request.method,'GET');
  assert.equal(request.redirect,'error');
  assert.equal(request.credentials,'omit');
  assert.equal(request.headers.Authorization,undefined);
  assert.ok(request.signal);
  return ok({service:'privi-quantum',version:'0.13.0',
    max_qubits:16,algorithm:'CVaR-QAOA (exact statevector)'});
 }});
 assert.equal(called,1);
 assert.equal(result.connected,true);
 assert.equal(result.projectMaxQubits,16);
 assert.equal(result.qpuRunVerified,false);
 assert.equal(result.quantumAdvantageVerified,false);
 assert.equal(result.canSubmitJobsFromJose,false);
 assert.match(formatQuantumProjectStatus(result),/self-reported/);
});
test('service outage never becomes a false quantum hardware status',async()=>{
 for(const fetchImpl of [
   async()=>{throw Error('ECONNRESET');},
   async()=>ok({service:'other',max_qubits:128}),
   async()=>ok({service:'privi-quantum',max_qubits:16},{type:'text/html'}),
   async()=>ok({service:'privi-quantum',max_qubits:16},{status:502}),
 ]){
   const result=await readQuantumProjectStatus({fetchImpl});
   assert.equal(result.connected,false);
   assert.equal(result.qpuRunVerified,false);
   assert.match(formatQuantumProjectStatus(result),/not verified/);
 }
});
test('Quantum service status rejects oversized or unexpected data',async()=>{
 const huge='a'.repeat(17000);
 const big=await readQuantumProjectStatus({
   fetchImpl:async()=>({ok:true,headers:{get:()=> 'application/json'},text:async()=>huge})
 });
 assert.equal(big.connected,false);
 const odd=await readQuantumProjectStatus({fetchImpl:async()=>ok({service:'privi-quantum',max_qubits:1000})});
 assert.equal(odd.connected,false);
});
