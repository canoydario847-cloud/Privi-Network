"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const crypto=require("node:crypto");
const {
  hash,positionStamp,parseRegistry,signedMessage,proposer,proposalFields,
  voteFields,TRUSTED_MODE
}=require("./engine.cjs");
const {verifyCandidateAncestry,MAX_CERTIFICATES}=require("./candidate_ancestry.cjs");

function newKey() {
  const pair=crypto.generateKeyPairSync("ed25519");
  const der=pair.publicKey.export({type:"spki",format:"der"});
  return {id:hash(der),pub:der.toString("base64"),privateKey:pair.privateKey};
}
function sign(key,tag,fields) {
  return crypto.sign(null,signedMessage(tag,fields),key.privateKey).toString("base64");
}
function makeFixture(n=4) {
  const gov=newKey(),keys=Array.from({length:n},newKey);
  const chainId="privi-pop-research-ancestry",genesisHash="0x"+"a".repeat(64);
  const epoch=1;
  const validators=keys.map((key,i)=>{
    const operatorId="OPERATOR_"+i;
    const faultDomain="host"+i+".isolated.test";
    const companyId="ORG_"+i,positionSequence=i+1;
    const anchorBlockHash=hash(Buffer.from("synthetic-position-anchor-"+i));
    const positionHash=hash(Buffer.from(positionStamp(companyId,positionSequence)));
    const fields=[chainId,genesisHash,epoch,operatorId,faultDomain,
      companyId,positionSequence,key.id,anchorBlockHash];
    return {id:key.id,keySpkiBase64:key.pub,operatorId,faultDomain,companyId,
      positionSequence,anchorBlockHash,positionHash,
      admissionSignature:sign(gov,"admit",fields)};
  });
  const committee=parseRegistry({mode:TRUSTED_MODE,chainId,genesisHash,
    epoch,validators},gov.pub);
  const keyById=new Map(keys.map(k=>[k.id,k]));
  const checkpoint={height:5,blockHash:"0x"+"e".repeat(64)};
  function certificate(height,previousBlockHash,blockHash,round=0,voteCount=committee.quorum) {
    const proposerId=proposer(committee,height,round);
    const fields=proposalFields(committee,height,round,previousBlockHash,blockHash,proposerId);
    const proposal={height,round,previousBlockHash,blockHash,proposerId,
      signature:sign(keyById.get(proposerId),"propose",fields)};
    const votes=committee.validators.slice(0,voteCount).map(v=>({
      validatorId:v.id,signature:sign(keyById.get(v.id),"commit",voteFields(fields,v.id))
    }));
    return {proposal,votes};
  }
  function sequence(length=3){
    const list=[];
    let parent=checkpoint.blockHash;
    for(let step=1;step<=length;step++){
      const height=checkpoint.height+step;
      const current="0x"+height.toString(16).padStart(64,"0");
      list.push(certificate(height,parent,current,step%2));
      parent=current;
    }
    return list;
  }
  return {committee,checkpoint,certificate,sequence};
}

test("verifies three locally signed contiguous 3-of-4 research candidate certificates",()=>{
  const f=makeFixture(),certificates=f.sequence();
  const proof=verifyCandidateAncestry(f.committee,f.checkpoint,certificates);
  assert.equal(proof.researchOnly,true);
  assert.equal(proof.productionConsensus,false);
  assert.equal(proof.finalized,false);
  assert.equal(proof.verifiesExecution,false);
  assert.equal(proof.verifiesCheckpointAuthenticity,false);
  assert.equal(proof.verifiedCandidateCertificates,3);
  assert.equal(proof.checkedSignatures,9);
  assert.equal(proof.checkpointHeight,5);
  assert.equal(proof.endingHeight,8);
  assert.equal(proof.endingBlockHash,certificates[2].proposal.blockHash);
  assert.equal(proof.governanceKeyId,f.committee.governanceKeyId);
  assert.equal(Object.isFrozen(proof),true);
});

test("works with a correctly signed 5-of-7 research certificate sequence",()=>{
  const f=makeFixture(7);
  const proof=verifyCandidateAncestry(f.committee,f.checkpoint,f.sequence(2));
  assert.equal(proof.verifiedCandidateCertificates,2);
  assert.equal(proof.checkedSignatures,10);
  assert.equal(proof.productionConsensus,false);
});

test("fails closed on empty, oversized, or forged research batch",()=>{
  const f=makeFixture(),items=f.sequence();
  assert.throws(()=>verifyCandidateAncestry(f.committee,f.checkpoint,[]),/1..256/);
  assert.throws(()=>verifyCandidateAncestry(f.committee,f.checkpoint,
    Array.from({length:MAX_CERTIFICATES+1},()=>items[0])),/1..256/);
  assert.throws(()=>verifyCandidateAncestry({...f.committee},f.checkpoint,items),
    /Unverified PoP committee/);
  assert.throws(()=>verifyCandidateAncestry(f.committee,f.checkpoint,{}),/1..256/);
});

test("rejects inherited, accessor-backed, and ambiguous caller-supplied checkpoints",()=>{
  const f=makeFixture(),items=f.sequence(1);
  const inherited=Object.create({height:f.checkpoint.height});
  inherited.blockHash=f.checkpoint.blockHash;
  let getterReads=0;
  const accessor={blockHash:f.checkpoint.blockHash};
  Object.defineProperty(accessor,"height",{
    enumerable:true,get(){getterReads++;return f.checkpoint.height;}
  });
  for(const untrusted of [
    inherited,accessor,{...f.checkpoint,finalized:true},
    Object.assign(Object.create(null),f.checkpoint)
  ]){
    assert.throws(()=>verifyCandidateAncestry(f.committee,untrusted,items),
      /plain own height and blockHash data fields/);
  }
  assert.equal(getterReads,0,"untrusted checkpoint getter must not execute");
  assert.equal(verifyCandidateAncestry(f.committee,f.checkpoint,items)
    .verifiedCandidateCertificates,1);
});

test("research certificate envelopes reject getters, inherited fields and hidden finality claims",()=>{
  const f=makeFixture(),valid=f.sequence(1)[0];
  let getterReads=0;
  const accessor={votes:valid.votes};
  Object.defineProperty(accessor,"proposal",{
    enumerable:true,get(){getterReads++;return valid.proposal;}
  });
  const inherited=Object.create({proposal:valid.proposal});
  inherited.votes=valid.votes;
  const hidden={...valid};
  Object.defineProperty(hidden,"finalized",{value:true,enumerable:false});
  const symbolic={...valid};
  symbolic[Symbol("productionConsensus")]=true;
  const nonenumerable={...valid};
  Object.defineProperty(nonenumerable,"votes",{
    value:valid.votes,enumerable:false
  });
  for(const untrusted of [
    accessor,inherited,hidden,symbolic,nonenumerable,
    Object.assign(Object.create(null),valid)
  ]){
    assert.throws(()=>verifyCandidateAncestry(f.committee,f.checkpoint,[untrusted]),
      /plain own proposal and votes data fields/);
  }
  assert.equal(getterReads,0,"untrusted certificate getter must not execute");
  assert.equal(verifyCandidateAncestry(f.committee,f.checkpoint,[valid])
    .verifiedCandidateCertificates,1);
});

test("caller-supplied zero-height anchor rejects negative-zero alias",()=>{
  const f=makeFixture();
  const genesis={height:0,blockHash:f.checkpoint.blockHash};
  const first=f.certificate(1,genesis.blockHash,"0x"+"d".repeat(64));
  assert.equal(verifyCandidateAncestry(f.committee,genesis,[first]).endingHeight,1);
  const aliased={...genesis,height:-0};
  assert.equal(Object.is(aliased.height,-0),true);
  assert.throws(()=>verifyCandidateAncestry(f.committee,aliased,[first]),
    /nonnegative safe integer/);
});

test("detects missing starting candidate and gap after accepted height",()=>{
  const f=makeFixture(),items=f.sequence(3);
  assert.throws(()=>verifyCandidateAncestry(f.committee,f.checkpoint,items.slice(1)),
    /height gap/);
  assert.throws(()=>verifyCandidateAncestry(f.committee,f.checkpoint,
    [items[0],items[2]]),/height gap/);
});

test("rejects rollback, reversed order, repeated height and duplicate entries",()=>{
  const f=makeFixture(),items=f.sequence(3);
  assert.throws(()=>verifyCandidateAncestry(f.committee,f.checkpoint,
    [items[1],items[0],items[2]]),/height gap/);
  assert.throws(()=>verifyCandidateAncestry(f.committee,f.checkpoint,
    [items[0],items[0]]),/height gap/);
  assert.throws(()=>verifyCandidateAncestry(f.committee,f.checkpoint,
    [items[0],items[1],items[1]]),/height gap/);
});

test("rejects a different genesis/checkpoint anchor even with valid individual signatures",()=>{
  const f=makeFixture(),items=f.sequence();
  assert.throws(()=>verifyCandidateAncestry(f.committee,
    {height:5,blockHash:"0x"+"f".repeat(64)},items),/parent hash mismatch/);
  assert.throws(()=>verifyCandidateAncestry(f.committee,
    {height:6,blockHash:f.checkpoint.blockHash},items),/height gap/);
});

test("detects a re-signed parent link that contradicts the prior signed candidate",()=>{
  const f=makeFixture(),items=f.sequence();
  const old=items[1].proposal;
  items[1]=f.certificate(old.height,"0x"+"d".repeat(64),old.blockHash,old.round);
  assert.throws(()=>verifyCandidateAncestry(f.committee,f.checkpoint,items),
    /parent hash mismatch/);
});

test("rejects valid but cyclic candidate block hashes",()=>{
  const f=makeFixture(),items=f.sequence(3);
  const last=items[2].proposal;
  // Third candidate is individually signed but repeats the first block's
  // hash under the second block; cannot be a new unique chain step.
  items[2]=f.certificate(last.height,items[1].proposal.blockHash,
                           items[0].proposal.blockHash,last.round);
  assert.throws(()=>verifyCandidateAncestry(f.committee,f.checkpoint,items),
    /duplicate or cyclic block hash/);
});

test("rejects nonquorum and duplicated signer certificates",()=>{
  const f=makeFixture(),items=f.sequence(2);
  items[1]=f.certificate(items[1].proposal.height,items[1].proposal.previousBlockHash,
    items[1].proposal.blockHash,items[1].proposal.round,2);
  assert.throws(()=>verifyCandidateAncestry(f.committee,f.checkpoint,items),/quorum/);
  const g=makeFixture(),batch=g.sequence(2);
  batch[1].votes[1]=batch[1].votes[0];
  assert.throws(()=>verifyCandidateAncestry(g.committee,g.checkpoint,batch),
    /Duplicate PoP voter/);
});

test("rejects tampering with already signed block hash, proposer, parent or height",()=>{
  const mutations=[
    b=>{b[0].proposal.blockHash="0x"+"f".repeat(64);},
    b=>{b[1].proposal.proposerId="0x"+"c".repeat(64);},
    b=>{b[0].proposal.previousBlockHash="0x"+"a".repeat(64);},
    b=>{b[1].proposal.height=42;}
  ];
  for(const alter of mutations){
    const f=makeFixture(),items=f.sequence();
    alter(items);
    assert.throws(()=>verifyCandidateAncestry(f.committee,f.checkpoint,items));
  }
});

test("refuses a forged vote signature on an otherwise connected chain",()=>{
  const f=makeFixture(),items=f.sequence();
  items[2].votes[0].signature=items[2].votes[1].signature;
  assert.throws(()=>verifyCandidateAncestry(f.committee,f.checkpoint,items),
    /Forged or wrong-epoch/);
});

test("rejects malformed checkpoint, overflow and incomplete research certificate",()=>{
  const f=makeFixture(),items=f.sequence();
  for(const invalid of [null,{},{height:-1,blockHash:f.checkpoint.blockHash},
    {height:1.5,blockHash:f.checkpoint.blockHash},
    {height:5,blockHash:"0xNOTHEX"}]){
    assert.throws(()=>verifyCandidateAncestry(f.committee,invalid,items));
  }
  assert.throws(()=>verifyCandidateAncestry(f.committee,
    {height:Number.MAX_SAFE_INTEGER,blockHash:f.checkpoint.blockHash},items),
    /height gap/);
  assert.throws(()=>verifyCandidateAncestry(f.committee,f.checkpoint,[null]),
    /malformed research certificate/);
  assert.throws(()=>verifyCandidateAncestry(f.committee,f.checkpoint,
    [{proposal:null,votes:[]}]),/missing candidate proposal/);
});

test("research certificate batches reject unsigned metadata, holes and index getters",()=>{
  const f=makeFixture(),items=f.sequence(2);
  let getterReads=0;
  const decorated=[...items];
  decorated.finalized=true;
  const hidden=[...items];
  Object.defineProperty(hidden,"productionConsensus",{value:true});
  const symbolic=[...items];
  symbolic[Symbol("mainnet")]=true;
  const accessor=[...items];
  Object.defineProperty(accessor,"0",{
    enumerable:true,configurable:true,
    get(){getterReads++;throw Error("untrusted certificate index getter executed");}
  });
  const sparse=[...items];
  delete sparse[1];
  const inherited=[...items];
  Object.setPrototypeOf(inherited,Object.create(Array.prototype));
  for(const untrusted of [decorated,hidden,symbolic,accessor,sparse,inherited]){
    assert.throws(()=>verifyCandidateAncestry(f.committee,f.checkpoint,untrusted),
      /dense plain data array/);
  }
  assert.equal(getterReads,0,"untrusted certificate index getter must not execute");
  const proof=verifyCandidateAncestry(f.committee,f.checkpoint,items);
  assert.equal(proof.verifiedCandidateCertificates,2);
  assert.equal(proof.finalized,false);
  assert.equal(proof.productionConsensus,false);
});

test("research ancestry uses declared certificate slots, not Proxy iterators or index getters",()=>{
  const f=makeFixture(),items=f.sequence(2);
  let iteratorReads=0,indexReads=0;
  const injected=new Proxy([items[0]],{
    get(target,key,receiver){
      if(key==="entries"){
        iteratorReads++;
        return ()=>items.entries();
      }
      if(key==="0"){
        indexReads++;
        return items[1];
      }
      return Reflect.get(target,key,receiver);
    }
  });
  const checked=verifyCandidateAncestry(f.committee,f.checkpoint,injected);
  assert.equal(checked.verifiedCandidateCertificates,1);
  assert.equal(checked.endingHeight,items[0].proposal.height);
  assert.equal(checked.endingBlockHash,items[0].proposal.blockHash);
  assert.equal(iteratorReads,0,"untrusted certificate iterator must not execute");
  assert.equal(indexReads,0,"untrusted certificate index getter must not execute");

  const swapped=new Proxy([items[0]],{
    get(target,key,receiver){
      if(key==="0"){
        indexReads++;
        return items[1];
      }
      return Reflect.get(target,key,receiver);
    }
  });
  const second=verifyCandidateAncestry(f.committee,f.checkpoint,swapped);
  assert.equal(second.endingHeight,items[0].proposal.height);
  assert.equal(second.verifiedCandidateCertificates,1);
  assert.equal(indexReads,0,"validated certificate descriptor must be authoritative");
  assert.equal(second.finalized,false);
  assert.equal(second.productionConsensus,false);
});
