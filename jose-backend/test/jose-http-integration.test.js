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
async function serverSession(dbFile){
 const port=await freePort(),base='http://127.0.0.1:'+port;
 const env={...process.env,PORT:String(port),BASE_URL:base,DB_FILE:dbFile};
 for(const key of ['JOSE_ADMIN_EMAIL','JOSE_ADMIN_PASSWORD','JOSE_AI_API_KEY','GOOGLE_CLIENT_ID','GOOGLE_CLIENT_SECRET'])delete env[key];
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
 let first,second;
 try{
  first=await serverSession(dbFile);
  const base=first.base;
  const health=await json(base,'/health');assert.equal(health.status,200);assert.equal(health.data.ok,true);
  const status=await json(base,'/api/chat/status');assert.equal(status.status,200);
  assert.equal(status.data.localPowerCount,20);
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
  const gmailAuth=await json(base,'/api/gmail/status','GET',null,{Cookie:cookie});
  assert.equal(gmailAuth.status,503);assert.match(gmailAuth.data.error,/Google OAuth/);
  await stop(first.proc);first=null;
  second=await serverSession(dbFile);
  const login=await json(second.base,'/api/login','POST',{email:accountEmail,password:'TestPassword-NotReal1!'});
  assert.equal(login.status,200,JSON.stringify(login.data));
  const wrong=await json(second.base,'/api/login','POST',{email:accountEmail,password:'WrongPassword-1'});
  assert.equal(wrong.status,401);
  const html=await fetch(second.base+'/chat.html',{signal:AbortSignal.timeout(2000)});
  assert.equal(html.status,200);const markup=await html.text();
  assert.match(markup,/chat-gmail\.js/);assert.match(markup,/chat-memory\.js/);
 }finally{
  if(first)await stop(first.proc);
  if(second)await stop(second.proc);
  rmSync(root,{recursive:true,force:true});
 }
});
