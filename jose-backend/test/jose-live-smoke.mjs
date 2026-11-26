// Live read-only HTTP health probe for Render deployment.
// No signup, user cookies, credentials, wallet signing, token spending or email.
const SITE=process.env.JOSE_SITE_URL||'https://jose-site-21hs.onrender.com';
const BACKEND=process.env.JOSE_BACKEND_URL||'https://jose-backend-075d.onrender.com';
const report={date:new Date().toISOString(),site:SITE,backend:BACKEND,checks:[]};
async function probe(name,url,{method='GET',payload,expect=200,timeoutMs=16000,optional=false}={}){
 let last;
 for(let attempt=0;attempt<3;attempt++){
  const ctrl=new AbortController(),timer=setTimeout(()=>ctrl.abort(),timeoutMs);
  try{
   const response=await fetch(url,{method,headers:payload?{'Content-Type':'application/json',Origin:BACKEND}:{},body:payload?JSON.stringify(payload):undefined,signal:ctrl.signal,redirect:'follow'});
   const raw=await response.text();
   const json=/application\/json/i.test(response.headers.get('content-type')||'')?JSON.parse(raw):null;
   const pass=typeof expect==='function'?expect(response,json,raw):response.status===expect;
   if(!pass)throw Error('HTTP '+response.status+' did not meet expected response');
   report.checks.push({name,status:'pass',httpStatus:response.status});
   return {json,raw,response};
  }catch(e){last=e; if(attempt<2)await new Promise(resolve=>setTimeout(resolve,1300));}
  finally{clearTimeout(timer);}
 }
 report.checks.push({name,status:optional?'warning':'fail',error:String(last?.message||last).slice(0,170)});
 if(!optional)process.exitCode=1;
 return null;
}
const site=await probe('Public site root',SITE+'/',{expect:(r,j,t)=>r.status===200&&t.includes('jose-backend-075d.onrender.com/chat.html')});
const health=await probe('Jose backend health',BACKEND+'/health',{expect:(r,j)=>r.status===200&&j?.ok===true});
const status=await probe('Chat configuration and 20 powers',BACKEND+'/api/chat/status',{
 expect:(r,j)=>r.status===200&&j?.localPowerCount===20&&typeof j?.available==='boolean'&&typeof j?.gmailConfigured==='boolean'
});
if(status?.json){
 report.aiProviderConfigured=status.json.available;
 report.gmailOAuthConfigured=status.json.gmailConfigured;
 report.note='Configured does not mean end-to-end AI/Gmail access is verified.';
}
await probe('Chat HTML and Gmail/Memory UI',BACKEND+'/chat.html',{expect:(r,j,t)=>r.status===200&&t.includes('chat-gmail.js')&&t.includes('chat-memory.js')});
await probe('Gmail script served',BACKEND+'/chat-gmail.js',{expect:(r,j,t)=>r.status===200&&t.includes('gmailConnect')});
await probe('Memory script served',BACKEND+'/chat-memory.js',{expect:(r,j,t)=>r.status===200&&t.includes('joseMemory')});
await probe('Power command chat answer',BACKEND+'/api/chat',{method:'POST',payload:{message:'/powers'},expect:(r,j)=>r.status===200&&j?.power==='powers'&&j?.answer?.includes('20 verified local tools')});
const connect=await probe('Gmail connect intent gives specific state',BACKEND+'/api/chat',{method:'POST',payload:{message:'Connect my Gmail account'},expect:(r,j)=>r.status===200&&['operator_setup','sign_in','authorize','connected'].includes(j?.gmailStatus)});
if(connect?.json)report.gmailConnectionState=connect.json.gmailStatus;
const inbox=await probe('Gmail read intent gives truthful state',BACKEND+'/api/chat',{method:'POST',payload:{message:'Read my emails'},expect:(r,j)=>r.status===200&&(
 (typeof j?.gmailStatus==='string')||(j?.gmailAction==='inbox'&&typeof j?.answer==='string')
)});
if(inbox?.json)report.gmailReadIntentState=inbox.json.gmailStatus||inbox.json.gmailAction;
await probe('Gmail API rejects unauthenticated access',BACKEND+'/api/gmail/status',{expect:401});
await probe('Gmail send endpoint rejects unauthenticated requests',BACKEND+'/api/gmail/send',{method:'POST',payload:{reviewToken:'test-invalid',confirmSend:true},expect:401});

// Future PRVI integration is explicitly inert; verify status after deployment.
await probe('PRVI future mainnet remains no-go and unconnected',
  BACKEND+'/api/prvi/mainnet/plan',{
  expect:(r,j)=>r.status===200&&j?.connected===false&&
    j?.readiness==='NO_GO_AWAITING_INDEPENDENT_RELEASE_EVIDENCE'&&
    j?.chainId===null&&j?.paymentsEnabled===false&&j?.pricePegActive===false,
  optional:true
});
// New release diagnostics. These are optional in PR checks because the old
// production deployment may still be live; rerun after Render deploys.
await probe('Privi Quantum local simulator metadata (12 qubits)',BACKEND+'/api/quantum/info',{
 expect:(r,j)=>r.status===200&&j?.engine==='classical_exact_statevector'&&j?.maxQubits===12&&j?.hardwareQpu===false,
 optional:true
});
await probe('Privi Quantum 12-qubit GHZ simulation',BACKEND+'/api/quantum/simulate',{
 method:'POST',
 payload:{qubits:12,gates:[{gate:'h',target:0},...Array.from({length:11},(_,i)=>({gate:'cx',control:i,target:i+1}))],shots:512,seed:1},
 expect:(r,j)=>r.status===200&&j?.physicalQpu===false&&j?.paymentRequired===false&&
   j?.probabilities?.find(v=>v.state==='1'.repeat(12))?.probability===0.5&&
   Object.values(j?.counts||{}).reduce((a,b)=>a+b,0)===512,
 optional:true
});
await probe('Privi Quantum public project status proxy',BACKEND+'/api/quantum/project',{
 expect:(r,j)=>r.status===200&&typeof j?.connected==='boolean'&&j?.canSubmitJobsFromJose===false&&
   j?.qpuRunVerified===false,
 optional:true
});

// Operator-only cloud jobs remain untouched. These optional checks only read
// public metadata or perform an inexpensive local classical calculation.
await probe('Privi Quantum exact QUBO optimizer metadata',BACKEND+'/api/quantum/optimization-info',{
 expect:(r,j)=>r.status===200&&j?.maxVariables===16&&j?.qaoaExecuted===false&&j?.physicalQpu===false,
 optional:true
});
await probe('Privi Quantum exact QUBO baseline',BACKEND+'/api/quantum/optimize',{
 method:'POST',payload:{Q:[[1,-2],[-2,1]],names:['a','b']},
 expect:(r,j)=>r.status===200&&j?.optimumCost===-2&&j?.qaoaExecuted===false&&
  j?.configurationsEvaluated===4&&j?.remoteJobsSubmitted===false,
 optional:true
});
await probe('Privi Quantum Cloud does not expose hardware calls',BACKEND+'/api/quantum/cloud/info',{
 expect:(r,j)=>r.status===200&&j?.physicalQpu===false&&j?.paidHardwareAllowed===false&&
  typeof j?.enabled==='boolean',
 optional:true
});
// Public read-only smoke: Mission Control requires real login for task sync.
// No tasks are written by production smoke checks.
await probe('Hey Jose Mission Control manual task capability',BACKEND+'/api/chat/status',{
  expect:(r,j)=>r.status===200&&j?.missionControl===true&&
    j?.missionControlManualOnly===true&&j?.missionControlRequiresLoginForSync===true,
  optional:true
});
await probe('Mission Control guest account access denied',BACKEND+'/api/tasks',{
  expect:(r,j)=>r.status===401&&typeof j?.error==='string',
  optional:true
});
const card=await probe('Network report card response',BACKEND+'/api/network/report-card',{expect:(r,j)=>r.status===200&&j&&typeof j==='object',optional:true});
if(card?.json)report.monitorFresh=card.json.fresh===true;
const dev=await probe('Devnet verification endpoint',BACKEND+'/api/devnet/status',{expect:(r,j)=>r.status===200&&typeof j?.connected==='boolean',optional:true});
if(dev?.json){
 report.devnetConnected=dev.json.connected;
 report.devnetEvmId=dev.json.connected?dev.json.observedEvmChainId:null;
 if(dev.json.connected&&dev.json.observedEvmChainId!==772626){
  report.checks.push({name:'Devnet expected EVM chain ID 772626',status:'fail'});
  process.exitCode=1;
 }
}
console.log(JSON.stringify(report,null,2));
