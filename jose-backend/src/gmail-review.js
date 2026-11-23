// One-time exact-message send review. No AI or email content can authorize send.
// In-memory tokens expire; a restart causes review to fail safely.
import { randomBytes } from 'node:crypto';
import { validateEmailDraft } from './gmail-client.js';
const TTL=10*60*1000,MAX=200;
export function createMailReview({clock=()=>Date.now()}={}){
  const pending=new Map();
  function tidy(){
    for(const [id,row] of pending)if(clock()>row.expiresAt)pending.delete(id);
    if(pending.size>MAX){for(const id of pending.keys()){pending.delete(id);if(pending.size<=MAX)break;}}
  }
  function prepare(userId,body){
    if(!userId)throw Error('Sign in first.');
    const draft=validateEmailDraft(body);
    tidy();
    const reviewToken=randomBytes(24).toString('base64url');
    pending.set(reviewToken,{userId,draft,expiresAt:clock()+TTL});
    return {reviewToken,draft,expiresInSeconds:TTL/1000,
      instruction:'Review the exact recipient, subject and message before explicitly clicking Send email.'};
  }
  function consume(userId,token,confirmSend){
    if(confirmSend!==true)throw Error('Explicit confirmation is required.');
    if(typeof token!=='string'||token.length>100)throw Error('Invalid send review token.');
    tidy();
    const row=pending.get(token);
    if(!row||row.userId!==userId)throw Error('The email review expired or does not belong to this account.');
    pending.delete(token); // prevents duplicate sends, even across parallel requests
    return row.draft;
  }
  return Object.freeze({prepare,consume});
}
