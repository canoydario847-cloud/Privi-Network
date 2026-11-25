import test from 'node:test';
import assert from 'node:assert/strict';
import {
 cloudBridgeEnabled,operatorAuthorized,cloudBridgeStatus,createQuantumCloudBridge,
 QuantumCloudError,CLOUD_BASE
} from '../src/privi-quantum-cloud-bridge.js';

const admin={id:'user-1',email:'owner@example.test'};
const other={id:'user-2',email:'other@example.test'};
const env={
 JOSE_QUANTUM_CLOUD_ENABLED:'true',
 JOSE_QUANTUM_CLOUD_OPERATOR_EMAILS:'owner@example.test',
 JOSE_QUANTUM_CLOUD_API_KEY:'S'.repeat(40)
};
const qasm='OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[2];\nh q[0];\ncx q[0],q[1];';
const jid='qj_'+'a'.repeat(32);
const jsonBody=(obj,status=200)=>({ok:status>=200&&status<300,status,
 headers:{get:()=> 'application/json'},text:async()=>JSON.stringify(obj)});
test('Quantum Cloud remote execution remains disabled by default',async()=>{
 const unset={};
 let networkCalls=0;
 const bridge=createQuantumCloudBridge({env:unset,fetchImpl:async()=>{
   networkCalls++;throw Error('should not call network');
 }});
 assert.equal(cloudBridgeEnabled(unset),false);
 assert.equal(bridge.status().enabled,false);
 await assert.rejects(()=>bridge.submit(admin,{qasm}),error=>error.status===503);
 assert.equal(networkCalls,0);
 assert.equal(bridge.status().physicalQpu,false);
 assert.equal(bridge.status().paidHardwareAllowed,false);
});
test('Cloud bridge refuses guests, wrong accounts, and a missing operator allowlist',async()=>{
 assert.equal(operatorAuthorized(admin,env),true);
 assert.equal(operatorAuthorized(other,env),false);
 assert.equal(operatorAuthorized(null,env),false);
 assert.equal(cloudBridgeEnabled({...env,JOSE_QUANTUM_CLOUD_OPERATOR_EMAILS:''}),false);
 const bridge=createQuantumCloudBridge({env,fetchImpl:async()=>{throw Error('network must not be called');}});
 await assert.rejects(()=>bridge.submit(other,{qasm}),error=>error.status===403);
 await assert.rejects(()=>bridge.submit({id:'guest',email:''},{qasm}),error=>error.status===403);
});
test('Only allowlisted operator can submit an explicitly simulator-only circuit',async()=>{
 const calls=[];
 const bridge=createQuantumCloudBridge({env,fetchImpl:async(url,request)=>{
   calls.push({url,request});
   assert.equal(request.redirect,'error');
   assert.equal(request.credentials,'omit');
   assert.equal(request.headers.Authorization,'Bearer '+env.JOSE_QUANTUM_CLOUD_API_KEY);
   assert.equal(request.method,calls.length===1?'POST':'GET');
   if(calls.length===1){
     assert.deepEqual(JSON.parse(request.body),{qasm,shots:100});
     return jsonBody({job_id:jid,status:'queued',backend:'local_statevector_simulator',
       qubits:2,shots:100,physical_qpu:false},202);
   }
   return jsonBody({job_id:jid,status:'completed',physical_qpu:false,
     backend:'local_statevector_simulator',
     result:{counts:{'00':50,'11':50},shots:100,qubits:2,
       backend:'local_statevector_simulator',physical_qpu:false}});
 }});
 const queued=await bridge.submit(admin,{qasm,shots:100});
 assert.equal(queued.physicalQpu,false);
 assert.equal(queued.paymentRequired,false);
 assert.equal(queued.jobId,jid);
 assert.equal(calls[0].url,CLOUD_BASE+'/v1/quantum/cloud/jobs');
 await assert.rejects(()=>bridge.get(other,jid),error=>error.status===403);
 const result=await bridge.get(admin,jid);
 assert.equal(result.status,'completed');
 assert.equal(result.result.counts['11'],50);
 assert.equal(calls[1].url,CLOUD_BASE+'/v1/quantum/cloud/jobs/'+jid);
 assert.equal(calls.length,2);
});
test('Rejected or physical-QPU remote replies do not become trusted job records',async()=>{
 const malicious=createQuantumCloudBridge({env,fetchImpl:async()=>
   jsonBody({job_id:jid,status:'queued',backend:'physical_qpu',
     physical_qpu:true},202)});
 await assert.rejects(()=>malicious.submit(admin,{qasm}),error=>error.status===502);
 await assert.rejects(()=>malicious.get(admin,jid),error=>error.status===404);
});
test('Bad OpenQASM, paid-hardware options, and unknown remote job identifiers are rejected',async()=>{
 let calls=0;
 const bridge=createQuantumCloudBridge({env,fetchImpl:async()=>{calls++;throw Error('network blocked');}});
 await assert.rejects(()=>bridge.submit(admin,{qasm:'OPENQASM 3.0; qubit[1] q;'}));
 await assert.rejects(()=>bridge.submit(admin,{qasm,shots:100,backend:'ibm_qpu'}));
 await assert.rejects(()=>bridge.submit(admin,{qasm,shots:5000}));
 await assert.rejects(()=>bridge.get(admin,'qj_'+'b'.repeat(32)),error=>error.status===404);
 assert.equal(calls,0);
});
