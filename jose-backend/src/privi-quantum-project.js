// Safe read-only status adapter to the user's existing Privi Quantum service.
// This public /status endpoint self-reports its capabilities. It is NOT proof
// of physical QPU runs, payment, blockchain anchoring, or quantum advantage.
export const QUANTUM_PROJECT_STATUS_URL='https://privi-quantum-vvmj.onrender.com/status';
export async function readQuantumProjectStatus({fetchImpl=globalThis.fetch,timeoutMs=4500}={}){
  const controller=new AbortController();
  const timer=setTimeout(()=>controller.abort(),timeoutMs);
  try{
    const res=await fetchImpl(QUANTUM_PROJECT_STATUS_URL,{
      method:'GET',headers:{Accept:'application/json'},
      credentials:'omit',redirect:'error',cache:'no-store',signal:controller.signal
    });
    if(!res.ok)throw Error('Status unavailable');
    const type=res.headers?.get?.('content-type')||'';
    if(!type.toLowerCase().includes('application/json'))throw Error('Unexpected content type');
    const body=await res.text();
    if(body.length>16000)throw Error('Status exceeds safe limit');
    const data=JSON.parse(body);
    if(data?.service!=='privi-quantum'||!Number.isInteger(data.max_qubits)||
      data.max_qubits<1||data.max_qubits>128)throw Error('Unrecognized Privi Quantum status');
    return {
      connected:true,source:'self_reported_public_status',observedAt:new Date().toISOString(),
      statusUrl:QUANTUM_PROJECT_STATUS_URL,
      service:'privi-quantum',version:typeof data.version==='string'?data.version.slice(0,30):null,
      projectMaxQubits:data.max_qubits,
      algorithm:typeof data.algorithm==='string'?data.algorithm.slice(0,140):null,
      qpuRunVerified:false,quantumAdvantageVerified:false,
      canSubmitJobsFromJose:false,
      note:'Public service status is self-reported. Jose free simulations run locally; paid or authenticated remote quantum jobs are not exposed.'
    };
  }catch{
    return {connected:false,source:'unverified',observedAt:new Date().toISOString(),
      statusUrl:QUANTUM_PROJECT_STATUS_URL,qpuRunVerified:false,quantumAdvantageVerified:false,
      canSubmitJobsFromJose:false,note:'The Privi Quantum status endpoint could not be verified. The free local Jose simulator remains available.'};
  }finally{clearTimeout(timer);}
}
export function formatQuantumProjectStatus(status){
  if(!status?.connected)return 'Privi Quantum project: live service status **not verified**. The free local qubit simulator in Hey Jose remains available. This does not indicate a physical QPU run.';
  return 'Privi Quantum service status: public /status responded as privi-quantum (self-reported version '+(status.version||'unknown')+'). '+
    'The project reports up to '+status.projectMaxQubits+' qubits for its '+(status.algorithm||'quantum optimization')+
    ' engine. This is **reported capability**, not an executed job or independent scientific certification. '+
    'Hey Jose can separately simulate up to 12 qubits locally at no extra charge. '+
    'No physical QPU result or quantum advantage has been verified here.';
}
