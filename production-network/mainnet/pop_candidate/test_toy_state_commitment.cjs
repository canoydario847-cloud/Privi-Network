"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const crypto=require("node:crypto");
const {
  hash,positionStamp,parseRegistry,signedMessage,proposer,
  proposalFields,voteFields,TRUSTED_MODE
}=require("./engine.cjs");
const {SCHEMA,MODE,SIGNING_TAG,checkpointFields}=require("./checkpoint_attestation.cjs");
const {
  stateRoot,computeResearchBlock,verifyResearchStateSequence
}=require("./toy_state_commitment.cjs");

function makeKey(){
  const pair=crypto.generateKeyPairSync("ed25519");
  const pub=pair.publicKey.export({format:"der",type:"spki"});
  return {id:hash(pub),pub:pub.toString("base64"),privateKey:pair.privateKey};
}
function sign(key,tag,fields){
  return crypto.sign(null,signedMessage(tag,fields),key.privateKey).toString("base64");
}
function fixture(n=4){
  const gov=makeKey(),keys=Array.from({length:n},makeKey);
  const chainId="privi-pop-research-toy-state";
  const genesisHash="0x"+"a".repeat(64),epoch=1;
  const validators=keys.map((key,i)=>{
    const operatorId="OP_"+i,faultDomain="host"+i+".independent.test";
    const companyId="ORG_"+i,positionSequence=i+1;
    const anchorBlockHash=hash(Buffer.from("toy-state-position-"+i));
    const positionHash=hash(Buffer.from(positionStamp(companyId,positionSequence)));
    return {
      id:key.id,keySpkiBase64:key.pub,operatorId,faultDomain,
      companyId,positionSequence,anchorBlockHash,positionHash,
      admissionSignature:sign(gov,"admit",[
        chainId,genesisHash,epoch,operatorId,faultDomain,companyId,
        positionSequence,key.id,anchorBlockHash
      ])
    };
  });
  const committee=parseRegistry({chainId,genesisHash,epoch,
                                  mode:TRUSTED_MODE,validators},gov.pub);
  const byKey=new Map(keys.map(k=>[k.id,k]));
  const checkpointUnsigned={
    schema:SCHEMA,mode:MODE,chainId,genesisHash,epoch,height:5,
    blockHash:"0x"+"e".repeat(64),governanceKeyId:gov.id
  };
  const checkpoint={
    ...checkpointUnsigned,
    signatureB64:sign(gov,SIGNING_TAG,checkpointFields(checkpointUnsigned))
  };
  const startingState={agent_a:{value:2,nonce:0}};
  function signedCertificate(block,round=0,voteCount=committee.quorum){
    const proposerId=proposer(committee,block.height,round);
    const fields=proposalFields(committee,block.height,round,
                                block.previousBlockHash,block.blockHash,proposerId);
    const proposal={height:block.height,round,
      previousBlockHash:block.previousBlockHash,blockHash:block.blockHash,
      proposerId,signature:sign(byKey.get(proposerId),"propose",fields)};
    const votes=committee.validators.slice(0,voteCount).map(v=>({
      validatorId:v.id,
      signature:sign(byKey.get(v.id),"commit",voteFields(fields,v.id))
    }));
    return {proposal,votes};
  }
  function build(opsList=[
    [{kind:"increment",account:"agent_a",amount:3,nonce:1}],
    [{kind:"increment",account:"agent_a",amount:4,nonce:2},
     {kind:"increment",account:"agent_b",amount:1,nonce:1}]
  ]){
    let previous=checkpoint.blockHash,state=startingState;
    const blocks=[],certificates=[];
    opsList.forEach((ops,i)=>{
      const result=computeResearchBlock(committee,state,checkpoint.height+1+i,
                                        previous,ops);
      blocks.push(result.block);
      certificates.push(signedCertificate(result.block,i%2));
      previous=result.block.blockHash;
      state=result.nextState;
    });
    return {blocks,certificates};
  }
  function verify(ops=build(),initial=startingState,startingDigest=stateRoot(startingState),
                  trustKey=gov.pub,issuedCheckpoint=checkpoint){
    return verifyResearchStateSequence(
      committee,issuedCheckpoint,trustKey,initial,startingDigest,
      ops.certificates,ops.blocks
    );
  }
  return {gov,keys,committee,checkpoint,startingState,build,verify,signedCertificate};
}
test("four-val research quorums bind nonfinancial toy execution to two signed block commitments",()=>{
  const f=fixture(),result=f.verify();
  assert.equal(result.researchOnly,true);
  assert.equal(result.nonFinancialToyState,true);
  assert.equal(result.finalized,false);
  assert.equal(result.productionConsensus,false);
  assert.equal(result.validatesLiveCosmosEvmState,false);
  assert.equal(result.checkpointFinalityVerified,false);
  assert.equal(result.startingStateExternallyAuthenticated,false);
  assert.equal(result.verifiedToyTransitions,2);
  assert.equal(result.endingHeight,7);
  assert.equal(result.endingState.agent_a.value,9);
  assert.equal(result.endingState.agent_a.nonce,2);
  assert.equal(result.endingState.agent_b.value,1);
  assert.equal(result.endingState.agent_b.nonce,1);
  assert.equal(result.endingStateRoot,stateRoot(result.endingState));
  assert.ok(Object.isFrozen(result));
  assert.ok(Object.isFrozen(result.endingState));
  assert.ok(Object.isFrozen(result.endingState.agent_a));
});
test("seven-val five-vote research quorum preserves toy deterministic execution",()=>{
  const f=fixture(7),result=f.verify();
  assert.equal(result.endingHeight,7);
  assert.equal(result.endingState.agent_a.value,9);
  assert.equal(result.nonFinancialToyState,true);
});
test("initial state commitment is insensitive to JSON object insertion order",()=>{
  const original={agent_z:{value:3,nonce:2},agent_a:{value:4,nonce:3}};
  const reordered={agent_a:{nonce:3,value:4},agent_z:{nonce:2,value:3}};
  assert.equal(stateRoot(original),stateRoot(reordered));
});
test("starting state manipulation is detected against independently given digest",()=>{
  const f=fixture(),trials=f.build();
  assert.throws(()=>f.verify(trials,{agent_a:{value:999,nonce:0}}),
    /does not match independently supplied expected root/);
  assert.throws(()=>f.verify(trials,f.startingState,"0x"+"0".repeat(64)),
    /does not match independently supplied expected root/);
});
test("signed block votes cannot validate modified nonfinancial operation contents",()=>{
  const f=fixture(),trials=f.build();
  trials.blocks[0].operations[0].amount=999;
  assert.throws(()=>f.verify(trials),
    /operations root mismatch|claimed state root mismatch|signed block hash/);
});
test("signed block votes cannot validate an invented claimed state root",()=>{
  const f=fixture(),trials=f.build();
  trials.blocks[1]={...trials.blocks[1],stateRoot:"0x"+"a".repeat(64)};
  assert.throws(()=>f.verify(trials),/claimed state root mismatch/);
});
test("changing operation ordering invalidates nonces or recomputed commitments",()=>{
  const f=fixture(),trials=f.build([[
    {kind:"increment",account:"agent_a",amount:3,nonce:1},
    {kind:"increment",account:"agent_a",amount:4,nonce:2}
  ]]);
  trials.blocks[0].operations.reverse();
  assert.throws(()=>f.verify(trials),/nonce/);
});
test("copying or dropping a signed certificate/block cannot reproduce state history",()=>{
  const f=fixture();
  const missing=f.build();missing.blocks.pop();
  assert.throws(()=>f.verify(missing),/count mismatch/);
  const duplicate=f.build();duplicate.blocks[1]=missing.blocks[0];
  assert.throws(()=>f.verify(duplicate),/candidate header|state root|operations root|replayed, missing or reordered operation nonce/);
});
test("a valid signed candidate hash for different toy state is not acceptable",()=>{
  const f=fixture();
  const trials=f.build();
  const block=trials.blocks[1];
  trials.blocks[1]={...block,blockHash:"0x"+"f".repeat(64)};
  assert.throws(()=>f.verify(trials),/signed block hash/);
});
test("invalid governance checkpoint and unverified committee cannot authorize toy state verification",()=>{
  const f=fixture(),trials=f.build();
  assert.throws(()=>f.verify(trials,f.startingState,stateRoot(f.startingState),
                makeKey().pub),/independently trusted|not the independently trusted/);
  assert.throws(()=>verifyResearchStateSequence(
    {...f.committee},f.checkpoint,f.gov.pub,f.startingState,
    stateRoot(f.startingState),trials.certificates,trials.blocks
  ),/Unverified PoP committee/);
});
test("forged voter or unsupported non-quorum certificate is rejected",()=>{
  const f=fixture(),a=f.build();
  a.certificates[0].votes.pop();
  assert.throws(()=>f.verify(a),/quorum/);
  const b=f.build();
  b.certificates[0].votes[0].signature=b.certificates[0].votes[1].signature;
  assert.throws(()=>f.verify(b),/Forged|wrong-epoch/);
});
test("operation nonces must progress exactly once across blocks",()=>{
  const f=fixture();
  assert.throws(()=>f.build([[
    {kind:"increment",account:"agent_a",amount:2,nonce:2}
  ]]),/nonce/);
  assert.throws(()=>f.build([
    [{kind:"increment",account:"agent_a",amount:2,nonce:1}],
    [{kind:"increment",account:"agent_a",amount:2,nonce:1}]
  ]),/nonce/);
});
test("does not accept financial, unsupported, negative, overflow, or noncanonical operations",()=>{
  const f=fixture(),good={kind:"increment",account:"agent_a",amount:2,nonce:1};
  for(const bad of [
    {...good,kind:"transfer"},{...good,kind:"mint"},
    {...good,amount:-1},{...good,amount:0},{...good,amount:1000001},
    {...good,nonce:0},{...good,nonce:1.1},
    {...good,account:"__proto__"},
    {...good,account:"A"},{...good,extra:"noncanonical"}
  ])assert.throws(()=>f.build([[bad]]));
  const maxState={agent_a:{value:Number.MAX_SAFE_INTEGER,nonce:0}};
  assert.throws(()=>computeResearchBlock(f.committee,maxState,6,
    f.checkpoint.blockHash,[good]),/counter overflow/);
});
test("limits number of research accounts, operations, certificates and invalid state",()=>{
  const f=fixture(),single={kind:"increment",account:"agent_a",amount:1,nonce:1};
  assert.throws(()=>f.build([[]]),/1..64 operations/);
  const repeated=Array.from({length:65},(_,i)=>({...single,nonce:i+1}));
  assert.throws(()=>f.build([repeated]),/1..64 operations/);
  const badState={agent_a:{value:-3,nonce:0}};
  assert.throws(()=>stateRoot(badState),/invalid safe integer/);
  assert.throws(()=>stateRoot({agent_a:{value:3,nonce:0,hidden:3}}),
                /unexpected fields/);
  assert.throws(()=>stateRoot([]),/plain-object accounts/);
  assert.throws(()=>f.verify({blocks:[],certificates:[]}),/1..64 entries/);
  const fixtureTooLong=f.build(Array.from({length:65},(_,i)=>[
    {kind:"increment",account:"agent_a",amount:1,nonce:i+1}
  ]));
  assert.throws(()=>f.verify(fixtureTooLong),/1..64 entries/);
});
test("unexpected block fields, signed-header changes and mismatched parent are refused",()=>{
  const f=fixture(),sample=f.build();
  sample.blocks[0]={...sample.blocks[0],productionFinalized:true};
  assert.throws(()=>f.verify(sample),/unexpected fields/);
  const b=f.build();
  b.blocks[1]={...b.blocks[1],previousBlockHash:"0x"+"a".repeat(64)};
  assert.throws(()=>f.verify(b),/candidate header/);
});
