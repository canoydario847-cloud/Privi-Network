// Opt-in, server-to-server bridge to the existing Privi Quantum Cloud's
// *simulator-only* API. Disabled by default. Never forwards a browser token,
// caller-supplied URL, wallet, payment, or real quantum hardware job.
// Privi Quantum Cloud authenticates by shared bearer secret; Jose separately
// restricts it to allowlisted operator accounts and tracks in-memory ownership.
import {parseQasm,QuantumInputError} from './privi-quantum-simulator.js';
export const CLOUD_BASE='https://privi-quantum-vvmj.onrender.com';
const MAX_JOBS=128;
const MAX_BODY=8000;
const JOB_TTL=24*60*60*1000;
export class QuantumCloudError extends Error{
  constructor(message,status=503){super(message);this.name='QuantumCloudError';this.status=status;}
}
const bad=(message,status=400)=>{throw new QuantumCloudError(message,status);};
function allowedEmails(env){
  return new Set(String(env.JOSE_QUANTUM_CLOUD_OPERATOR_EMAILS||'')
    .split(',').map(x=>x.trim().toLowerCase()).filter(Boolean));
}
export function cloudBridgeEnabled(env=process.env){
  return env.JOSE_QUANTUM_CLOUD_ENABLED==='true' &&
    typeof env.JOSE_QUANTUM_CLOUD_API_KEY==='string' &&
    env.JOSE_QUANTUM_CLOUD_API_KEY.trim().length>=24 &&
    allowedEmails(env).size>0;
}
export function operatorAuthorized(user,env=process.env){
  return Boolean(user?.id && typeof user.email==='string' &&
    allowedEmails(env).has(user.email.toLowerCase()));
}
export function cloudBridgeStatus(env=process.env){
  return {
    simulatorOnly:true,physicalQpu:false,paidHardwareAllowed:false,
    enabled:cloudBridgeEnabled(env),requiresLogin:true,operatorAllowlistRequired:true,
    externallyAuthenticated:true,durableJobTracking:false,
    maxQubits:12,maxShots:4096,maxSourceChars:5000,
    note:cloudBridgeEnabled(env)?
      'Restricted operator-only remote simulator job bridge is configured. It does not run QAOA or physical hardware.':
      'Remote simulator jobs disabled until explicit operator allowlist and matching server-only API keys are configured. Free Jose simulator and QUBO optimizer are available now.'
  };
}
function validateInput(input){
  if(!input||typeof input!=='object'||Array.isArray(input)||
    Object.keys(input).some(k=>!['qasm','shots'].includes(k))||
    typeof input.qasm!=='string'||input.qasm.length<10||input.qasm.length>5000)
    bad('Provide restricted OpenQASM 2.0 source up to 5000 characters and optional shots.');
  const circuit=parseQasm(input.qasm); // Restricts 12 qubits and the supported safe gates.
  const shots=input.shots===undefined?1024:input.shots;
  if(!Number.isInteger(shots)||shots<1||shots>4096)
    bad('Shots must be 1–4096.');
  if(circuit.gates.length>80)bad('A maximum of 80 basis gates is allowed by Jose.');
  return {qasm:input.qasm,shots};
}
async function safeRequest(fetchImpl,url,key,{method='GET',body,timeoutMs=7500}={}){
  const controller=new AbortController();
  const timer=setTimeout(()=>controller.abort(),timeoutMs);
  try{
    const response=await fetchImpl(url,{method,redirect:'error',credentials:'omit',cache:'no-store',
      headers:{Authorization:'Bearer '+key,Accept:'application/json',
        ...(body?{'Content-Type':'application/json'}:{})},
      ...(body?{body:JSON.stringify(body)}:{}),signal:controller.signal});
    const type=response.headers?.get?.('content-type')||'';
    if(!type.toLowerCase().includes('application/json'))
      bad('Unexpected cloud response content type.',502);
    const raw=await response.text();
    if(raw.length>MAX_BODY)bad('Quantum Cloud response exceeds safe size.',502);
    let data;
    try{data=JSON.parse(raw);}catch{bad('Invalid Quantum Cloud response.',502);}
    if(!response.ok)
      bad(response.status===429?'Quantum Cloud queue is full.':
        response.status===503?'Quantum Cloud is not configured.':
        response.status===401?'Quantum Cloud credentials are not accepted.':
        'Quantum Cloud job unavailable.',response.status===429?429:503);
    return data;
  }catch(e){
    if(e instanceof QuantumCloudError)throw e;
    throw new QuantumCloudError('Quantum Cloud is unreachable. No hardware was used.',503);
  }finally{clearTimeout(timer);}
}
export function createQuantumCloudBridge({env=process.env,fetchImpl=globalThis.fetch}={}){
  const ownedJobs=new Map();
  function assertCaller(user){
    if(!cloudBridgeEnabled(env))bad('Cloud simulator not configured; local quantum features remain available.',503);
    if(!operatorAuthorized(user,env))bad('This Cloud simulator is restricted to approved operator accounts.',403);
  }
  function cleanup(){
    const now=Date.now();
    for(const [id,row] of ownedJobs)if(now-row.createdAt>JOB_TTL)ownedJobs.delete(id);
  }
  async function submit(user,input){
    assertCaller(user);
    const payload=validateInput(input);
    cleanup();
    if(ownedJobs.size>=MAX_JOBS)bad('Jose Quantum Cloud operator job limit reached.',429);
    const data=await safeRequest(fetchImpl,CLOUD_BASE+'/v1/quantum/cloud/jobs',
      env.JOSE_QUANTUM_CLOUD_API_KEY,{method:'POST',body:payload});
    if(typeof data?.job_id!=='string'||!/^qj_[0-9a-f]{32}$/.test(data.job_id)||
       data.physical_qpu!==false||data.backend!=='local_statevector_simulator'||
       !['queued','running','completed'].includes(data.status)){
      bad('The Quantum Cloud did not confirm a simulator-only job.',502);
    }
    ownedJobs.set(data.job_id,{owner:user.id,createdAt:Date.now()});
    return {jobId:data.job_id,status:data.status,backend:data.backend,
      qubits:data.qubits,shots:data.shots,physicalQpu:false,paymentRequired:false,
      note:'Remote classical simulator, operator-only. Results require polling; jobs are not available after a Jose restart.'};
  }
  async function get(user,jobId){
    assertCaller(user);
    if(typeof jobId!=='string'||!/^qj_[0-9a-f]{32}$/.test(jobId))bad('Unknown job identifier.',404);
    cleanup();
    if(ownedJobs.get(jobId)?.owner!==user.id)bad('Job not found for this Jose account.',404);
    const data=await safeRequest(fetchImpl,CLOUD_BASE+'/v1/quantum/cloud/jobs/'+jobId,
      env.JOSE_QUANTUM_CLOUD_API_KEY);
    if(data?.job_id!==jobId||data?.physical_qpu!==false||
       data?.backend!=='local_statevector_simulator'||
       !['queued','running','completed','failed'].includes(data.status))
      bad('Unrecognized Cloud simulator job response.',502);
    if(data.status==='completed'){
      const r=data.result;
      if(!r||r.physical_qpu!==false||r.backend!=='local_statevector_simulator'||
         !Number.isInteger(r.qubits)||r.qubits<1||r.qubits>12||
         !Number.isInteger(r.shots)||r.shots<1||r.shots>4096||
         !r.counts||typeof r.counts!=='object'||Array.isArray(r.counts)||
         Object.entries(r.counts).some(([k,v])=>!new RegExp('^[01]{'+r.qubits+'}$').test(k)||!Number.isInteger(v)||v<0))
        bad('Invalid classical simulator result returned.',502);
    }
    return {jobId,status:data.status,physicalQpu:false,paymentRequired:false,
      backend:'local_statevector_simulator',
      ...(data.status==='completed'?{result:data.result}:{}),
      ...(data.status==='failed'?{error:'Remote classical simulation failed.'}:{})};
  }
  return Object.freeze({status:()=>cloudBridgeStatus(env),submit,get});
}
