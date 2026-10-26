"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const os=require("node:os");
const path=require("node:path");
const {spawnSync}=require("node:child_process");
const {makeDemo,verifyDemo,canonical}=require("./demo.cjs");

function clone(value){return JSON.parse(JSON.stringify(value));}
function modified(fn){
  const pair=makeDemo();
  const receipt=clone(pair.receipt);
  const trust=clone(pair.trust);
  fn(receipt,trust);
  return ()=>verifyDemo(receipt,trust);
}

test("two independently signed fictional records verify without network",()=>{
  const pair=makeDemo();
  const result=verifyDemo(pair.receipt,pair.trust);
  assert.equal(result.valid,true);
  assert.equal(result.synthetic_only,true);
  assert.equal(result.verified_signatures,2);
  assert.equal(result.execution_proven,false);
  assert.equal(result.chain_head,pair.receipt.events[1].entry_hash);
  assert.notEqual(pair.trust.trusted_signers.authorization_service.key_id,
                  pair.trust.trusted_signers.execution_reporter.key_id);
  const publicText=JSON.stringify(pair);
  assert.ok(publicText.includes("reference-only-not-human-verified"));
  assert.ok(publicText.includes("NOT proof that an actual authorized action occurred"));
  assert.ok(!publicText.includes("privateKey"));
});

test("changing approval ID, tenant, actor, policy or software version invalidates signature",()=>{
  for(const field of ["approval_id","tenant_id","actor_id","policy_id",
                      "policy_version","policy_sha256","software_version"]) {
    assert.throws(modified((r)=>{r.events[0][field]+="-tampered";}),
                  /mismatch|signature|binding/,field);
  }
});
test("reported execution outcome or synthetic acknowledgment cannot be rewritten",()=>{
  assert.throws(modified((r)=>{r.events[1].result="reported_failure";}),
                /unexpected event/);
  assert.throws(modified((r)=>{r.events[1].external_ack_id="ACK-SYNTHETIC-forged";}),
                /hash mismatch/);
});
test("missing, reordered, repeated or extra events are refused",()=>{
  assert.throws(modified((r)=>{r.events.pop();}),/exactly one/);
  assert.throws(modified((r)=>{r.events.reverse();}),/reordered/);
  assert.throws(modified((r)=>{r.events[1]=clone(r.events[0]);}),/reordered/);
  assert.throws(modified((r)=>{r.events.push(clone(r.events[1]));}),/exactly one/);
});
test("hash head mismatch and severed authorization linkage are rejected",()=>{
  assert.throws(modified((r)=>{r.head_hash="f".repeat(64);}),/chain head/);
  assert.throws(modified((r)=>{r.events[1].authorization_entry_hash="0".repeat(64);}),
                /hash mismatch/);
  assert.throws(modified((r)=>{r.events[1].previous_entry_hash="0".repeat(64);}),
                /hash mismatch/);
});
test("substituted test trust key cannot validate issuer signatures",()=>{
  const pair=makeDemo(), other=makeDemo();
  pair.trust.trusted_signers.execution_reporter=
    other.trust.trusted_signers.execution_reporter;
  assert.throws(()=>verifyDemo(pair.receipt,pair.trust),/signature/);
});
test("missing or same signer trust roots rejected",()=>{
  assert.throws(modified((r,t)=>{delete t.trusted_signers.authorization_service;}),
                /Missing independently pinned/);
  assert.throws(modified((r,t)=>{
    t.trusted_signers.execution_reporter=t.trusted_signers.authorization_service;
  }),/distinct test signers/);
});
test("test-only markers cannot be changed into production claims",()=>{
  assert.throws(modified((r)=>{r.synthetic_only=false;}),/synthetic/);
  assert.throws(modified((r)=>{r.trust_statement="Privi production verified execution";}),
                /caveat/);
  assert.throws(modified((r,t)=>{t.issuer="Privi production";}),/test trust roots/);
});
test("CLI makes and verifies only public test artifacts; fails closed on tampering",()=>{
  const root=fs.mkdtempSync(path.join(os.tmpdir(),"privi-raaa-poc-"));
  const output=path.join(root,"sample");
  try{
    const create=spawnSync(process.execPath,[path.join(__dirname,"demo.cjs"),"create",output],
                           {encoding:"utf8"});
    assert.equal(create.status,0,create.stderr);
    assert.deepEqual(fs.readdirSync(output).sort(),["receipt.json","trusted-keys.json"]);
    const receiptPath=path.join(output,"receipt.json");
    const trustedPath=path.join(output,"trusted-keys.json");
    const verify=()=>spawnSync(process.execPath,
      [path.join(__dirname,"demo.cjs"),"verify",receiptPath,trustedPath],{encoding:"utf8"});
    assert.equal(verify().status,0);
    assert.match(verify().stdout,/NOT PROVEN/);
    assert.notEqual(spawnSync(process.execPath,
      [path.join(__dirname,"demo.cjs"),"create",output],{encoding:"utf8"}).status,0,
      "No overwriting previously published test public-key bindings");
    const doc=JSON.parse(fs.readFileSync(receiptPath,"utf8"));
    doc.events[1].result="reported_failure";
    fs.writeFileSync(receiptPath,JSON.stringify(doc));
    assert.notEqual(verify().status,0,"Mutated action outcome must fail offline verification");
  }finally{fs.rmSync(root,{recursive:true,force:true});}
});
test("canonical JSON is independent of property insertion order",()=>{
  assert.equal(canonical({b:{z:1,a:2},a:true}),canonical({a:true,b:{a:2,z:1}}));
});
