'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {generateKeyPairSync,sign,createHash}=require('node:crypto');
const {BoundedReplayGuard}=require('./bounded_replay_guard.cjs');
const {authorizeCall,bytesForCall}=require('./agent_call_auth.cjs');
const now=1700000000000;
const {privateKey,publicKey}=generateKeyPairSync('ed25519');
const {publicKey:other}=generateKeyPairSync('ed25519');
const guard=()=>new BoundedReplayGuard({clock:()=>now});
const body='{"job":"demo"}';
const call=()=>({tenant:'t1',agent:'a1',method:'POST',path:'/agent/run',nonce:'a'.repeat(32),expiresAt:now+30000,bodyHash:createHash('sha256').update(body).digest('hex')});
const sig=c=>sign(null,bytesForCall(c),privateKey).toString('base64url');
const opts=(c,g=guard())=>({call:c,body,signature:sig(c),lookupKey:()=>publicKey,replayGuard:g});
test('accepts valid signed call',()=>assert.equal(authorizeCall(opts(call())).authorized,true));
test('rejects replay',()=>{const g=guard(),c=call();authorizeCall(opts(c,g));assert.throws(()=>authorizeCall(opts(c,g)),/replay/)});
test('rejects body tampering',()=>assert.throws(()=>authorizeCall({...opts(call()),body:'tampered'}),/body mismatch/));
test('rejects route tampering',()=>{const c=call(),o=opts(c);assert.throws(()=>authorizeCall({...o,call:{...c,path:'/agent/admin'}}),/signature rejected/)});
test('rejects unknown or wrong tenant key',()=>assert.throws(()=>authorizeCall({...opts(call()),lookupKey:()=>other}),/signature rejected/));
test('bad signature does not consume nonce',()=>{const g=guard(),c=call();assert.throws(()=>authorizeCall({...opts(c,g),signature:sign(null,Buffer.from('other'),privateKey).toString('base64url')}),/signature rejected/);assert.equal(authorizeCall(opts(c,g)).authorized,true)});
test('rejects invalid routes',()=>assert.throws(()=>bytesForCall({...call(),path:'/agent/../admin'}),/route/));
test('rejects expired calls',()=>assert.throws(()=>authorizeCall(opts({...call(),expiresAt:now-1})),/expiry/));

test('rejects unsigned privilege and routing extensions',()=>{for(const extra of [{role:'admin'},{tenantOverride:'t2'},{destination:'https://evil.invalid'}]){const c={...call(),...extra};assert.throws(()=>authorizeCall({...opts(call()),call:c}),/unsigned call field/);}});
test('rejects missing signed envelope field',()=>{const c=call();delete c.agent;assert.throws(()=>bytesForCall(c),/unsigned call field/);});

test('rejects inherited privilege fields',()=>{const c=Object.assign(Object.create({role:'admin'}),call());assert.throws(()=>bytesForCall(c),/invalid call prototype/);});
test('rejects accessor side effects',()=>{const c=call();Object.defineProperty(c,'tenant',{enumerable:true,get(){throw Error('getter executed')}});assert.throws(()=>bytesForCall(c),/unsafe call property/);});
test('rejects non-enumerable and symbol extensions',()=>{const c=call();Object.defineProperty(c,'role',{value:'admin',enumerable:false});assert.throws(()=>bytesForCall(c),/unsafe call property/);const d=call();d[Symbol('role')]='admin';assert.throws(()=>bytesForCall(d),/unsafe call property/);});
