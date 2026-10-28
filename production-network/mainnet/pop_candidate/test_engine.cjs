"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const crypto=require("node:crypto");
const {
  hash,signedMessage,parseRegistry,positionStamp,proposer,
  proposalFields,voteFields,verifyCertificate,ResearchVoteLock,TRUSTED_MODE
}=require("./engine.cjs");

function makeKey(){
  const pair=crypto.generateKeyPairSync("ed25519");
  const der=pair.publicKey.export({type:"spki",format:"der"});
  return {id:hash(der), publicKeyB64:der.toString("base64"),privateKey:pair.privateKey};
}
function sign(key,tag,fields){
  return crypto.sign(null,signedMessage(tag,fields),key.privateKey).toString("base64");
}
function fixture(count=4){
  const gov=makeKey(), keys=Array.from({length:count},()=>makeKey());
  const chainId="privi-pop-research-test-v1",genesisHash="0x"+"a".repeat(64);
  const epoch=1;
  const registry={
    mode:TRUSTED_MODE,chainId,genesisHash,epoch,
    validators:keys.map((k,i)=>{
      const operatorId="OPERATOR_"+i;
      const faultDomain="host"+i+".separate-operator.test";
      const companyId="ORG_"+i,positionSequence=i+1;
      const anchorBlockHash=hash(Buffer.from("privi-test-position-block-"+i));
      const positionHash=hash(Buffer.from(positionStamp(companyId,positionSequence)));
      const fields=[chainId,genesisHash,epoch,operatorId,faultDomain,companyId,
                    positionSequence,k.id,anchorBlockHash];
      return {
        id:k.id,keySpkiBase64:k.publicKeyB64,operatorId,faultDomain,
        companyId,positionSequence,anchorBlockHash,positionHash,
        admissionSignature:sign(gov,"admit",fields)
      };
    })
  };
  const committee=parseRegistry(registry,gov.publicKeyB64);
  const byKey=new Map(keys.map(k=>[k.id,k]));
  function bundle(height=5,round=0,previousBlockHash="0x"+"b".repeat(64),
                  blockHash="0x"+"c".repeat(64),votesCount=committee.quorum){
    const proposerId=proposer(committee,height,round);
    const fields=proposalFields(committee,height,round,previousBlockHash,blockHash,proposerId);
    const proposal={height,round,previousBlockHash,blockHash,proposerId,
                    signature:sign(byKey.get(proposerId),"propose",fields)};
    const votes=committee.validators.slice(0,votesCount).map(v=>({
      validatorId:v.id,
      signature:sign(byKey.get(v.id),"commit",voteFields(fields,v.id))
    }));
    return {proposal,votes};
  }
  return {gov,keys,registry,committee,bundle};
}

test("four unique PoP position admissions yield exact three-of-four quorum",()=>{
  const f=fixture();
  assert.equal(f.committee.quorum,3);
  assert.equal(f.committee.validators.length,4);
  assert.equal(f.committee.epoch,1);
  assert.equal(f.committee.mode,TRUSTED_MODE);
  assert.equal(f.committee.validators.every(v=>v.stamp.startsWith("PoP:ORG_")),true);
  const {proposal,votes}=f.bundle();
  const proof=verifyCertificate(f.committee,proposal,votes);
  assert.equal(proof.valid,true);
  assert.equal(proof.signers,3);
  assert.equal(proof.chainId,f.committee.chainId);
  assert.equal(proof.genesisHash,f.committee.genesisHash);
  assert.equal(proof.governanceKeyId,f.committee.governanceKeyId);
  assert.equal(proof.previousBlockHash,proposal.previousBlockHash);
  assert.equal(proof.blockHash,proposal.blockHash);
  assert.equal(proof.finalized,false);
  assert.equal(proof.validatesExecution,false);
  assert.equal(proof.validatorIndependenceVerified,false);
  assert.equal(proof.productionConsensus,false);
  assert.equal(Object.isFrozen(proof),true);
});

test("research certificate signer attribution is deterministic and immutable",()=>{
  const f=fixture(7);
  const {proposal,votes}=f.bundle();
  const expected=votes.map(v=>v.validatorId).sort();
  const forward=verifyCertificate(f.committee,proposal,votes);
  const reversed=verifyCertificate(f.committee,proposal,[...votes].reverse());
  assert.deepEqual(forward.signerIds,expected);
  assert.deepEqual(reversed.signerIds,expected);
  assert.equal(forward.signerIds.length,forward.signers);
  assert.equal(Object.isFrozen(forward.signerIds),true);
  assert.throws(()=>{forward.signerIds[0]="0x"+"f".repeat(64);},TypeError);
  assert.throws(()=>{forward.signerIds.push("forged");},TypeError);
  assert.deepEqual(forward.signerIds,expected);
  assert.equal(forward.finalized,false);
  assert.equal(forward.productionConsensus,false);
});

test("candidate certificate refuses caller-forged quorum and committee copies",()=>{
  const f=fixture();
  const {proposal,votes}=f.bundle();
  assert.equal(verifyCertificate(f.committee,proposal,votes).valid,true);
  const forged={...f.committee,quorum:1};
  assert.throws(()=>verifyCertificate(forged,proposal,votes.slice(0,1)),
                /Unverified PoP committee/);
  // Reusing the same keys and membership does not turn a shallow copy
  // into an independently attested admission record.
  assert.throws(()=>verifyCertificate({...f.committee},proposal,votes),
                /Unverified PoP committee/);
  assert.equal(Object.isFrozen(f.committee),true);
  assert.equal(Object.isFrozen(f.committee.validators),true);
  assert.equal(Object.isFrozen(f.committee.validators[0]),true);
  assert.throws(()=>{f.committee.quorum=1;},TypeError);
  assert.throws(()=>{f.committee.validators.pop();},TypeError);
});

test("candidate certificate detects post-admission signer-map tampering",()=>{
  const f=fixture();
  const {proposal,votes}=f.bundle();
  const signer=f.committee.validators[0];
  const original=f.committee.byId.get(signer.id);
  try {
    f.committee.byId.set(signer.id,{...original});
    assert.throws(()=>verifyCertificate(f.committee,proposal,votes),
                  /membership changed/);
    f.committee.byId.delete(signer.id);
    assert.throws(()=>verifyCertificate(f.committee,proposal,votes),
                  /quorum or membership metadata inconsistent/);
  } finally {
    f.committee.byId.set(signer.id,original);
  }
  assert.equal(verifyCertificate(f.committee,proposal,votes).valid,true);
});

test("quorum never formed from one or two votes",()=>{
  const f=fixture();
  for(const n of [0,1,2]){
    const {proposal,votes}=f.bundle(5,0,undefined,undefined,n);
    assert.throws(()=>verifyCertificate(f.committee,proposal,votes),/quorum/);
  }
});

test("research election is deterministic, not PRVI balances/PoS/PoSA",()=>{
  const f=fixture(7);
  assert.equal(f.committee.quorum,5);
  for(const r of [0,1,2,17]){
    const id=proposer(f.committee,63,r);
    assert.equal(id,proposer(f.committee,63,r));
    assert.equal(f.committee.byId.has(id),true);
  }
  assert.equal(f.registry.validators.some(v=>Object.hasOwn(v,"stake")),false);
});

test("research proposer refuses forged or post-admission modified committees",()=>{
  const f=fixture(4);
  const original=proposer(f.committee,9,0);
  assert.equal(f.committee.byId.has(original),true);
  assert.throws(()=>proposer({...f.committee},9,0),
                /Unverified PoP committee/);
  // A cloned roster cannot confer proposer authority, even with the same
  // IDs, quorum, epoch and genesis as a verified registry.
  assert.throws(()=>proposer({
    ...f.committee,
    validators:[...f.committee.validators],
    byId:new Map(f.committee.byId)
  },9,0),/Unverified PoP committee/);
  const signer=f.committee.validators[0];
  const originalEntry=f.committee.byId.get(signer.id);
  try {
    f.committee.byId.set(signer.id,{...originalEntry});
    assert.throws(()=>proposer(f.committee,9,0),
                  /membership changed/);
  } finally {
    f.committee.byId.set(signer.id,originalEntry);
  }
  assert.equal(proposer(f.committee,9,0),original);
});

test("reject unapproved, copied or forged PoP authority",()=>{
  const f=fixture();
  const invalid=structuredClone(f.registry);
  invalid.validators[0].admissionSignature=f.registry.validators[1].admissionSignature;
  assert.throws(()=>parseRegistry(invalid,f.gov.publicKeyB64),/admission signature/);
  const clone=structuredClone(f.registry);
  clone.validators[1].operatorId=clone.validators[0].operatorId;
  assert.throws(()=>parseRegistry(clone,f.gov.publicKeyB64),/Duplicated|admission signature/);
  const sameHost=structuredClone(f.registry);
  sameHost.validators[1].faultDomain=sameHost.validators[0].faultDomain;
  assert.throws(()=>parseRegistry(sameHost,f.gov.publicKeyB64),/Duplicated|admission signature/);
  const forgedPosition=structuredClone(f.registry);
  forgedPosition.validators[0].positionHash="0x"+"f".repeat(64);
  assert.throws(()=>parseRegistry(forgedPosition,f.gov.publicKeyB64),/anchor stamp mismatch/);
  const pretendMainnet=structuredClone(f.registry);
  pretendMainnet.mode="production-mainnet";
  assert.throws(()=>parseRegistry(pretendMainnet,f.gov.publicKeyB64),/Cannot run candidate as mainnet/);
  const foreignChain=structuredClone(f.registry);
  foreignChain.chainId="ethereum";
  assert.throws(()=>parseRegistry(foreignChain,f.gov.publicKeyB64),/Unexpected PoP research chain/);
});

test("a signed vote cannot be replayed at another block, round, epoch or chain",()=>{
  const f=fixture();
  const {proposal,votes}=f.bundle();
  assert.throws(()=>verifyCertificate(f.committee,{...proposal,blockHash:"0x"+"d".repeat(64)},votes),
                /proposal/);
  assert.throws(()=>verifyCertificate(f.committee,{...proposal,round:1},votes),
                /proposer|proposal/);
  const other=fixture();
  assert.throws(()=>verifyCertificate(other.committee,proposal,votes),/proposer/);
  const tamperedVote=structuredClone(votes);
  tamperedVote[0].signature=tamperedVote[1].signature;
  assert.throws(()=>verifyCertificate(f.committee,proposal,tamperedVote),/Forged/);
});

test("duplicate, unknown, and missing signers are refused",()=>{
  const f=fixture();
  const {proposal,votes}=f.bundle();
  assert.throws(()=>verifyCertificate(f.committee,proposal,[votes[0],votes[0],votes[1]]),
                /Duplicate/);
  assert.throws(()=>verifyCertificate(f.committee,proposal,
    [...votes.slice(0,2),{validatorId:"0x"+"e".repeat(64),signature:votes[2].signature}]),
    /Unadmitted/);
  assert.throws(()=>verifyCertificate(f.committee,proposal,"bad"),/Malformed/);
});

test("validator cannot double vote same height for conflicting position blocks",()=>{
  const f=fixture();
  const v=f.committee.validators[0],lock=new ResearchVoteLock();
  lock.accept(f.committee.epoch,5,0,v.id,"0x"+"b".repeat(64),"0x"+"a".repeat(64));
  lock.accept(f.committee.epoch,5,0,v.id,"0x"+"b".repeat(64),"0x"+"a".repeat(64));
  assert.throws(()=>lock.accept(f.committee.epoch,5,1,v.id,"0x"+"c".repeat(64),"0x"+"a".repeat(64)),
    /double-sign/);
  lock.accept(f.committee.epoch,6,0,v.id,"0x"+"c".repeat(64),"0x"+"b".repeat(64));
});

test("in-memory research signer lock does not reset at epoch transition",()=>{
  const f=fixture();
  const id=f.committee.validators[0].id, lock=new ResearchVoteLock();
  const first="0x"+"c".repeat(64), conflicting="0x"+"d".repeat(64);
  lock.accept(1,25,0,id,first,"0x"+"a".repeat(64));
  lock.accept(1,25,1,id,first,"0x"+"a".repeat(64)); // round changes do not reset same-block lock
  assert.throws(()=>lock.accept(2,25,0,id,conflicting,"0x"+"a".repeat(64)),
                /epoch transition/,"new epoch cannot bypass a same-height lock");
  assert.throws(()=>lock.accept(2,25,0,id,first,"0x"+"a".repeat(64)),
                /epoch transition/,"even same block requires reviewed epoch handoff");
  // Unrelated heights remain signable with a later epoch.
  lock.accept(2,26,0,id,conflicting,first);
  // A failed cross-epoch attempt must not overwrite the original commitment.
  assert.throws(()=>lock.accept(1,25,2,id,conflicting,"0x"+"a".repeat(64)),/double-sign/);
  lock.accept(1,25,2,id,first,"0x"+"a".repeat(64));
});

test("in-memory PoP height lock refuses same child with conflicting signed parent",()=>{
  const f=fixture();
  const id=f.committee.validators[0].id,lock=new ResearchVoteLock();
  const child="0x"+"c".repeat(64),parentA="0x"+"a".repeat(64);
  const parentB="0x"+"b".repeat(64);
  lock.accept(1,42,0,id,child,parentA);
  assert.throws(()=>lock.accept(1,42,1,id,child,parentB),
                /parent-link double-sign/);
  // Rejected attempts cannot replace the first commitment.
  lock.accept(1,42,2,id,child,parentA);
  assert.throws(()=>lock.accept(1,42,3,id,child),/previous block hash/);
  assert.throws(()=>lock.accept(1,42,3,id,child,child),/previous block hash/);
  assert.throws(()=>lock.accept(1,42,3,id,child,"invalid"),/previous block hash/);
  lock.accept(1,42,4,id,child,parentA);
});

test("in-memory research lock cannot be reset through public mutable state",()=>{
  const f=fixture();
  const id=f.committee.validators[0].id,lock=new ResearchVoteLock();
  const first="0x"+"c".repeat(64),other="0x"+"d".repeat(64);
  const parent="0x"+"a".repeat(64);
  lock.accept(1,51,0,id,first,parent);
  // A previously public Map could be cleared or replaced to permit a
  // conflicting second commitment at the same height.
  assert.equal(Object.hasOwn(lock,"commits"),false);
  assert.equal(Object.isFrozen(lock),true);
  assert.throws(()=>{lock.commits=new Map();},TypeError);
  assert.throws(()=>{lock.accept=()=>{};},TypeError);
  assert.throws(()=>lock.accept(1,51,1,id,other,parent),/double-sign/);
  // Failed tampering and a rejected conflict must preserve exact replay.
  lock.accept(1,51,2,id,first,parent);
});

test("no valid validator quorum with ambiguous unsigned position proof",()=>{
  const f=fixture();
  const noAnchor=structuredClone(f.registry);
  noAnchor.validators[0].anchorBlockHash="missing";
  assert.throws(()=>parseRegistry(noAnchor,f.gov.publicKeyB64),/position-block commitment/);
  assert.throws(()=>positionStamp("ORG_TEST","bad"),/safe integer/);
});
