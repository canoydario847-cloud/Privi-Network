'use strict';
/** Privi Wall agent call authorization prototype. Not RFC 9421.
 * Verify signature BEFORE consuming nonce. Caller must provide tenant-scoped
 * trusted key lookup; never trust public keys supplied by the request.
 * Single-process replay store: NOT safe for distributed production.
 */
const {verify, createHash, createPublicKey} = require('node:crypto');
const {BoundedReplayGuard} = require('./bounded_replay_guard.cjs');
const MAX_BODY_BYTES = 65536;
const ID = /^[A-Za-z0-9_-]{1,64}$/;
const HEX = /^[a-f0-9]{32,64}$/;
function bytesForCall(call) {
  if (!call || typeof call !== 'object' || Array.isArray(call)) throw Error('invalid call');
  const {tenant, agent, method, path, nonce, expiresAt, bodyHash} = call;
  if (![tenant,agent].every(x=>typeof x==='string'&&ID.test(x)))throw Error('invalid identity');
  if(typeof method!=='string'||!['POST','PUT'].includes(method)||typeof path!=='string'||!/^\/agent\/[A-Za-z0-9_/-]{1,128}$/.test(path)||path.includes('//')||path.includes('..'))throw Error('invalid route');
  if(typeof nonce!=='string'||!HEX.test(nonce)||!Number.isSafeInteger(expiresAt)||typeof bodyHash!=='string'||!/^[a-f0-9]{64}$/.test(bodyHash))throw Error('invalid signed fields');
  return Buffer.from(JSON.stringify(['privi-wall-agent-call-v1',tenant,agent,method,path,nonce,expiresAt,bodyHash]),'utf8');
}
function authorizeCall({call,body,signature,lookupKey,replayGuard}) {
  const signed=bytesForCall(call);
  if(typeof body!=='string'||Buffer.byteLength(body,'utf8')>MAX_BODY_BYTES)throw Error('invalid body');
  if(createHash('sha256').update(body).digest('hex')!==call.bodyHash)throw Error('body mismatch');
  if(typeof lookupKey!=='function'||!(replayGuard instanceof BoundedReplayGuard))throw Error('invalid verifier');
  if(typeof signature!=='string'||!/^[A-Za-z0-9_-]{86}$/.test(signature))throw Error('invalid signature');
  const sig=Buffer.from(signature,'base64url');
  if(sig.length!==64)throw Error('invalid signature');
  // Key registry must be provisioned out-of-band and scoped to tenant+agent.
  const key=lookupKey(call.tenant,call.agent);
  if(!key)throw Error('unknown agent');
  const publicKey=createPublicKey(key);
  if(publicKey.asymmetricKeyType!=='ed25519')throw Error('unsupported key algorithm');
  if(!verify(null,signed,publicKey,sig))throw Error('signature rejected');
  replayGuard.consume({tenant:call.tenant,nonce:call.nonce,expiresAt:call.expiresAt});
  return Object.freeze({authorized:true,tenant:call.tenant,agent:call.agent});
}
module.exports={bytesForCall,authorizeCall};
