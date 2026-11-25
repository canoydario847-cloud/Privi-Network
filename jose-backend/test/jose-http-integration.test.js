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
  assert.equal(status.data.freePriviQuantumSimulator,true);
  assert.equal(status.data.quantumSimulatorMaxQubits,12);
  const quantumInfo=await json(base,'/api/quantum/info');
  assert.equal(quantumInfo.status,200);
  assert.equal(quantumInfo.data.physicalQpu,undefined);
  assert.equal(quantumInfo.data.hardwareQpu,false);
  assert.equal(quantumInfo.data.maxQubits,12);
  assert.equal(quantumInfo.data.paidCalls,false);
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
  assert.equal(login.status,200,JSON.stringify(login.data));
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
  // The no-cost voice feature is a browser module. Both module files must be
  // delivered with a JavaScript MIME type or the browser will reject imports.
  assert.match(markup,/priviVoicePanel/);
  assert.match(markup,/Quantum simulation/);
  assert.match(markup,/showQuantumResult\(data.quantum\)/);
  assert.match(markup,/Download JSON/);
  assert.match(markup,/Quantum status/);
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
