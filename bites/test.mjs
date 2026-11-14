import test from 'node:test'; import assert from 'node:assert/strict'; import {issue,verify,revoke} from './server.mjs';
test('short-lived bites are scoped and revocable',()=>{
 const out=issue({audience:'app',subject:'agent',scopes:['read'],ttl_seconds:60});
 assert.equal(verify({bite:out.bite,audience:'app',scope:'read'}).valid,true);
 assert.equal(verify({bite:out.bite,audience:'other',scope:'read'}).valid,false);
 assert.equal(verify({bite:out.bite,audience:'app',scope:'write'}).valid,false);
 assert.equal(verify({bite:out.bite+'x',audience:'app',scope:'read'}).valid,false);
 revoke({bite:out.bite});
 assert.equal(verify({bite:out.bite,audience:'app',scope:'read'}).valid,false);
});
