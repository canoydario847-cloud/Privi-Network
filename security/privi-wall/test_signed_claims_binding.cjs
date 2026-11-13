'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {createHash}=require('node:crypto');
const {admitBoundAgentCall:admit}=require('./signed_claims_binding.cjs');
const payload=Buffer.from('{"operation":"read"}');
const envelope={tenant:'t1',agent:'a1',action:'run',nonce:'a'.repeat(32),expiresAt:2000};
const hash=p=>createHash('sha256').update(p).digest('hex');
function fixture(patch={}){
 const events=[],seen=new Set();
 return {events,args:{sessionTenant:'t1',envelope:{...envelope},payload:Buffer.from(payload),
 verifySignedClaims:async(c,p)=>{events.push('verify');return {verified:true,claims:{...c,payloadSha256:hash(p)}};},
 authorizeAction:async()=>{events.push('authorize');return true;},
 reserve:async key=>{events.push('reserve');if(seen.has(key))return false;seen.add(key);return true;},
 clock:()=>1000,...patch}};
}
test('valid full signed claims admit once and deny replay',async()=>{
 const f=fixture();assert.equal(await admit(f.args),true);assert.deepEqual(f.events,['verify','authorize','reserve']);
 assert.equal(await admit(f.args),false);
});
test('signature failure denies before authorization',async()=>{
 const f=fixture({verifySignedClaims:async()=>({verified:false,claims:{}})});
 assert.equal(await admit(f.args),false);assert.deepEqual(f.events,[]);
});
test('missing covered field fails closed',async()=>{
 const f=fixture({verifySignedClaims:async(c,p)=>{delete c.action;return {verified:true,claims:{tenant:'t1',agent:'a1',nonce:envelope.nonce,expiresAt:2000,payloadSha256:hash(p)}};}});
 assert.equal(await admit(f.args),false);assert.deepEqual(f.events,[]);
});
test('signed tenant or action mismatch fails closed',async()=>{
 for(const field of ['tenant','action']){const f=fixture({verifySignedClaims:async(c,p)=>({verified:true,claims:{...c,[field]:'different',payloadSha256:hash(p)}})});assert.equal(await admit(f.args),false);}
});
test('modified payload is rejected',async()=>{
 const f=fixture({verifySignedClaims:async c=>({verified:true,claims:{...c,payloadSha256:hash(Buffer.from('other'))}})});
 assert.equal(await admit(f.args),false);assert.deepEqual(f.events,[]);
});
test('invalid digest encoding is rejected',async()=>{
 const f=fixture({verifySignedClaims:async c=>({verified:true,claims:{...c,payloadSha256:'not-a-digest'}})});
 assert.equal(await admit(f.args),false);
});
test('verifier error fails closed',async()=>{
 const f=fixture({verifySignedClaims:async()=>{throw Error('unavailable')}});
 assert.equal(await admit(f.args),false);
});
test('oversized payload rejected before verifier',async()=>{
 const f=fixture({payload:Buffer.alloc(65537)});
 assert.equal(await admit(f.args),false);assert.deepEqual(f.events,[]);
});
test('input mutation during async verification cannot alter admitted claims',async()=>{
 const f=fixture({verifySignedClaims:async(c,p)=>{f.args.envelope.action='delete';f.args.payload.fill(0);return {verified:true,claims:{...c,payloadSha256:hash(p)}};}});
 assert.equal(await admit(f.args),true);
});
