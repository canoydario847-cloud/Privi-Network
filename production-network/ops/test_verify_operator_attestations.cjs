"use strict";
const assert=require("node:assert/strict");
const test=require("node:test");
const crypto=require("node:crypto");
const verifier=require("./verify_operator_attestations.cjs");

function data() {
  const m={
    network_type:"public_testnet",asset_symbol:"TEST",valueless_asset:true,
    financial_mainnet_live:false,bnb_priv_separate:true,
    cosmos_chain_id:"privi-testnet-1",evm_chain_id:951723,
    genesis_sha256:"a".repeat(64),binary_sha256:"b".repeat(64),
    operators:[]
  };
  for(let i=0;i<4;i++){
    const keys=crypto.generateKeyPairSync("ed25519");
    const o={
      operator_id:"operator-"+i,consensus_address:(i+1).toString(16).padStart(40,"0"),
      fault_domain:"domain-"+i,operator_controls_keys:true,
      independence_attestation_url:"https://operator"+i+".example.org/review",
      attested_utc:"2026-10-17T19:00:00Z",
      attestation_public_key_pem:keys.publicKey.export({type:"spki",format:"pem"})
    };
    o.attestation_signature_base64=crypto.sign(null,verifier.payload(m,o),keys.privateKey).toString("base64");
    m.operators.push(o);
  }
  return m;
}
test("accepts four separately signed, unique operator claims",()=>{
  const res=verifier.verify(data());
  assert.equal(res.verified_attestation_count,4);
  assert.equal(res.status,"VALID_OFFCHAIN_ATTESTATIONS_ONLY");
});
test("rejects tampering with candidate genesis hash",()=>{
  const m=data(); m.genesis_sha256="c".repeat(64);
  assert.throws(()=>verifier.verify(m),/invalid operator attestation signature/);
});
test("rejects changed Cosmos/EVM chain IDs",()=>{
  const m=data();m.evm_chain_id=951724;
  assert.throws(()=>verifier.verify(m),/invalid operator attestation signature/);
});
test("rejects altered consensus address",()=>{
  const m=data();m.operators[2].consensus_address="e".repeat(40);
  assert.throws(()=>verifier.verify(m),/invalid operator attestation signature/);
});
test("rejects duplicate operator keys, even if fields differ",()=>{
  const m=data();m.operators[1].attestation_public_key_pem=m.operators[0].attestation_public_key_pem;
  assert.throws(()=>verifier.verify(m),/invalid operator attestation signature/);
});
test("rejects repeated voting address after re-signing",()=>{
  const m=data();
  const priv=crypto.generateKeyPairSync("ed25519");
  m.operators[1].consensus_address=m.operators[0].consensus_address;
  m.operators[1].attestation_public_key_pem=priv.publicKey.export({type:"spki",format:"pem"});
  m.operators[1].attestation_signature_base64=crypto.sign(null,
    verifier.payload(m,m.operators[1]),priv.privateKey).toString("base64");
  assert.throws(()=>verifier.verify(m),/duplicate consensus address/);
});
test("rejects attestation using dev/demo EVM ID",()=>{
  const m=data();m.evm_chain_id=262144;
  assert.throws(()=>verifier.verify(m),/non-demo EVM ID/);
});
test("rejects false operator key control",()=>{
  const m=data();m.operators[0].operator_controls_keys=false;
  assert.throws(()=>verifier.verify(m),/key control/);
});
test("rejects non-Ed25519 off-chain attestation key",()=>{
  const m=data(),key=crypto.generateKeyPairSync("rsa",{modulusLength:2048});
  m.operators[0].attestation_public_key_pem=key.publicKey.export({type:"spki",format:"pem"});
  assert.throws(()=>verifier.verify(m),/Ed25519/);
});
test("rejects plain HTTP evidence link",()=>{
  const m=data();m.operators[3].independence_attestation_url="http://example.org";
  assert.throws(()=>verifier.verify(m),/evidence URL/);
});
test("only off-chain fields, never private signing keys, exist in fixtures",()=>{
  const m=data();
  assert.equal("private_key" in m.operators[0],false);
});
test("rejects secret fields in public manifest",()=>{
  const m=data();m.operators[0].attestation_private_key_pem="never-commit-private-key";
  assert.throws(()=>verifier.verify(m),/manifest may not contain secrets/);
});
