'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {enforceActiveSession} = require('./active_session_guard.cjs');
const {authorizeWebSocketUpgrade} = require('./websocket_upgrade_gate.cjs');
const base = {agentId:'agent-1', tenant:'tenant-1', audience:'privi-agent', expiresAt:2000};
function socket(){const closed=[];return {closed,close:(...args)=>closed.push(args)};}
test('valid active session is allowed without closing',()=>{const s=socket();assert.equal(enforceActiveSession({socket:s,context:base,now:1999,isRevoked:()=>false}),true);assert.equal(s.closed.length,0);});
test('expired session closes with policy violation',()=>{const s=socket();assert.equal(enforceActiveSession({socket:s,context:base,now:2000}),false);assert.equal(s.closed[0][0],1008);});
test('revoked session closes immediately',()=>{const s=socket();assert.equal(enforceActiveSession({socket:s,context:base,now:1000,isRevoked:()=>true}),false);assert.equal(s.closed.length,1);});
test('revocation backend failure denies access',()=>{const s=socket();assert.equal(enforceActiveSession({socket:s,context:base,now:1000,isRevoked:()=>{throw Error('offline');}}),false);assert.equal(s.closed.length,1);});
test('missing context or invalid timestamp fails closed',()=>{for(const context of [null,{}, {...base,expiresAt:'2000'}, {...base,tenant:''}]){const s=socket();assert.equal(enforceActiveSession({socket:s,context,now:1000}),false);assert.equal(s.closed.length,1);}});
test('upgrade context retains verified expiration',async()=>{const expiry=Date.now()+60000;const p=await authorizeWebSocketUpgrade({request:{headers:{origin:'https://app.privi.example'}},allowedOrigins:['https://app.privi.example'],expectedTenant:'tenant-1',expectedAudience:'privi-agent',authenticate:async()=>({authenticated:true,...base,expiresAt:expiry})});assert.equal(p.expiresAt,expiry);assert.equal(Object.isFrozen(p),true);});

test('missing revocation authority is rejected, not treated as not revoked',()=>{const s=socket();assert.equal(enforceActiveSession({socket:s,context:base,now:1000}),false);assert.deepEqual(s.closed[0],[1008,'Session unauthorized']);});
test('revocation callback must explicitly return false',()=>{for(const result of [undefined,null,0,'false']){const s=socket();assert.equal(enforceActiveSession({socket:s,context:base,now:1000,isRevoked:()=>result}),false);assert.equal(s.closed[0][0],1008);}});

test('missing revocation authority denies even when socket close throws',()=>{const s={close(){throw Error('socket closed');}};assert.equal(enforceActiveSession({socket:s,context:base,now:1000}),false);});
