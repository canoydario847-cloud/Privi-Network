"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const os=require("node:os");
const path=require("node:path");
const crypto=require("node:crypto");
const {
  verifyCeremony,message,fileHash,FORMAT,ROSTER_FORMAT
}=require("./verify_operator_release.cjs");

// All inputs and keys in this file are synthetically generated, valueless
// test fixtures. Never use a fixture as real operator acceptance evidence.
function fixture(n=4) {
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),"privi-unsigned-release-test-"));
  const genesisPath=path.join(dir,"genesis.json"),binaryPath=path.join(dir,"candidate.bin");
  const cosmosId="privi-test-fixture-1";
  fs.writeFileSync(genesisPath,JSON.stringify({chain_id:cosmosId,app_state:{}}));
  fs.writeFileSync(binaryPath,Buffer.from("PRIVI UNSIGNED BUILD-ONLY TEST BYTES\n"));
  const keys=Array.from({length:n},()=>crypto.generateKeyPairSync("ed25519"));
  const operators=keys.map((pair,i)=>({
    operator_id:"ORG_"+i,
    fault_domain:"separate"+i+".test",
    public_key_spki_base64:pair.publicKey.export({format:"der",type:"spki"}).toString("base64")
  }));
  const trustRoster={format:ROSTER_FORMAT,operators};
  const release={
    cosmos_chain_id:cosmosId,evm_chain_id:424242,
    base_denom:"aprvi",max_supply_whole_prvi:"1000000000",
    consensus_protocol:"Point of Position",
    genesis_sha256:fileHash(genesisPath),binary_sha256:fileHash(binaryPath),
    source_commit:"a".repeat(40),planned_genesis_utc:"2030-01-02T03:04:05Z"
  };
  const manifest={format:FORMAT,release,signatures:[]};
  function sign() {
    manifest.signatures=operators.map((op,i)=>({
      operator_id:op.operator_id,
      signature_base64:crypto.sign(null,message(release,op),keys[i].privateKey)
        .toString("base64")
    }));
  }
  sign();
  return {
    dir,genesisPath,binaryPath,keys,operators,trustRoster,manifest,sign,
    verify:()=>verifyCeremony({manifest,trustRoster,genesisPath,binaryPath}),
    cleanup:()=>fs.rmSync(dir,{recursive:true,force:true})
  };
}
function caseWithFixture(title,work) {
  test(title,()=>{
    const f=fixture();
    try {work(f);} finally {f.cleanup();}
  });
}
caseWithFixture("4 actual operator keys sign same genesis, binary and commit without authorizing launch",f=>{
  const result=f.verify();
  assert.equal(result.verified_operator_signatures,4);
  assert.equal(result.production_release_authorized,false);
  assert.equal(result.financial_mainnet_activated,false);
  assert.equal(result.genesis_sha256,f.manifest.release.genesis_sha256);
  assert.equal(result.binary_sha256,f.manifest.release.binary_sha256);
});
caseWithFixture("reject substituted genesis bytes even with four valid signatures",f=>{
  fs.writeFileSync(f.genesisPath,JSON.stringify({chain_id:"privi-rogue-1"}));
  assert.throws(()=>f.verify(),/Genesis bytes/);
});
caseWithFixture("reject substituted node binary",f=>{
  fs.appendFileSync(f.binaryPath,"changed");
  assert.throws(()=>f.verify(),/Node binary bytes/);
});
caseWithFixture("reject source commit tampering",f=>{
  f.manifest.release.source_commit="b".repeat(40);
  assert.throws(()=>f.verify(),/Invalid or replayed operator release signature/);
});
caseWithFixture("reject chain ID replay",f=>{
  f.manifest.release.cosmos_chain_id="privi-different-2";
  assert.throws(()=>f.verify(),/genesis and Cosmos chain IDs disagree/);
});
caseWithFixture("reject alteration of planned genesis UTC timestamp",f=>{
  f.manifest.release.planned_genesis_utc="2030-01-03T03:04:05Z";
  assert.throws(()=>f.verify(),/Invalid or replayed operator release signature/);
});
caseWithFixture("reject forged release signature",f=>{
  const s=f.manifest.signatures[0];
  s.signature_base64=crypto.sign(null,Buffer.from("NOT PRVI RELEASE"),
                                 f.keys[0].privateKey).toString("base64");
  assert.throws(()=>f.verify(),/Invalid or replayed operator release signature/);
});
caseWithFixture("reject fewer than four independent approved signatures",f=>{
  f.manifest.signatures.pop();
  assert.throws(()=>f.verify(),/Exactly one signature/);
});
caseWithFixture("reject repeated signature from same operator instead of quorum",f=>{
  f.manifest.signatures[3]={...f.manifest.signatures[0]};
  assert.throws(()=>f.verify(),/Unapproved or duplicate/);
});
caseWithFixture("reject replacing an operator public key in the signed roster",f=>{
  const rogue=crypto.generateKeyPairSync("ed25519");
  f.trustRoster.operators[2].public_key_spki_base64=
    rogue.publicKey.export({format:"der",type:"spki"}).toString("base64");
  assert.throws(()=>f.verify(),/Invalid or replayed operator release signature/);
});
caseWithFixture("reject a reused signer key despite different operator names",f=>{
  f.trustRoster.operators[1].public_key_spki_base64=
    f.trustRoster.operators[0].public_key_spki_base64;
  assert.throws(()=>f.verify(),/Duplicate operator public key/);
});
caseWithFixture("reject same self-reported fault domain",f=>{
  f.trustRoster.operators[1].fault_domain=f.trustRoster.operators[0].fault_domain;
  assert.throws(()=>f.verify(),/Duplicate claimed fault domain/);
});
caseWithFixture("reject dev EVM chain IDs even if every test key signs them",f=>{
  for(const id of [1,56,97,1337,31337,4221,262144]) {
    f.manifest.release.evm_chain_id=id;
    assert.throws(()=>f.sign(),/Unapproved public\/developer EVM chain identity/);
  }
});
caseWithFixture("reject PoS/PoSA masquerading as PoP even with valid keys",f=>{
  for(const value of ["Proof of Stake","PoSA","Stake Weighted PoP"]) {
    f.manifest.release.consensus_protocol=value;
    assert.throws(()=>f.sign(),/Native Point of Position required/);
  }
});
caseWithFixture("reject a release authorization flag inserted into signed evidence",f=>{
  f.manifest.production_release_authorized=true;
  assert.throws(()=>f.verify(),/missing or unknown keys/);
});
caseWithFixture("reject a different genesis chain identity despite newly signed evidence",f=>{
  f.manifest.release.cosmos_chain_id="privi-other-2";
  f.sign();
  assert.throws(()=>f.verify(),/Signed genesis and Cosmos chain IDs disagree/);
});
caseWithFixture("reject symlinked local binary inputs even when hashes match",f=>{
  const binaryReal=path.join(f.dir,"real.bin");
  fs.renameSync(f.binaryPath,binaryReal);
  fs.symlinkSync(binaryReal,f.binaryPath);
  assert.throws(()=>f.verify(),/regular non-symlink file/);
});
caseWithFixture("reject malformed UTC time, supply and native denom",f=>{
  f.manifest.release.planned_genesis_utc="2030-01-02T03:04:05+01:00";
  assert.throws(()=>f.verify(),/Canonical UTC/);
  f.manifest.release.planned_genesis_utc="2030-01-02T03:04:05Z";
  f.manifest.release.max_supply_whole_prvi="1000000001";
  assert.throws(()=>f.verify(),/Immutable maximum supply/);
  f.manifest.release.max_supply_whole_prvi="1000000000";
  f.manifest.release.base_denom="atest";
  assert.throws(()=>f.verify(),/Native denomination/);
});
test("five independently signed test operators also verify, without PoP mainnet clearance",()=>{
  const f=fixture(5);
  try {
    const result=f.verify();
    assert.equal(result.verified_operator_signatures,5);
    assert.equal(result.production_release_authorized,false);
  } finally {f.cleanup();}
});
