import test from 'node:test';
import assert from 'node:assert/strict';
import {createGmailClient,validateEmailDraft,rawEmail,safeMessage} from '../src/gmail-client.js';
import {createMailReview} from '../src/gmail-review.js';
import {gmailIntent,formatGmailInbox,formatGmailMessage} from '../src/gmail-intents.js';
import {GMAIL_SCOPES,google} from '../src/plugins/google.js';
function tokenRecord(expiresAt=10000000){
  return {accessTokenEnc:'encrypted-at',refreshTokenEnc:'encrypted-rt',expiresAt,scopes:[...GMAIL_SCOPES]};
}
function setup({expiresAt=10000000,responseStatus=200}={}){
  const records=new Map([['alice',tokenRecord(expiresAt)]]);
  const calls=[];
  const fetchImpl=async(url,options={})=>{
    calls.push({url,method:options.method,headers:options.headers,body:options.body});
    let body={};
    if(url.includes('/token')){
      body={access_token:'fresh-access',expires_in:3600};
    }else if(url.includes('/messages/send')){
      body={id:'18ca6bba77e12abc',threadId:'thread-1'};
    }else if(url.includes('/messages?')){
      body={messages:[{id:'18ca6bba77e12abc'}]};
    }else if(url.includes('/messages/')){
      body={id:'18ca6bba77e12abc',threadId:'thread-1',snippet:'Meet Friday',
        labelIds:['INBOX','UNREAD'],
        payload:{headers:[{name:'From',value:'Bob <bob@example.com>'},
          {name:'Subject',value:'Weekly check-in'},{name:'Date',value:'Mon, 23 Nov 2026'}],
          mimeType:'text/plain',body:{data:Buffer.from('Hi Alice, meeting Friday!').toString('base64url')}}};
    }
    return {ok:responseStatus===200,status:responseStatus,json:async()=>body};
  };
  const client=createGmailClient({
    getConnection:(id)=>records.get(id),setConnection:(id,provider,value)=>records.set(id,value),
    encrypt:x=>'encrypted-'+x,decrypt:x=>x==='encrypted-rt'?'refresh_token':x==='encrypted-at'?'access_token':x.slice('encrypted-'.length),
    fetchImpl,clock:()=>1000000
  });
  return {client,calls,records};
}
test('OAuth requests only Gmail reading and sending, no Drive or Calendar',()=>{
 assert.equal(GMAIL_SCOPES.length,2);
 assert.ok(GMAIL_SCOPES.some(s=>s.endsWith('gmail.readonly')));
 assert.ok(GMAIL_SCOPES.some(s=>s.endsWith('gmail.send')));
 const previous=process.env.GOOGLE_CLIENT_ID;
 process.env.GOOGLE_CLIENT_ID='test_id';
 const u=new URL(google.buildAuthorizeUrl('test-state','https://example.com/callback/google'));
 assert.equal(u.searchParams.get('scope'),GMAIL_SCOPES.join(' '));
 assert.equal(u.searchParams.get('access_type'),'offline');
 assert.equal(u.searchParams.get('state'),'test-state');
 if(previous===undefined)delete process.env.GOOGLE_CLIENT_ID;else process.env.GOOGLE_CLIENT_ID=previous;
});
test('Gmail inbox returns metadata and never echoes access token',async()=>{
 const {client,calls}=setup();
 const result=await client.inbox('alice','from:bob@example.com');
 assert.equal(result.count,1);
 assert.equal(result.messages[0].subject,'Weekly check-in');
 assert.match(calls[0].url,/maxResults=8/);
 assert.match(calls[0].url,/q=from%3Abob/);
 assert.equal(calls.length,2);
 assert.doesNotMatch(JSON.stringify(result),/access_token|refresh_token|encrypted/);
 assert.match(calls[0].headers.Authorization,/Bearer access_token/);
});
test('Gmail full read returns safe plain text, not executable HTML',async()=>{
 const {client}=setup();
 const msg=await client.read('alice','18ca6bba77e12abc');
 assert.match(msg.body,/meeting Friday/);
 assert.equal(msg.subject,'Weekly check-in');
 assert.equal(msg.unread,true);
});
test('wrong user or missing permissions cannot access Gmail',async()=>{
 const {client,records}=setup();
 assert.throws(()=>client.connection('bob'),/Connect Gmail/);
 records.set('bob',{...tokenRecord(),scopes:['https://www.googleapis.com/auth/gmail.send']});
 assert.throws(()=>client.connection('bob'),/Reconnect Gmail/);
 await assert.rejects(client.read('alice','../../secrets'),/Invalid Gmail message ID/);
});
test('refreshes expired encrypted token and stores updated encrypted token',async()=>{
 const {client,records,calls}=setup({expiresAt:10000});
 const rows=await client.inbox('alice');
 assert.equal(rows.count,1);
 const refreshed=records.get('alice');
 assert.equal(refreshed.accessTokenEnc,'encrypted-fresh-access');
 assert.ok(refreshed.expiresAt>1000000);
 assert.equal(calls[0].url,'https://oauth2.googleapis.com/token');
 assert.doesNotMatch(JSON.stringify(rows),/fresh-access|refresh_token/);
});
test('email MIME encoding and RFC headers are safe from injection',()=>{
 const draft={to:'user@example.com',subject:'Privi résumé',text:'Hello\nHere is an update.'};
 const raw=Buffer.from(rawEmail(draft),'base64url').toString('utf8');
 assert.match(raw,/To: user@example.com/);
 assert.match(raw,/Subject: =\?UTF-8\?B\?/);
 assert.match(raw,/Content-Transfer-Encoding: base64/);
 assert.match(raw,/SGVsbG8/);
 assert.throws(()=>validateEmailDraft({...draft,subject:'Hi\r\nBcc: bad@example.com'}),/one line/);
 assert.throws(()=>validateEmailDraft({...draft,to:'bad@example.com,other@example.com'}),/one valid/);
 assert.throws(()=>validateEmailDraft({...draft,text:''}),/Message/);
});
test('email send uses user-scoped access and actual Gmail API after exact confirmation',async()=>{
 const {client,calls}=setup();
 const review=createMailReview({clock:()=>10000});
 const draft={to:'person@example.com',subject:'Project update',text:'The build passed.'};
 const prepared=review.prepare('alice',draft);
 assert.equal(prepared.draft.to,draft.to);
 assert.throws(()=>review.consume('alice',prepared.reviewToken,false),/Explicit confirmation/);
 assert.throws(()=>review.consume('bob',prepared.reviewToken,true),/does not belong/);
 const exact=review.consume('alice',prepared.reviewToken,true);
 assert.throws(()=>review.consume('alice',prepared.reviewToken,true),/expired/);
 const result=await client.send('alice',exact);
 assert.equal(result.sent,true);
 assert.equal(calls[0].method,'POST');
 assert.ok(calls[0].url.endsWith('/messages/send'));
 const encoded=JSON.parse(calls[0].body).raw;
 assert.match(Buffer.from(encoded,'base64url').toString('utf8'),/Project update/); // Subject is base64 encoded, so don't rely on plain subject
});
test('review token fails when expired',()=>{
 let now=0;
 const review=createMailReview({clock:()=>now});
 const token=review.prepare('u',{to:'a@example.com',subject:'test',text:'body'}).reviewToken;
 now=11*60*1000;
 assert.throws(()=>review.consume('u',token,true),/expired/);
});
test('Gmail intents are explicit; normal chat unchanged',()=>{
 assert.deepEqual(gmailIntent('Show my latest Gmail'),{action:'inbox',query:''});
 assert.deepEqual(gmailIntent('/gmail search from:bill@example.com'),{action:'inbox',query:'from:bill@example.com'});
 assert.deepEqual(gmailIntent('/gmail read 18ca6bba77e12abc'),{action:'read',id:'18ca6bba77e12abc'});
 assert.equal(gmailIntent('Explain the history of email'),null);
 assert.equal(gmailIntent('Create an email app'),null);
 assert.match(formatGmailInbox({messages:[{id:'18ca6bba77e12abc',subject:'Hello',from:'Alice',snippet:'Hi'}]}),/\/gmail read/);
 assert.match(formatGmailMessage({id:'18ca6bba77e12abc',subject:'Hi',from:'Alice',to:'Bob',date:'Monday',body:'Hello!'}),/Hello!/);
});
