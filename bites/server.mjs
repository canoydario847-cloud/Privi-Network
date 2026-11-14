import http from 'node:http';
import { createHmac, randomBytes, timingSafeEqual } from 'node:crypto';

const PORT = Number(process.env.PORT || 10000);
const SECRET = process.env.BITES_SECRET || randomBytes(32).toString('hex');
const ADMIN_KEY = process.env.BITES_ADMIN_KEY || '';
const MAX_TTL_SECONDS = 900; // 15 minutes
const revoked = new Map(); // Demo-only: use shared durable storage for production revocation
const base64url = (x) => Buffer.from(x).toString('base64url');
const sign = (body) => createHmac('sha256', SECRET).update(body).digest('base64url');
const safeEqual = (a,b) => { const aa=Buffer.from(String(a)), bb=Buffer.from(String(b)); return aa.length===bb.length && timingSafeEqual(aa,bb); };
const send = (res, status, value) => { res.writeHead(status,{'content-type':'application/json; charset=utf-8','cache-control':'no-store','x-content-type-options':'nosniff'}); res.end(JSON.stringify(value)); };
const read = async (req) => { let data=''; for await (const chunk of req) { data+=chunk; if(data.length>16384) throw new Error('Request too large'); } return data?JSON.parse(data):{}; };
const authorized = (req) => Boolean(ADMIN_KEY) && safeEqual(req.headers.authorization||'', 'Bearer '+ADMIN_KEY);
const validText=(s,max=128)=>typeof s==='string'&&s.length>0&&s.length<=max;
const issue = ({audience,subject,scopes,ttl_seconds=300}) => {
  if(!validText(audience)||!validText(subject)||!Array.isArray(scopes)||scopes.length<1||scopes.length>16||!scopes.every(s=>validText(s,80))||!Number.isInteger(ttl_seconds)||ttl_seconds<1||ttl_seconds>MAX_TTL_SECONDS) throw new Error('Invalid audience, subject, scopes or TTL');
  const now=Math.floor(Date.now()/1000);
  const payload={v:1,iss:'privi-bites',sub:subject,aud:audience,scp:[...new Set(scopes)],iat:now,exp:now+ttl_seconds,jti:randomBytes(16).toString('hex')};
  const encoded=base64url(JSON.stringify(payload));
  return {bite:'pb1.'+encoded+'.'+sign('pb1.'+encoded),expires_at:new Date(payload.exp*1000).toISOString(),scopes:payload.scp};
};
const verify = ({bite,audience,scope}) => {
  if(!validText(bite,4096)||!validText(audience)||!validText(scope,80)) return {valid:false,reason:'invalid_request'};
  const parts=bite.split('.');
  if(parts.length!==3||parts[0]!=='pb1'||!/^[A-Za-z0-9_-]+$/.test(parts[1])||!/^[A-Za-z0-9_-]+$/.test(parts[2])) return {valid:false,reason:'invalid_format'};
  const expected=sign('pb1.'+parts[1]);
  if(!safeEqual(parts[2],expected)) return {valid:false,reason:'bad_signature'};
  let p; try {p=JSON.parse(Buffer.from(parts[1],'base64url').toString());}catch{return {valid:false,reason:'invalid_payload'};}
  const now=Math.floor(Date.now()/1000);
  if(p.v!==1||p.iss!=='privi-bites'||!validText(p.jti,64)||!Number.isInteger(p.exp)||!Number.isInteger(p.iat)||p.iat>now+30||p.exp<=now||p.exp-p.iat>MAX_TTL_SECONDS) return {valid:false,reason:'expired_or_invalid'};
  if(revoked.has(p.jti)) return {valid:false,reason:'revoked'};
  if(p.aud!==audience||!Array.isArray(p.scp)||!p.scp.includes(scope)) return {valid:false,reason:'insufficient_permission'};
  return {valid:true,subject:p.sub,audience:p.aud,scope,expires_at:new Date(p.exp*1000).toISOString(),jti:p.jti};
};
const revoke=({bite})=>{
  if(!validText(bite,4096)) throw new Error('Invalid bite');
  const parts=bite.split('.'); if(parts.length!==3||parts[0]!=='pb1'||!safeEqual(parts[2],sign('pb1.'+parts[1]))) throw new Error('Invalid signature');
  const p=JSON.parse(Buffer.from(parts[1],'base64url').toString());
  if(!validText(p.jti,64)||!Number.isInteger(p.exp)) throw new Error('Invalid payload');
  revoked.set(p.jti,p.exp); return {revoked:true,jti:p.jti};
};
const mcp=(message)=>{
  const {id,method,params={}}=message;
  if(method==='notifications/initialized') return null;
  if(method==='initialize') return {jsonrpc:'2.0',id,result:{protocolVersion:'2025-03-26',capabilities:{tools:{}},serverInfo:{name:'privi-bites',version:'0.1.0'}}};
  if(method==='ping') return {jsonrpc:'2.0',id,result:{}};
  if(method==='tools/list') return {jsonrpc:'2.0',id,result:{tools:[{name:'bites_verify',description:'Validate a short-lived signed Privi Bite for an exact audience and permission; never send a Bite to an untrusted server.',inputSchema:{type:'object',properties:{bite:{type:'string'},audience:{type:'string'},scope:{type:'string'}},required:['bite','audience','scope']}}]}};
  if(method==='tools/call'&&params.name==='bites_verify') return {jsonrpc:'2.0',id,result:{content:[{type:'text',text:JSON.stringify(verify(params.arguments||{}))}]}};
  return {jsonrpc:'2.0',id,error:{code:-32601,message:'Method not found'}};
};
const server=http.createServer(async(req,res)=>{
  const url=new URL(req.url,'http://localhost');
  // Never set tracking cookies; Bites are explicitly carried in Authorization headers.
  if(req.method==='GET'&&url.pathname==='/health') return send(res,200,{status:'ok',service:'privi-bites',version:'0.1.0',revocation_storage:'memory-only'});
  if(req.method==='GET'&&url.pathname==='/') return send(res,200,{name:'Privi Bites',description:'Scoped short-lived signed permissions; not a drop-in replacement for browser session cookies',endpoints:['/v1/issue','/v1/verify','/v1/revoke','/mcp','/health']});
  if(req.method!=='POST') return send(res,404,{error:'not_found'});
  try {
    if(url.pathname==='/v1/issue'||url.pathname==='/v1/revoke') {
      if(!authorized(req)) return send(res,401,{error:'admin_auth_required'});
    }
    const input=await read(req);
    if(url.pathname==='/v1/issue') return send(res,200,issue(input));
    if(url.pathname==='/v1/verify') return send(res,200,verify(input));
    if(url.pathname==='/v1/revoke') return send(res,200,revoke(input));
    if(url.pathname==='/mcp') {const output=mcp(input);return output?send(res,200,output):(res.writeHead(202),res.end());}
    return send(res,404,{error:'not_found'});
  } catch(e) { return send(res,400,{error:'invalid_request',detail:String(e.message).slice(0,100)}); }
});
setInterval(()=>{const now=Math.floor(Date.now()/1000);for(const [k,exp] of revoked) if(exp<now) revoked.delete(k);},60000).unref();
if (!process.argv[1]?.endsWith('/test.mjs') && !process.env.NODE_TEST_CONTEXT) server.listen(PORT,'0.0.0.0',()=>console.log('Privi Bites listening on '+PORT));
export {issue,verify,revoke};
