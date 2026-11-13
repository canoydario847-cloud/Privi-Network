'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {createHash}=require('node:crypto');
const {auditPinnedSupplyManifest}=require('./audit_pinned_supply_manifest.cjs');
const genesis={app_state:{bank:{balances:[{address:'addr1',coins:[{denom:'aprvi',amount:'100'}]}],supply:[{denom:'aprvi',amount:'100'}]}}};
const raw=Buffer.from(JSON.stringify({denom:'aprvi',expectedSupply:'100',maxSupply:'1000'}));
const digest=b=>createHash('sha256').update(b).digest('hex');
test('accepts matching independently pinned bytes and reconciled amounts',()=>{
 assert.deepEqual(auditPinnedSupplyManifest(genesis,raw,digest(raw)),[]);
});
test('rejects absent or malformed approval digest',()=>{
 for(const bad of [undefined,'','a'.repeat(64),'G'.repeat(64)])
  assert.ok(auditPinnedSupplyManifest(genesis,raw,bad).length);
});
test('rejects tampered manifest even when JSON remains valid',()=>{
 const tampered=Buffer.from(raw.toString().replace('1000','2000'));
 assert.match(auditPinnedSupplyManifest(genesis,tampered,digest(raw))[0],/differs/);
});
test('rejects malformed JSON despite matching digest',()=>{
 const bad=Buffer.from('{bad');
 assert.match(auditPinnedSupplyManifest(genesis,bad,digest(bad))[0],/JSON/);
});
test('rejects bank supply mismatch even when digest matches',()=>{
 const g=structuredClone(genesis);g.app_state.bank.supply[0].amount='99';
 assert.ok(auditPinnedSupplyManifest(g,raw,digest(raw)).length);
});
test('rejects oversized or non-byte manifest inputs',()=>{
 assert.ok(auditPinnedSupplyManifest(genesis,'{}',digest(raw)).length);
 assert.ok(auditPinnedSupplyManifest(genesis,Buffer.alloc(1024*1024+1),digest(raw)).length);
});
