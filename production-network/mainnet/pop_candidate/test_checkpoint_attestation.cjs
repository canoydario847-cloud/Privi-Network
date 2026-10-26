"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const crypto=require("node:crypto");
const {
  hash,positionStamp,parseRegistry,signedMessage,proposer,
  proposalFields,voteFields,TRUSTED_MODE
}=require("./engine.cjs");
const {
  SCHEMA,MODE,SIGNING_TAG,checkpointFields,verifyResearchCheckpoint,
  verifyAttestedCandidateAncestry
}=require("./checkpoint_attestation.cjs");

function newKey() {
  const pair=crypto.generateKeyPairSync("ed25519");
  const der=pair.publicKey.export({type:"spki",format:"der"});
  return {id:hash(der),publicKey:der.toString("base64"),privateKey:pair.privateKey};
}
function sign(key,tag,fields){
  return crypto.sign(null,signedMessage(tag,fields),key.privateKey).toString("base64");
}
function fixture(count=4) {
  const governance=newKey(),keys=Array.from({length:count},newKey);
  const chainId="privi-pop-research-signed-checkpoint",genesisHash="0x"+"a".repeat(64);
  const epoch=2;
  const registry={
    chainId,genesisHash,epoch,mode:TRUSTED_MODE,
    validators:keys.map((key,index)=>{
      const operatorId="OP_"+index,faultDomain="host"+index+".independent.test";
      const companyId="ORG_"+index,positionSequence=index+1;
      const anchorBlockHash=hash(Buffer.from("synthetic-pop-anchor-"+index));
      const positionHash=hash(Buffer.from(positionStamp(companyId,positionSequence)));
      return {
        id:key.id,keySpkiBase64:key.publicKey,operatorId,faultDomain,
        companyId,positionSequence,anchorBlockHash,positionHash,
        admissionSignature:sign(governance,"admit",[
          chainId,genesisHash,epoch,operatorId,faultDomain,companyId,
          positionSequence,key.id,anchorBlockHash
        ])
      };
    })
  };
  const committee=parseRegistry(registry,governance.publicKey);
  const signerKeys=new Map(keys.map(k=>[k.id,k]));
  const checkpoint={
    schema:SCHEMA,mode:MODE,chainId,genesisHash,epoch,
    height:30,blockHash:"0x"+"e".repeat(64),
    governanceKeyId:governance.id
  };
  function resign(subject=checkpoint,key=governance) {
    const unsigned={...subject};
    delete unsigned.signatureB64;
    return {...unsigned,signatureB64:sign(key,SIGNING_TAG,checkpointFields(unsigned))};
  }
  function certificate(height,previousBlockHash,blockHash,round=0,limit=committee.quorum){
    const proposerId=proposer(committee,height,round);
    const fields=proposalFields(committee,height,round,
                                 previousBlockHash,blockHash,proposerId);
    const proposal={height,round,previousBlockHash,blockHash,proposerId,
                    signature:sign(signerKeys.get(proposerId),"propose",fields)};
    const votes=committee.validators.slice(0,limit).map(v=>({
      validatorId:v.id,signature:sign(signerKeys.get(v.id),"commit",
                                    voteFields(fields,v.id))
    }));
    return {proposal,votes};
  }
  function batch() {
    const head="0x"+"f".repeat(64),tail="0x"+"d".repeat(64);
    return [
      certificate(31,checkpoint.blockHash,head),
      certificate(32,head,tail,1)
    ];
  }
  return {governance,committee,checkpoint:resign(),resign,certificate,batch};
}
test("signed research checkpoint from an independently pinned governance root authenticates the assertion",()=>{
  const f=fixture(),check=verifyResearchCheckpoint(f.committee,f.checkpoint,
                                                   f.governance.publicKey);
  assert.equal(check.checkpointIssuerSignatureVerified,true);
  assert.equal(check.checkpointFinalityVerified,false);
  assert.equal(check.productionConsensus,false);
  assert.equal(check.researchOnly,true);
  assert.equal(check.governanceKeyId,f.committee.governanceKeyId);
  assert.equal(check.blockHash,f.checkpoint.blockHash);
  assert.equal(Object.isFrozen(check),true);
});

test("two signed contiguous candidate certificates also require the issuer attestation",()=>{
  const f=fixture(),result=verifyAttestedCandidateAncestry(
    f.committee,f.checkpoint,f.governance.publicKey,f.batch()
  );
  assert.equal(result.verifiedCandidateCertificates,2);
  assert.equal(result.checkedSignatures,6);
  assert.equal(result.checkpointIssuerSignatureVerified,true);
  assert.equal(result.verifiesCheckpointAuthenticity,false);
  assert.equal(result.checkpointFinalityVerified,false);
  assert.equal(result.finalized,false);
  assert.equal(result.productionConsensus,false);
  assert.equal(result.endingHeight,32);
  assert.equal(Object.isFrozen(result),true);
});

test("five-of-seven research signature quorum also accepts a valid synthetic checkpoint",()=>{
  const f=fixture(7),result=verifyAttestedCandidateAncestry(
    f.committee,f.checkpoint,f.governance.publicKey,f.batch());
  assert.equal(result.checkedSignatures,10);
  assert.equal(result.finalized,false);
});

test("wrong, missing or substituted independently pinned trusted governance key is refused",()=>{
  const f=fixture(),rogue=newKey();
  for(const untrustedKey of [null,undefined,rogue.publicKey,"not-base64"]){
    assert.throws(()=>verifyResearchCheckpoint(f.committee,f.checkpoint,untrustedKey));
  }
  const replacement=f.resign(f.checkpoint,rogue);
  assert.throws(()=>verifyResearchCheckpoint(f.committee,replacement,f.governance.publicKey),
                /issuer signature invalid/);
  assert.throws(()=>verifyResearchCheckpoint(f.committee,f.checkpoint,rogue.publicKey),
                /not the independently trusted/);
});

test("re-signing a checkpoint with valid governance key cannot bypass another epoch, chain or genesis",()=>{
  const f=fixture();
  const overrides=[
    {epoch:f.committee.epoch+1},
    {chainId:"privi-pop-research-other"},
    {genesisHash:"0x"+"c".repeat(64)}
  ];
  for(const fields of overrides){
    const checkpoint=f.resign({...f.checkpoint,...fields});
    assert.throws(()=>verifyResearchCheckpoint(f.committee,checkpoint,
                  f.governance.publicKey),/belongs to another chain/);
  }
});

test("tampered height, block hash, signer identity or research mode invalidates checkpoint",()=>{
  const f=fixture();
  const changed=[
    {...f.checkpoint,height:29},
    {...f.checkpoint,blockHash:"0x"+"b".repeat(64)},
    {...f.checkpoint,governanceKeyId:"0x"+"f".repeat(64)},
    {...f.checkpoint,mode:"production-mainnet"},
    {...f.checkpoint,schema:"PriviFinancialFinality/v1"}
  ];
  for(const c of changed){
    assert.throws(()=>verifyResearchCheckpoint(f.committee,c,f.governance.publicKey));
  }
  const malformed=f.resign({...f.checkpoint,blockHash:"invalid"});
  assert.throws(()=>verifyResearchCheckpoint(f.committee,malformed,
                f.governance.publicKey),/canonical block hash/);
});

test("production-finality claims, arbitrary metadata and incomplete attestation refuse verification",()=>{
  const f=fixture();
  for(const extra of [
    {finalized:true},{productionConsensus:true},
    {executionProven:true},{genesisAllocation:"real"}
  ]){
    assert.throws(()=>verifyResearchCheckpoint(
      f.committee,{...f.checkpoint,...extra},f.governance.publicKey),
      /missing or unexpected fields/);
  }
  const incomplete={...f.checkpoint};
  delete incomplete.signatureB64;
  assert.throws(()=>verifyResearchCheckpoint(f.committee,incomplete,
                f.governance.publicKey),/missing or unexpected fields/);
  const invalid={...f.checkpoint,signatureB64:"AQ=="};
  assert.throws(()=>verifyResearchCheckpoint(f.committee,invalid,
                f.governance.publicKey),/canonical/);
});

test("checkpoint height is bounded and does not accept JS unsafe integers",()=>{
  const f=fixture();
  for(const height of [-1,0.2,Number.MAX_SAFE_INTEGER,Number.MAX_SAFE_INTEGER+1,NaN,Infinity]){
    const checkpoint=f.resign({...f.checkpoint,height});
    assert.throws(()=>verifyResearchCheckpoint(f.committee,checkpoint,
                  f.governance.publicKey),/bounded integer/);
  }
  const genesis=f.resign({...f.checkpoint,height:0});
  assert.equal(verifyResearchCheckpoint(f.committee,genesis,
               f.governance.publicKey).height,0);
});

test("a caller-supplied committee shallow copy is not a valid governance admission",()=>{
  const f=fixture();
  assert.throws(()=>verifyResearchCheckpoint({...f.committee},
                f.checkpoint,f.governance.publicKey),/Unverified PoP committee/);
});

test("a valid checkpoint cannot rescue a forged, disconnected, or insufficient-quorum candidate batch",()=>{
  const f=fixture();
  const broken=f.batch();
  broken[1].proposal.previousBlockHash="0x"+"b".repeat(64);
  assert.throws(()=>verifyAttestedCandidateAncestry(
    f.committee,f.checkpoint,f.governance.publicKey,broken),/parent hash mismatch/);
  const low=f.batch();
  low[0].votes.pop();
  assert.throws(()=>verifyAttestedCandidateAncestry(
    f.committee,f.checkpoint,f.governance.publicKey,low),/quorum/);
  assert.throws(()=>verifyAttestedCandidateAncestry(
    f.committee,{height:30,blockHash:f.checkpoint.blockHash},
    f.governance.publicKey,f.batch()),/missing or unexpected fields/);
});

test("a signed but incorrect starting checkpoint cannot authorize the unrelated candidate history",()=>{
  const f=fixture();
  const conflicting=f.resign({...f.checkpoint,blockHash:"0x"+"a".repeat(64)});
  assert.throws(()=>verifyAttestedCandidateAncestry(
    f.committee,conflicting,f.governance.publicKey,f.batch()),
    /parent hash mismatch/);
});

test("signatures are bound to research schema and domain-separated from validator admissions",()=>{
  const f=fixture();
  const fake={...f.checkpoint,signatureB64:sign(
    f.governance,"admit",checkpointFields(f.checkpoint)
  )};
  assert.throws(()=>verifyResearchCheckpoint(f.committee,fake,
                f.governance.publicKey),/issuer signature invalid/);
});
