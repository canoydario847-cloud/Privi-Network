// Hey Jose Gmail API client: explicit user-scoped read and send only.
// OAuth tokens never go to the browser or to the AI provider.
// Data is untrusted; Gmail messages are displayed as text, not executed.
import { GMAIL_SCOPES } from './plugins/google.js';

const API='https://gmail.googleapis.com/gmail/v1/users/me';
const TOKEN='https://oauth2.googleapis.com/token';
const TIMEOUT_MS=12000;
const ID=/^[a-zA-Z0-9]{8,50}$/;
const EMAIL=/^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$/i;
const MAX_TEXT=16000;
const LIMIT=8;

export function validateEmailDraft(v){
  if(!v||typeof v!=='object'||Array.isArray(v))throw Error('Enter recipient, subject and message.');
  const to=String(v.to||'').trim(),subject=String(v.subject||'').trim(),text=String(v.text||'').trim();
  if(!EMAIL.test(to)||to.length>254||/[\r\n]/.test(to))throw Error('Provide one valid recipient email address.');
  if(!subject||subject.length>180||/[\r\n\u0000-\u001f]/.test(subject))throw Error('Subject must be 1–180 characters on one line.');
  if(!text||text.length>MAX_TEXT||text.includes('\0'))throw Error('Message must be 1–16,000 characters.');
  return Object.freeze({to,subject,text});
}
export function rawEmail(v){
  const draft=validateEmailDraft(v);
  const subjectEncoded='=?UTF-8?B?'+Buffer.from(draft.subject,'utf8').toString('base64')+'?=';
  const header=['To: '+draft.to,'Subject: '+subjectEncoded,'MIME-Version: 1.0',
    'Content-Type: text/plain; charset=UTF-8','Content-Transfer-Encoding: base64'].join('\r\n');
  const body=Buffer.from(draft.text,'utf8').toString('base64').replace(/.{1,76}/g,'$&\r\n').trimEnd();
  return Buffer.from(header+'\r\n\r\n'+body,'utf8').toString('base64url');
}
function header(headers,name){
  const item=Array.isArray(headers)?headers.find(h=>String(h?.name||'').toLowerCase()===name):null;
  return String(item?.value||'').slice(0,250).replace(/[\r\n]/g,' ');
}
export function safeMessage(row,{body=false}={}){
  if(!row||typeof row!=='object'||!ID.test(String(row.id||'')))throw Error('Invalid Gmail message metadata.');
  const result={
    id:String(row.id),threadId:String(row.threadId||''),from:header(row.payload?.headers,'from'),
    to:header(row.payload?.headers,'to'),subject:header(row.payload?.headers,'subject')||'(no subject)',
    date:header(row.payload?.headers,'date'),snippet:String(row.snippet||'').slice(0,600),
    unread:Array.isArray(row.labelIds)&&row.labelIds.includes('UNREAD')
  };
  if(body){
    function textPart(part,depth=0){
      if(depth>6||!part||typeof part!=='object')return null;
      if(part.mimeType==='text/plain'&&typeof part.body?.data==='string'){
        try{return Buffer.from(part.body.data,'base64url').toString('utf8').slice(0,8500);}catch{return null;}
      }
      for(const child of part.parts||[]){
        const t=textPart(child,depth+1);if(t)return t;
      }
      return null;
    }
    result.body=textPart(row.payload)||result.snippet;
    result.bodyTruncated=result.body.length>=8500;
  }
  return result;
}
export function createGmailClient({getConnection,setConnection,encrypt,decrypt,fetchImpl=globalThis.fetch,clock=()=>Date.now()}){
  if(typeof getConnection!=='function'||typeof setConnection!=='function')throw Error('Connection store required.');
  const refreshInFlight=new Map();
  async function call(url,init={},timeoutMs=TIMEOUT_MS){
    const ctrl=new AbortController();const timer=setTimeout(()=>ctrl.abort(),timeoutMs);
    try{return await fetchImpl(url,{...init,redirect:'error',signal:ctrl.signal});}
    finally{clearTimeout(timer);}
  }
  function connection(userId){
    const record=getConnection(userId,'google');
    if(!record?.accessTokenEnc)throw Object.assign(Error('Connect Gmail in Jose first.'),{status:409});
    const scopes=Array.isArray(record.scopes)?record.scopes:[];
    if(!GMAIL_SCOPES.every(s=>scopes.includes(s)))throw Object.assign(Error('Reconnect Gmail to authorize read and send permissions.'),{status:409});
    return record;
  }
  async function token(userId){
    let current=connection(userId);
    if(!current.expiresAt||current.expiresAt>clock()+90000)return decrypt(current.accessTokenEnc);
    if(!current.refreshTokenEnc)throw Object.assign(Error('Gmail permission expired. Reconnect Gmail.'),{status:409});
    if(refreshInFlight.has(userId))return refreshInFlight.get(userId);
    const p=(async()=>{
      const resp=await call(TOKEN,{
        method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},
        body:new URLSearchParams({
          client_id:process.env.GOOGLE_CLIENT_ID||'',client_secret:process.env.GOOGLE_CLIENT_SECRET||'',
          grant_type:'refresh_token',refresh_token:decrypt(current.refreshTokenEnc)
        }).toString()
      });
      let data;try{data=await resp.json();}catch{data={};}
      if(!resp.ok||!data.access_token)throw Object.assign(Error('Gmail authorization expired. Please reconnect your Gmail account.'),{status:409});
      current={...current,accessTokenEnc:encrypt(data.access_token),expiresAt:clock()+Math.min(86400,Number(data.expires_in)||3600)*1000};
      setConnection(userId,'google',current);
      return data.access_token;
    })();
    refreshInFlight.set(userId,p);
    try{return await p;}finally{refreshInFlight.delete(userId);}
  }
  async function gmail(userId,path,{method='GET',body}={}){
    const access=await token(userId);
    const response=await call(API+path,{
      method,headers:{Authorization:'Bearer '+access,Accept:'application/json',
        ...(body?{'Content-Type':'application/json'}:{})},
      ...(body?{body:JSON.stringify(body)}:{})
    });
    let data;try{data=await response.json();}catch{data={};}
    if(!response.ok){
      const message=response.status===401||response.status===403
        ? 'Gmail denied permission. Reconnect your account or check Google OAuth scopes.'
        :response.status===429?'Gmail rate limit reached; try again later.'
        :response.status===404?'Message not found in this Gmail account.'
        :'Gmail could not complete this request.';
      throw Object.assign(Error(message),{status:response.status===404?404:response.status===429?429:502});
    }
    return data;
  }
  async function inbox(userId,query=''){
    if(typeof query!=='string'||query.length>180)throw Object.assign(Error('Gmail search must be under 180 characters.'),{status:400});
    const params=new URLSearchParams({maxResults:String(LIMIT)});
    if(query.trim())params.set('q',query.trim());
    else params.set('labelIds','INBOX');
    const results=await gmail(userId,'/messages?'+params);
    const ids=Array.isArray(results.messages)?results.messages.slice(0,LIMIT).map(m=>m.id).filter(id=>ID.test(id)):[];
    const rows=await Promise.all(ids.map(id=>gmail(userId,'/messages/'+id+'?format=metadata')
      .then(row=>safeMessage(row)).catch(()=>null)));
    return {messages:rows.filter(Boolean),query:query.trim(),count:rows.filter(Boolean).length,account:'connected Gmail'};
  }
  async function read(userId,id){
    if(!ID.test(String(id||'')))throw Object.assign(Error('Invalid Gmail message ID.'),{status:400});
    return safeMessage(await gmail(userId,'/messages/'+encodeURIComponent(id)+'?format=full'),{body:true});
  }
  async function send(userId,draft){
    const sent=await gmail(userId,'/messages/send',{method:'POST',body:{raw:rawEmail(draft)}});
    return {id:String(sent.id||''),threadId:String(sent.threadId||''),sent:true};
  }
  return Object.freeze({connection,token,inbox,read,send});
}
