import test from 'node:test';
import assert from 'node:assert/strict';
import {JOSE_POWERS,recognizePower,runJosePower,listJosePowers} from '../src/jose-powers.js';

const examples=[
 ['privacy','/privacy Email alice@example.com and call (313) 555-0192','[EMAIL]'],
 ['secrets','/secrets api_key=veryLongSecretTokenValue123','Possible exposures'],
 ['url-risk','/url-risk http://bit.ly/something','URL shortener'],
 ['claims','/claims We guarantee 100% savings in 2026.','Source: no source'],
 ['fingerprint','/fingerprint hello world','SHA-256: '],
 ['verify-fingerprint','/verify-fingerprint {"content":"abc","sha256":"ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"}','MATCH'],
 ['json-lint','/json-lint {"a":1,"b":[1,2]}','VALID JSON'],
 ['csv-stats','/csv-stats name,value\nAlpha,1\nBeta,2','Rows: 2; columns: 2'],
 ['compare','/compare one\n--- VS ---\ntwo','1 differing line'],
 ['invoice-check','/invoice-check {"items":[{"qty":2,"unitPrice":15}],"taxRatePercent":6,"claimedTotal":31.8}','MATCH'],
 ['runway','/runway {"cash":1200,"monthlyBurn":600,"monthlyRevenue":200}','3.00 months'],
 ['break-even','/break-even {"fixedCost":1000,"price":35,"variableCost":5}','Required sales: 34'],
 ['unit-economics','/unit-economics {"revenue":1000,"variableCost":300,"customers":20}','35.00'],
 ['model-cost','/model-cost {"inputTokens":10000,"outputTokens":4000,"inputPerMillion":1,"outputPerMillion":4}','$0.0260'],
 ['gas-cost','/gas-cost {"gasUnits":100000,"gwei":2,"nativePriceUsd":2000}','$0.40'],
 ['token-units','/token-units {"tokens":"1.5","decimals":18}','1500000000000000000'],
 ['chain-guard','/chain-guard {"chainId":772626}','Privi single-validator devnet'],
 ['rpc-guard','/rpc-guard {"method":"eth_sendTransaction","params":[]}','NOT ALLOWLISTED'],
 ['critical-path','/critical-path {"tasks":[{"id":"A","days":2},{"id":"B","days":3,"dependsOn":["A"]}]}','5 working-day units'],
 ['launch-risk','/launch-risk Launch a production contract next week with no testing.','Potential omissions to review']
];

test('20 registered power identities are unique, with usage examples',()=>{
 assert.equal(JOSE_POWERS.length,20);
 assert.equal(new Set(JOSE_POWERS.map(p=>p.id)).size,20);
 assert.equal(examples.length,20);
 for(const [id] of examples)assert.ok(JOSE_POWERS.some(p=>p.id===id),'missing '+id);
 assert.match(listJosePowers(),/20 verified local tools/);
});
for(const [id,ask,expected] of examples){
 test('working power: '+id,async()=>{
  const result=await runJosePower(ask);
  assert.equal(result.power,id);
  assert.ok(result.answer.includes(expected),JSON.stringify(result.answer));
  assert.ok(!result.answer.includes('needs valid input'),result.answer);
 });
}
test('plain English explicit invocation and discovery work without new pages',async()=>{
 assert.equal(recognizePower('Run chain-guard: {"chainId":772626}').id,'chain-guard');
 assert.equal(recognizePower('What are your 20 features?').id,'powers');
 assert.equal((await runJosePower('/powers')).power,'powers');
 assert.equal(recognizePower('What is the capital of Canada?'),null);
 assert.equal(await runJosePower('What is the capital of Canada?'),null);
});
test('sensitive scans never reflect raw detected credentials',async()=>{
 const secret='sk-proj-WwXxYyZz0123456789abcdef';
 const alert=await runJosePower('/secrets '+secret);
 assert.match(alert.answer,/Possible exposures/);
 assert.ok(!alert.answer.includes(secret));
 const hide=await runJosePower('/privacy secret: '+secret);
 assert.ok(!hide.answer.includes(secret));
});
test('proof recheck detects altered content',async()=>{
 const bad=await runJosePower('/verify-fingerprint {"content":"xyz","sha256":"ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"}');
 assert.match(bad.answer,/MISMATCH/);
});
test('safety guards reject unknown methods and unsafe token precision',async()=>{
 const rpc=await runJosePower('/rpc-guard {"method":"eth_sendRawTransaction","params":[]}');
 assert.match(rpc.answer,/NOT ALLOWLISTED/);
 const units=await runJosePower('/token-units {"tokens":"1.123","decimals":2}');
 assert.match(units.answer,/needs valid input/);
 const plan=await runJosePower('/critical-path {"tasks":[{"id":"A","days":1,"dependsOn":["B"]},{"id":"B","days":2,"dependsOn":["A"]}]}');
 assert.match(plan.answer,/Dependency cycle/);
});
test('invalid cost inputs are rejected without spurious arithmetic',async()=>{
 const r=await runJosePower('/runway {"cash":-10,"monthlyBurn":50}');
 assert.match(r.answer,/needs valid input/);
});
