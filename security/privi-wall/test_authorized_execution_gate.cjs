'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {createHash}=require('node:crypto');
const {executeAdmittedAgentCall:run}=require('./authorized_execution_gate.cjs');
const base={tenant:'tenant-A',agent:'agent-1',action:'read',nonce:'b'.repeat(32),expiresAt:2000};
function setup(overrides={}){
 const calls=[],seen=new Set();
 const args={sessionTenant:'tenant-A',envelope:{...base},payload:Buffer.from('original'),
 clock:()=>1000,
 verifySignedClaims:async(c,p)=>{calls.push('verify');return {verified:true,claims:{...c,payloadSha256:createHash('sha256').update(p).digest('hex')}};},
 authorizeAction:async()=>{calls.push('authorize');return true;},
 reserve:async key=>{calls.push('reserve');if(seen.has(key))return false;seen.add(key);return true;},
 execute:async(c,p)=>{calls.push('execute');return {action:c.action,payload:p.toString()};},
 ...overrides};
 return {args,calls};
}
test('executes exactly once only after verification, authorization, and replay reservation',async()=>{
 const f=setup();const first=await run(f.args);
 assert.equal(first.executed,true);assert.deepEqual(f.calls,['verify','authorize','reserve','execute']);
 assert.deepEqual(first.result,{action:'read',payload:'original'});
 const second=await run(f.args);assert.deepEqual(second,{admitted:false});
 assert.equal(f.calls.filter(x=>x==='execute').length,1);
});
test('invalid signature never reaches executor',async()=>{
 const f=setup({verifySignedClaims:async()=>({verified:false})});
 assert.deepEqual(await run(f.args),{admitted:false});assert.deepEqual(f.calls,[]);
});
test('cross-tenant session never reaches executor',async()=>{
 const f=setup({sessionTenant:'tenant-B'});
 assert.deepEqual(await run(f.args),{admitted:false});assert.ok(!f.calls.includes('execute'));
});
test('policy denial never reaches executor',async()=>{
 const f=setup({authorizeAction:async()=>false});
 assert.deepEqual(await run(f.args),{admitted:false});assert.ok(!f.calls.includes('execute'));
});
test('replay store failure never reaches executor',async()=>{
 const f=setup({reserve:async()=>{throw Error('offline')}});
 assert.deepEqual(await run(f.args),{admitted:false});assert.ok(!f.calls.includes('execute'));
});
test('caller mutation during asynchronous verification does not change executed payload or action',async()=>{
 const f=setup();
 f.args.verifySignedClaims=async(c,p)=>{
   f.args.envelope.action='delete';f.args.payload.fill(0);
   return {verified:true,claims:{...c,payloadSha256:createHash('sha256').update(p).digest('hex')}};
 };
 const out=await run(f.args);
 assert.equal(out.executed,true);assert.deepEqual(out.result,{action:'read',payload:'original'});
});
test('executor errors are not reported as successful execution',async()=>{
 const f=setup({execute:async()=>{throw Error('failed')}});
 assert.deepEqual(await run(f.args),{admitted:true,executed:false});
});
test('missing executor and oversized payload fail before admission',async()=>{
 const f=setup();assert.deepEqual(await run({...f.args,execute:null}),{admitted:false});
 assert.deepEqual(await run({...f.args,payload:Buffer.alloc(65537)}),{admitted:false});
 assert.deepEqual(f.calls,[]);
});

test('expiry reached after replay admission prevents execution',async()=>{
 let now=1000;const f=setup({clock:()=>now,reserve:async()=>{now=2000;return true;}});
 assert.deepEqual(await run(f.args),{admitted:false});
 assert.ok(!f.calls.includes('execute'));
});
test('invalid post-admission clock prevents execution',async()=>{
 let reads=0;const f=setup({clock:()=>++reads>=3?NaN:1000});
 assert.deepEqual(await run(f.args),{admitted:false});
 assert.ok(!f.calls.includes('execute'));
});
test('clock errors after admission prevent execution',async()=>{
 let reads=0;const f=setup({clock:()=>{if(++reads>=3)throw Error('clock unavailable');return 1000;}});
 assert.deepEqual(await run(f.args),{admitted:false});
 assert.ok(!f.calls.includes('execute'));
});
