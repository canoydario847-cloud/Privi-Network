// End-to-end HTTP exercise of actual Jose Node server without live accounts,
// paid provider calls, Gmail sends, or blockchain writes. Runs on localhost only.
import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync, existsSync, readFileSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import net from 'node:net';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';

const serverFile=fileURLToPath(new URL('../src/server.js',import.meta.url));
const projectDir=path.dirname(path.dirname(serverFile));
async function freePort(){
 const server=net.createServer();
 await new Promise((resolve,reject)=>server.once('error',reject).listen(0,'127.0.0.1',resolve));
 const port=server.address().port;
 await new Promise(resolve=>server.close(resolve));
 return port;
}
async function serverSession(dbFile, overrides={}){
 const port=await freePort(),base='http://127.0.0.1:'+port;
 const env={...process.env,PORT:String(port),BASE_URL:base,DB_FILE:dbFile};
 for(const key of ['JOSE_ADMIN_EMAIL','JOSE_ADMIN_PASSWORD','JOSE_AI_API_KEY','GOOGLE_CLIENT_ID','GOOGLE_CLIENT_SECRET'])delete env[key];
 for(const key of Object.keys(env))if(key.startsWith('JOSE_QUANTUM_CLOUD_'))delete env[key];
 Object.assign(env,overrides);
 const proc=spawn(process.execPath,[serverFile],{cwd:projectDir,env,stdio:['ignore','pipe','pipe']});
 let output='';
 for(const name of ['stdout','stderr'])proc[name].on('data',chunk=>{output+=chunk.toString().slice(0,500);});
 const deadline=Date.now()+10000;
 while(Date.now()<deadline){
  if(proc.exitCode!==null)throw Error('Jose failed to start: '+output.slice(-2000));
  try{
   const r=await fetch(base+'/health',{signal:AbortSignal.timeout(1100)});
   if(r.ok)return {base,proc,output:()=>output};
  }catch{}
  await new Promise(resolve=>setTimeout(resolve,120));
 }
 proc.kill('SIGTERM');
 throw Error('Jose /health never responded. '+output.slice(-1000));
}
async function stop(proc){
 if(proc.exitCode!==null||proc.killed)return;
 const done=new Promise(resolve=>proc.once('exit',resolve));
 proc.kill('SIGTERM');
 await Promise.race([done,new Promise(resolve=>setTimeout(resolve,3500))]);
 if(proc.exitCode===null)proc.kill('SIGKILL');
}
async function json(base,path,method='GET',body,extra={}){
 const opts={
  method,headers:method==='GET'?{...extra}:{'Content-Type':'application/json',Origin:base,...extra},
  ...(body?{body:JSON.stringify(body)}:{}),
  signal:AbortSignal.timeout(11000)
 };
 const r=await fetch(base+path,opts);
 const data=await r.json().catch(()=>null);
 return {status:r.status,data,cookie:r.headers.get('set-cookie')};
}
test('actual Jose HTTP: health, tools, safe Gmail guide, signup, session persistence and login', {timeout:40000},async()=>{
 const root=mkdtempSync(path.join(tmpdir(),'hey-jose-http-'));
 const dbFile=path.join(root,'newly-created','nested','jose.json');
 let first,second,third;
 try{
  first=await serverSession(dbFile);
  const base=first.base;
  const health=await json(base,'/health');assert.equal(health.status,200);assert.equal(health.data.ok,true);
  const status=await json(base,'/api/chat/status');assert.equal(status.status,200);
  assert.equal(status.data.localPowerCount,20);
  assert.equal(status.data.futurePrviMainnetIntegration,'NO_GO_DESIGN_ONLY');
  assert.equal(status.data.financialPrviConnected,false);
  assert.equal(status.data.prviPricePegActive,false);
  assert.equal(status.data.selectedPrviDesign,'HEY_JOSE_VERIFIED_USERS_AND_USAGE_ONLY');
  assert.equal(status.data.dollarIndexUsed,false);
  assert.equal(status.data.usdStablecoinSelected,false);
  const future=await json(base,'/api/prvi/mainnet/plan');
  assert.equal(future.status,200);
  assert.equal(future.data.connected,false);
  assert.equal(future.data.chainId,null);
  assert.equal(future.data.financialMainnetLive,false);
  assert.equal(future.data.pricePegActive,false);
  assert.equal(future.data.paymentsEnabled,false);
  assert.equal(future.data.walletSigningEnabled,false);
  assert.equal(future.data.mintingEnabled,false);
  assert.equal(future.data.automaticMigrationEnabled,false);
  assert.equal(future.data.upstreamDemoEvmId,262144);
  assert.equal(future.data.priviTestDevnetId,772626);
  assert.equal(future.data.economicModel,'SELECTED_DESIGN_HEY_JOSE_USERS_AND_USAGE_ONLY');
  assert.equal(future.data.dollarIndexConfigured,false);
  assert.equal(future.data.usdStablecoinSelected,false);
  assert.equal(future.data.proposedUsageModel.usdDollarIndexUsed,false);
  assert.equal(future.data.proposedUsageModel.stablecoinSelected,false);
  assert.deepEqual(future.data.proposedUsageModel.allowedComponents,
    ['verified_active_users','verified_successful_usage']);
  const indexScenario={
    usersBaseline:100,usersCurrent:120,
    usageBaseline:1000,usageCurrent:1500,
    usersWeight:0.5,usageWeight:0.5
  };
  const oldRejected=await json(base,'/api/prvi/mainnet/index-preview','POST',{
    usageBaseline:1000,usageCurrent:1200,dollarIndexBaseline:100,
    dollarIndexCurrent:102,usageWeight:0.5,dollarWeight:0.5
  });
  assert.equal(oldRejected.status,410);
  const index=await json(base,'/api/prvi/mainnet/usage-index-preview','POST',indexScenario);
  assert.equal(index.status,200,JSON.stringify(index.data));
  assert.equal(index.data.kind,'HYPOTHETICAL_HEY_JOSE_USER_USAGE_INDEX');
  assert.equal(index.data.pricePegEnforced,false);
  assert.equal(index.data.realMarketPrice,null);
  assert.equal(index.data.oracleVerified,false);
  assert.equal(index.data.dollarIndexUsed,false);
  assert.ok(Math.abs(index.data.indexValue-134.16407865)<0.001);
  const wrongOrigin=await json(base,'/api/prvi/mainnet/usage-index-preview','POST',
    indexScenario,{Origin:'https://malicious.example'});
  assert.equal(wrongOrigin.status,403);
  const badIndex=await json(base,'/api/prvi/mainnet/usage-index-preview','POST',{
    ...indexScenario,dollarIndexCurrent:102
  });
  assert.equal(badIndex.status,400);

  assert.equal(status.data.missionControl,true);
  assert.equal(status.data.missionControlManualOnly,true);
  assert.equal(status.data.missionControlRequiresLoginForSync,true);
  const guestTasks=await json(base,'/api/tasks');
  assert.equal(guestTasks.status,401);
  const guestCreate=await json(base,'/api/tasks','POST',{title:'Forged task'});
  assert.equal(guestCreate.status,401);

  assert.equal(status.data.freePriviQuantumSimulator,true);
  assert.equal(status.data.quantumSimulatorMaxQubits,12);
  const quantumInfo=await json(base,'/api/quantum/info');
  assert.equal(quantumInfo.status,200);
  assert.equal(quantumInfo.data.physicalQpu,undefined);
  assert.equal(quantumInfo.data.hardwareQpu,false);
  assert.equal(quantumInfo.data.maxQubits,12);
  assert.equal(quantumInfo.data.paidCalls,false);
  const optimizationInfo=await json(base,'/api/quantum/optimization-info');
  assert.equal(optimizationInfo.status,200);
  assert.equal(optimizationInfo.data.maxVariables,16);
  assert.equal(optimizationInfo.data.qaoaExecuted,false);
  const cloudInfo=await json(base,'/api/quantum/cloud/info');
  assert.equal(cloudInfo.status,200);
  assert.equal(cloudInfo.data.enabled,false);
  assert.equal(cloudInfo.data.physicalQpu,false);
  const anonCloud=await json(base,'/api/quantum/cloud/jobs','POST',
    {qasm:'OPENQASM 2.0; qreg q[1]; h q[0];'});
  assert.equal(anonCloud.status,401);
  const quantumCircuit={qubits:2,gates:[{gate:'h',target:0},{gate:'cx',control:0,target:1}],shots:512,seed:77};
  const quantum=await json(base,'/api/quantum/simulate','POST',quantumCircuit);
  assert.equal(quantum.status,200,JSON.stringify(quantum.data));
  assert.equal(quantum.data.physicalQpu,false);
  assert.equal(quantum.data.probabilities.find(x=>x.state==='11').probability,0.5);
  assert.equal(Object.values(quantum.data.counts).reduce((a,b)=>a+b,0),512);
  assert.match(quantum.data.answer,/classical exact-statevector simulator/);
  const ghzGates=[{gate:'h',target:0},...Array.from({length:11},(_,i)=>({gate:'cx',control:i,target:i+1}))];
  const ghz12=await json(base,'/api/quantum/simulate','POST',{
    qubits:12,gates:ghzGates,shots:1024,seed:5
  });
  assert.equal(ghz12.status,200,JSON.stringify(ghz12.data));
  assert.equal(ghz12.data.qubits,12);
  assert.equal(ghz12.data.distributionTruncated,false);
  assert.equal(ghz12.data.countsTotal,1024);
  assert.equal(ghz12.data.probabilities.find(x=>x.state==='1'.repeat(12))?.probability,0.5);
  const uniform12=await json(base,'/api/quantum/simulate','POST',{
    qubits:12,gates:Array.from({length:12},(_,i)=>({gate:'h',target:i})),shots:1024
  });
  assert.equal(uniform12.status,200);
  assert.equal(uniform12.data.distributionTruncated,true);
  assert.ok(uniform12.data.returnedStates<=64);
  assert.equal(uniform12.data.countsTotal,1024);
  const quantumForbidden=await json(base,'/api/quantum/simulate','POST',quantumCircuit,{Origin:'https://evil.example'});
  assert.equal(quantumForbidden.status,403);
  const quantumInvalid=await json(base,'/api/quantum/simulate','POST',{qubits:33,gates:[]});
  assert.equal(quantumInvalid.status,400);
  assert.equal(status.data.gmailConfigured,false);
  const noAuth=await json(base,'/api/gmail/status');assert.equal(noAuth.status,401);
  const powers=await json(base,'/api/chat','POST',{message:'/powers'});
  assert.equal(powers.status,200);assert.match(powers.data.answer,/20 verified local tools/);
  const connect=await json(base,'/api/chat','POST',{message:'Connect my Gmail account'});
  assert.equal(connect.status,200);assert.equal(connect.data.gmailStatus,'operator_setup');
  assert.match(connect.data.answer,/GOOGLE_CLIENT_ID/);
  assert.doesNotMatch(connect.data.answer,/unable to connect to Gmail or any external services directly/i);
  const inbox=await json(base,'/api/chat','POST',{message:'Read my emails'});
  assert.equal(inbox.status,200);assert.equal(inbox.data.gmailStatus,'operator_setup');
  const bellChat=await json(base,'/api/chat','POST',{message:'Simulate a 2-qubit Bell state with Privi Quantum'});
  assert.equal(bellChat.status,200,JSON.stringify(bellChat.data));
  assert.equal(bellChat.data.deterministic,true);
  assert.equal(bellChat.data.quantum.physicalQpu,false);
  assert.equal(bellChat.data.quantum.probabilities.find(x=>x.state==='00').probability,0.5);
  const crossOrigin=await json(base,'/api/signup','POST',{email:'test@example.org',password:'mySecurePass1!'},{Origin:'https://evil.example'});
  assert.equal(crossOrigin.status,403);
  const accountEmail='test-'+Date.now()+'@example.org';
  const signup=await json(base,'/api/signup','POST',{email:accountEmail,password:'TestPassword-NotReal1!'});
  assert.equal(signup.status,201,JSON.stringify(signup.data));
  assert.ok(signup.cookie?.includes('HttpOnly'),String(signup.cookie));
  assert.ok(signup.cookie?.includes('SameSite=Lax'),String(signup.cookie));
  assert.ok(existsSync(dbFile),'signup must create missing DB parent directories');
  assert.ok(Object.keys(JSON.parse(readFileSync(dbFile))).includes('users'));
  const cookie=signup.cookie.split(';')[0];
  // Muse-style task board: account-scoped, manual actions only, evidence
  // required for completion, and protection from cross-account access.
  const initialTasks=await json(base,'/api/tasks','GET',null,{Cookie:cookie});
  assert.equal(initialTasks.status,200);
  assert.deepEqual(initialTasks.data.tasks,[]);
  assert.equal(initialTasks.data.execution,'MANUAL_USER_CONTROLLED');
  const badTaskOrigin=await json(base,'/api/tasks','POST',
    {title:'Forged'}, {Cookie:cookie,Origin:'https://evil.example'});
  assert.equal(badTaskOrigin.status,403);
  const createdTask=await json(base,'/api/tasks','POST',{
    title:'Publish verified Jose demo',
    steps:['Capture real demo','Review claims'],dueDate:'2026-12-01'
  },{Cookie:cookie});
  assert.equal(createdTask.status,201,JSON.stringify(createdTask.data));
  assert.equal(createdTask.data.status,'planned');
  assert.equal(createdTask.data.execution,'MANUAL_USER_CONTROLLED');
  assert.equal(createdTask.data.verification,'USER_MANAGED_NOT_AUTOMATICALLY_EXECUTED');
  assert.equal(createdTask.data.ownerId,undefined);
  const taskId=createdTask.data.id;
  assert.match(taskId,/^[a-f0-9-]{36}$/);
  const taskSteps=createdTask.data.steps.map(x=>x.id);
  const noEvidence=await json(base,'/api/tasks/'+taskId,'PATCH',{status:'completed'},
    {Cookie:cookie});
  assert.equal(noEvidence.status,400);
  const noSteps=await json(base,'/api/tasks/'+taskId,'PATCH',{
    status:'completed',completionNote:'Real recording uploaded by user'
  },{Cookie:cookie});
  assert.equal(noSteps.status,400);
  const invalidStep=await json(base,'/api/tasks/'+taskId,'PATCH',{
    doneSteps:['another-users-step']
  },{Cookie:cookie});
  assert.equal(invalidStep.status,400);
  const progress=await json(base,'/api/tasks/'+taskId,'PATCH',{
    status:'in_progress',doneSteps:[taskSteps[0]]
  },{Cookie:cookie});
  assert.equal(progress.status,200);
  assert.equal(progress.data.steps.filter(x=>x.done).length,1);
  const completedTask=await json(base,'/api/tasks/'+taskId,'PATCH',{
    status:'completed',doneSteps:taskSteps,
    completionNote:'Manually reviewed demo recording at test link'
  },{Cookie:cookie});
  assert.equal(completedTask.status,200,JSON.stringify(completedTask.data));
  assert.equal(completedTask.data.completionEvidenceType,'USER_REPORTED_NOT_INDEPENDENTLY_VERIFIED');
  assert.equal(completedTask.data.status,'completed');
  const taskList=await json(base,'/api/tasks','GET',null,{Cookie:cookie});
  assert.equal(taskList.status,200);
  assert.equal(taskList.data.tasks.length,1);
  assert.equal(taskList.data.tasks[0].status,'completed');

  const exactQubo=await json(base,'/api/quantum/optimize','POST',
    {Q:[[1,-2],[-2,1]],names:['a','b']},{Cookie:cookie});
  assert.equal(exactQubo.status,200,JSON.stringify(exactQubo.data));
  assert.equal(exactQubo.data.optimumCost,-2);
  assert.equal(exactQubo.data.qaoaExecuted,false);
  assert.equal(exactQubo.data.quantumHardware,false);
  const balanced=await json(base,'/api/quantum/optimize','POST',{
    jobs:[{name:'A',minutes:42},{name:'B',minutes:17},{name:'C',minutes:33}]
  },{Cookie:cookie});
  assert.equal(balanced.status,200);
  assert.equal(balanced.data.differenceMinutes,8);
  const invalidQubo=await json(base,'/api/quantum/optimize','POST',{Q:[[null]]},{Cookie:cookie});
  assert.equal(invalidQubo.status,400);
  const outsider=await json(base,'/api/quantum/cloud/jobs','POST',{
    qasm:'OPENQASM 2.0; qreg q[1]; h q[0];'
  },{Cookie:cookie});
  // The remote bridge is disabled before any account allowlist is evaluated.
  assert.equal(outsider.status,503);
  const cloudStatus=await json(base,'/api/chat','POST',{message:'/quantum cloud'},{Cookie:cookie});
  assert.equal(cloudStatus.status,200);
  assert.equal(cloudStatus.data.quantumCloud.enabled,false);
  const me=await json(base,'/api/me','GET',null,{Cookie:cookie});
  assert.equal(me.status,200);assert.equal(me.data.email,accountEmail);
  // Sidebar chat history: account-scoped, authorized, persisted, and bounded.
  const guestList=await json(base,'/api/conversations');
  assert.equal(guestList.status,401);
  const none=await json(base,'/api/conversations','GET',null,{Cookie:cookie});
  assert.equal(none.status,200);assert.deepEqual(none.data.conversations,[]);
  const invalidOrigin=await json(base,'/api/conversations','POST',{title:'CSRF'},{
   Cookie:cookie,Origin:'https://evil.example'
  });
  assert.equal(invalidOrigin.status,403);
  const created=await json(base,'/api/conversations','POST',{title:'Build a Privi token'},{Cookie:cookie});
  assert.equal(created.status,201,JSON.stringify(created.data));
  const conversationId=created.data.id;
  assert.match(conversationId,/^[a-f0-9-]{36}$/);
  const invalidMessage=await json(base,'/api/conversations/'+conversationId,'PUT',{
   messages:[{role:'system',content:'Forged system instructions'}]
  },{Cookie:cookie});
  assert.equal(invalidMessage.status,400);
  const saved=await json(base,'/api/conversations/'+conversationId,'PUT',{
   messages:[{role:'user',content:'Build a Web3 ledger'},{role:'assistant',content:'Use a testnet first.'}]
  },{Cookie:cookie});
  assert.equal(saved.status,200);
  assert.equal(saved.data.messageCount,2);
  const summary=await json(base,'/api/conversations','GET',null,{Cookie:cookie});
  assert.equal(summary.status,200);assert.equal(summary.data.conversations.length,1);
  assert.equal(summary.data.conversations[0].preview,'Build a Web3 ledger');
  const renamed=await json(base,'/api/conversations/'+conversationId,'PATCH',{
   title:'  Smart contract history  '
  },{Cookie:cookie});
  assert.equal(renamed.status,200);
  assert.equal(renamed.data.title,'Smart contract history');
  const detail=await json(base,'/api/conversations/'+conversationId,'GET',null,{Cookie:cookie});
  assert.equal(detail.status,200);assert.equal(detail.data.messages[1].content,'Use a testnet first.');
  const secondSignup=await json(base,'/api/signup','POST',{
   email:'isolated-'+Date.now()+'@example.org',password:'AnotherTestPassword-3!'
  });
  assert.equal(secondSignup.status,201);
  const secondCookie=secondSignup.cookie.split(';')[0];
  const crossTaskRead=await json(base,'/api/tasks/'+taskId,'GET',null,{Cookie:secondCookie});
  assert.equal(crossTaskRead.status,404);
  const crossTaskEdit=await json(base,'/api/tasks/'+taskId,'PATCH',
    {status:'blocked'}, {Cookie:secondCookie});
  assert.equal(crossTaskEdit.status,404);
  const crossTaskDelete=await json(base,'/api/tasks/'+taskId,'DELETE',undefined,
    {Cookie:secondCookie});
  assert.equal(crossTaskDelete.status,404);

  const crossRead=await json(base,'/api/conversations/'+conversationId,'GET',null,{Cookie:secondCookie});
  assert.equal(crossRead.status,404);
  const crossEdit=await json(base,'/api/conversations/'+conversationId,'PATCH',{title:'Stolen'},{Cookie:secondCookie});
  assert.equal(crossEdit.status,404);
  const crossDelete=await json(base,'/api/conversations/'+conversationId,'DELETE',undefined,{Cookie:secondCookie});
  assert.equal(crossDelete.status,404);

  const gmailAuth=await json(base,'/api/gmail/status','GET',null,{Cookie:cookie});
  assert.equal(gmailAuth.status,503);assert.match(gmailAuth.data.error,/OAuth configuration/);
  await stop(first.proc);first=null;
  second=await serverSession(dbFile);
  const login=await json(second.base,'/api/login','POST',{email:accountEmail,password:'TestPassword-NotReal1!'});
  // Account tasks are retained across controlled local server restarts.
  // Render without persistent disk remains non-durable across deployments.

  assert.equal(login.status,200,JSON.stringify(login.data));
  const restoredTask=await json(second.base,'/api/tasks/'+taskId,'GET',null,{
    Cookie:login.cookie.split(';')[0]
  });
  assert.equal(restoredTask.status,200);
  assert.equal(restoredTask.data.title,'Publish verified Jose demo');
  assert.equal(restoredTask.data.status,'completed');
  const removedTask=await json(second.base,'/api/tasks/'+taskId,'DELETE',undefined,{
    Cookie:login.cookie.split(';')[0]
  });
  assert.equal(removedTask.status,200);
  assert.equal(removedTask.data.deleted,true);
  const taskGone=await json(second.base,'/api/tasks/'+taskId,'GET',null,{
    Cookie:login.cookie.split(';')[0]
  });
  assert.equal(taskGone.status,404);

  const reloaded=await json(second.base,'/api/conversations/'+conversationId,'GET',null,{
   Cookie:login.cookie.split(';')[0]
  });
  assert.equal(reloaded.status,200);
  assert.equal(reloaded.data.title,'Smart contract history');
  const deleted=await json(second.base,'/api/conversations/'+conversationId,'DELETE',undefined,{
   Cookie:login.cookie.split(';')[0]
  });
  assert.equal(deleted.status,200);assert.equal(deleted.data.deleted,true);
  const gone=await json(second.base,'/api/conversations/'+conversationId,'GET',null,{
   Cookie:login.cookie.split(';')[0]
  });
  assert.equal(gone.status,404);

  const wrong=await json(second.base,'/api/login','POST',{email:accountEmail,password:'WrongPassword-1'});
  assert.equal(wrong.status,401);
  const html=await fetch(second.base+'/chat.html',{signal:AbortSignal.timeout(2000)});
  assert.equal(html.status,200);const markup=await html.text();
  assert.match(markup,/chat-gmail\.js/);assert.match(markup,/chat-memory\.js/);
  // Professional sidebar: all existing tools and account history remain reachable.
  assert.match(markup,/id="sidebarChatCount"/);
  assert.match(markup,/id="sidebarTasks"/);
  assert.match(markup,/sidebar-nav-item/);
  assert.match(markup,/Recent conversations/);
  assert.match(markup,/Build &amp; explore/);
  assert.match(markup,/id="sidebarAccountSubtitle"/);
  const sidebarAsset=await fetch(second.base+'/chat-sidebar.js',{signal:AbortSignal.timeout(3000)});
  assert.equal(sidebarAsset.status,200);
  assert.match(sidebarAsset.headers.get('content-type')||'',/application\/javascript/);
  const sidebarCode=await sidebarAsset.text();
  assert.match(sidebarCode,/function syncDrawer/);
  assert.match(sidebarCode,/sidebarChatCount/);
  assert.match(sidebarCode,/PREFERENCE_KEY/);
  assert.match(sidebarCode,/\/login\.html\?next=%2Fchat\.html/);

  assert.match(markup,/id="taskPanel"/);
  assert.match(markup,/id="taskToggle"/);
  assert.match(markup,/data-action="tasks"/);
  assert.match(markup,/jose-tasks\.js/);
  const taskScript=await fetch(second.base+'/jose-tasks.js',{signal:AbortSignal.timeout(2500)});
  assert.equal(taskScript.status,200);
  assert.match(taskScript.headers.get('content-type')||'',/application\/javascript/);
  assert.match(await taskScript.text(),/MANUAL_USER_CONTROLLED/);

  // The no-cost voice feature is a browser module. Both module files must be
  // delivered with a JavaScript MIME type or the browser will reject imports.
  assert.match(markup,/priviVoicePanel/);
  assert.match(markup,/Quantum simulation/);
  assert.match(markup,/showQuantumResult\(data.quantum\)/);
  assert.match(markup,/Download JSON/);
  assert.match(markup,/QUBO optimizer/);
  assert.match(markup,/Balance work/);
  assert.match(markup,/showOptimizationResult\(data.optimization\)/);
  assert.match(markup,/Quantum project status/);
  assert.match(markup,/priviVoiceAuto/);
  assert.match(markup,/priviVoiceLanguage/);
  assert.match(markup,/priviVoicePause/);
  assert.match(markup,/priviVoiceAutoSend/);
  assert.match(markup,/recognition\.lang=window\.priviVoice/);
  assert.match(markup,/window\.priviVoice\?\.autoSend/);
  assert.match(markup,/priviVoiceBtn/);
  assert.match(markup,/privi-voice\.js/);
  for(const voicePath of ['/privi-voice.js','/privi-voice-core.mjs']){
    const response=await fetch(second.base+voicePath,{signal:AbortSignal.timeout(2000)});
    assert.equal(response.status,200,voicePath);
    assert.match(response.headers.get('content-type')||'',/application\/javascript/,voicePath);
    const source=await response.text();
    assert.ok(source.includes('Privi Voice'),voicePath);
  }
  await stop(second.proc);second=null;
  third=await serverSession(dbFile,{JOSE_ADMIN_EMAIL:accountEmail,JOSE_ADMIN_PASSWORD:'AnotherTestPassword-2!'});
  const adminLogin=await json(third.base,'/api/login','POST',{email:accountEmail,password:'AnotherTestPassword-2!'});
  assert.equal(adminLogin.status,200,'admin bootstrap should update existing account without crashing');
  const stored=JSON.parse(readFileSync(dbFile));
  assert.equal(Object.values(stored.users).find(u=>u.email===accountEmail)?.role,'admin');
 }finally{
  if(first)await stop(first.proc);
  if(second)await stop(second.proc);
  if(third)await stop(third.proc);
  rmSync(root,{recursive:true,force:true});
 }
});
