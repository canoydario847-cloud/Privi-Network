"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const crypto=require("node:crypto");
const {
  hash,positionStamp,parseRegistry,signedMessage,proposer,
  proposalFields,voteFields,TRUSTED_MODE
}=require("./engine.cjs");
const {verifyResearchCertificatePair}=require("./certificate_conflicts.cjs");

function makeKey() {
  const pair=crypto.generateKeyPairSync("ed25519");
  const der=pair.publicKey.export({type:"spki",format:"der"});
  return {id:hash(der),pub:der.toString("base64"),privateKey:pair.privateKey};
}
function sign(key,tag,fields) {
  return crypto.sign(null,signedMessage(tag,fields),key.privateKey)
    .toString("base64");
}
function fixture(n=4) {
  const gov=makeKey(),keys=Array.from({length:n},makeKey);
  const chainId="privi-pop-research-conflicts-v1";
  const genesisHash="0x"+"a".repeat(64);
  const epoch=4;
  const validators=keys.map((key,i)=>{
    const operatorId="OPERATOR_"+i,faultDomain="host"+i+".independent.example";
    const companyId="ORG_"+i,positionSequence=i+1;
    const anchorBlockHash=hash(Buffer.from("synthetic-position-proof-"+i));
    const positionHash=hash(Buffer.from(positionStamp(companyId,positionSequence)));
    return {
      id:key.id,keySpkiBase64:key.pub,operatorId,faultDomain,companyId,
      positionSequence,anchorBlockHash,positionHash,
      admissionSignature:sign(gov,"admit",[
        chainId,genesisHash,epoch,operatorId,faultDomain,companyId,
        positionSequence,key.id,anchorBlockHash
      ])
    };
  });
  const committee=parseRegistry({chainId,genesisHash,epoch,mode:TRUSTED_MODE,
                                  validators},gov.pub);
  const byKey=new Map(keys.map(k=>[k.id,k]));
  function certificate({height=10,round=0,parent="0x"+"b".repeat(64),
                        block="0x"+"c".repeat(64),indexes}={}) {
    const proposerId=proposer(committee,height,round);
    const fields=proposalFields(committee,height,round,parent,block,proposerId);
    const proposal={height,round,previousBlockHash:parent,blockHash:block,proposerId,
      signature:sign(byKey.get(proposerId),"propose",fields)};
    const selected=indexes||Array.from({length:committee.quorum},(_,i)=>i);
    const votes=selected.map(i=>{
      const id=committee.validators[i].id;
      return {validatorId:id,signature:sign(byKey.get(id),"commit",
                                           voteFields(fields,id))};
    });
    return {proposal,votes};
  }
  return {gov,keys,committee,certificate};
}
function verifyEvidenceSignature(committee,validatorId,tag,evidence) {
  const validator=committee.byId.get(validatorId);
  return crypto.verify(null,signedMessage(tag,evidence.voteFields),
                       validator.pub,Buffer.from(evidence.signatureB64,"base64"));
}

test("two genuine 3-of-4 quorum certificates for conflicting blocks expose two distinct double-sign keys",()=>{
  const f=fixture();
  const left=f.certificate({round:0,block:"0x"+"c".repeat(64),
                            indexes:[0,1,2]});
  const right=f.certificate({round:1,block:"0x"+"d".repeat(64),
                             indexes:[1,2,3]});
  const result=verifyResearchCertificatePair(f.committee,left,right);
  assert.equal(result.researchOnly,true);
  assert.equal(result.productionConsensus,false);
  assert.equal(result.finalityProven,false);
  assert.equal(result.slashingAuthorized,false);
  assert.equal(result.operatorMisconductProven,false);
  assert.equal(result.certificateSignaturesVerified,true);
  assert.equal(result.incompatibleCommitments,true);
  assert.equal(result.intersectingSignerCount,2);
  assert.equal(result.minimumGuaranteedIntersection,2);
  assert.equal(result.doubleSignEvidence.length,2);
  assert.equal(Object.isFrozen(result),true);
  assert.equal(Object.isFrozen(result.doubleSignEvidence),true);
  for(const evidence of result.doubleSignEvidence){
    assert.equal(verifyEvidenceSignature(f.committee,evidence.validatorId,
                                        "commit",evidence.first),true);
    assert.equal(verifyEvidenceSignature(f.committee,evidence.validatorId,
                                        "commit",evidence.second),true);
    assert.notDeepEqual(evidence.first.voteFields,evidence.second.voteFields);
    assert.equal(Object.isFrozen(evidence),true);
    assert.equal(Object.isFrozen(evidence.first.voteFields),true);
  }
});
test("two 5-of-7 quorums guarantee at least three verifiable common research signers",()=>{
  const f=fixture(7),left=f.certificate({indexes:[0,1,2,3,4]}),
    right=f.certificate({round:1,block:"0x"+"e".repeat(64),
                         indexes:[2,3,4,5,6]});
  const result=verifyResearchCertificatePair(f.committee,left,right);
  assert.equal(result.intersectingSignerCount,3);
  assert.equal(result.minimumGuaranteedIntersection,3);
  assert.equal(result.doubleSignEvidence.length,3);
  assert.equal(result.slashingAuthorized,false);
});
test("conflict evidence signer ordering is canonical despite hostile host locale",()=>{
  const f=fixture(7);
  const left=f.certificate({indexes:[0,1,2,3,4]});
  const right=f.certificate({round:1,block:"0x"+"d".repeat(64),
                             indexes:[2,3,4,5,6]});
  const expected=[2,3,4].map(i=>f.committee.validators[i].id).sort();
  const originalLocaleCompare=String.prototype.localeCompare;
  try {
    // Simulate hosts with incompatible collation: evidence verification must
    // not consult localeCompare for cryptographic signer fingerprint order.
    String.prototype.localeCompare=function(){
      throw Error("host locale must not affect PoP conflict evidence");
    };
    const first=verifyResearchCertificatePair(f.committee,left,right);
    const reversed=verifyResearchCertificatePair(f.committee,
      {...left,votes:[...left.votes].reverse()},
      {...right,votes:[...right.votes].reverse()});
    for(const report of [first,reversed]){
      assert.equal(report.incompatibleCommitments,true);
      assert.deepEqual(report.doubleSignEvidence.map(v=>v.validatorId),expected);
      assert.equal(report.minimumGuaranteedIntersection,3);
      assert.equal(report.slashingAuthorized,false);
      assert.equal(report.finalityProven,false);
      for(const evidence of report.doubleSignEvidence){
        assert.equal(verifyEvidenceSignature(f.committee,evidence.validatorId,
                                            "commit",evidence.first),true);
        assert.equal(verifyEvidenceSignature(f.committee,evidence.validatorId,
                                            "commit",evidence.second),true);
      }
    }
  } finally {
    String.prototype.localeCompare=originalLocaleCompare;
  }
});

test("same block hash with conflicting parent is cryptographic equivocation evidence",()=>{
  const f=fixture(),left=f.certificate({parent:"0x"+"a".repeat(64)}),
    right=f.certificate({round:1,parent:"0x"+"b".repeat(64)});
  const report=verifyResearchCertificatePair(f.committee,left,right);
  assert.equal(report.firstBlockHash,report.secondBlockHash);
  assert.notEqual(report.firstParentHash,report.secondParentHash);
  assert.equal(report.incompatibleCommitments,true);
  assert.equal(report.doubleSignEvidence.length,3);
});
test("same block and same parent in another round is not reported as equivocation",()=>{
  const f=fixture(),left=f.certificate({round:0}),
    right=f.certificate({round:1,indexes:[1,2,3]});
  const report=verifyResearchCertificatePair(f.committee,left,right);
  assert.equal(report.incompatibleCommitments,false);
  assert.equal(report.intersectingSignerCount,2);
  assert.equal(report.doubleSignEvidence.length,0);
  assert.equal(report.finalityProven,false);
});
test("same proposal and replayed votes are not false double-sign evidence",()=>{
  const f=fixture(),cert=f.certificate();
  const report=verifyResearchCertificatePair(f.committee,cert,cert);
  assert.equal(report.incompatibleCommitments,false);
  assert.equal(report.doubleSignEvidence.length,0);
});
test("certificate evidence refuses differently numbered heights, even if individually signed",()=>{
  const f=fixture(),left=f.certificate(),right=f.certificate({
    height:11,parent:"0x"+"c".repeat(64),block:"0x"+"d".repeat(64)});
  assert.throws(()=>verifyResearchCertificatePair(f.committee,left,right),
                /same height/);
});
test("signed certificates from a different governance registry or private keys cannot be compared",()=>{
  const f=fixture(),other=fixture();
  assert.throws(()=>verifyResearchCertificatePair(f.committee,
    f.certificate(),other.certificate()),/proposer|Forged|PoP/);
  assert.throws(()=>verifyResearchCertificatePair({...f.committee},
    f.certificate(),f.certificate()),/Unverified PoP committee/);
});
test("malformed or omitted certificate is rejected before issuing evidence",()=>{
  const f=fixture(),left=f.certificate();
  for(const invalid of [null,{},[],{proposal:null,votes:[]}]) {
    assert.throws(()=>verifyResearchCertificatePair(f.committee,left,invalid));
    assert.throws(()=>verifyResearchCertificatePair(f.committee,invalid,left));
  }
});
test("invalid quorum and repeated/unknown voters cannot produce evidence",()=>{
  const f=fixture(),left=f.certificate(),right=f.certificate({
    round:1,block:"0x"+"d".repeat(64)});
  right.votes.pop();
  assert.throws(()=>verifyResearchCertificatePair(f.committee,left,right),/quorum/);
  const repeated=f.certificate({round:1,block:"0x"+"d".repeat(64)});
  repeated.votes[1]=repeated.votes[0];
  assert.throws(()=>verifyResearchCertificatePair(f.committee,left,repeated),/Duplicate/);
  const rogue=f.certificate({round:1,block:"0x"+"d".repeat(64)});
  rogue.votes[0]={validatorId:"0x"+"f".repeat(64),signature:rogue.votes[0].signature};
  assert.throws(()=>verifyResearchCertificatePair(f.committee,left,rogue),/Unadmitted/);
});
test("tampered vote and proposal signatures fail closed, without claiming equivocation",()=>{
  const f=fixture(),left=f.certificate();
  const tampered=f.certificate({round:1,block:"0x"+"d".repeat(64)});
  tampered.votes[0].signature=left.votes[0].signature;
  assert.throws(()=>verifyResearchCertificatePair(f.committee,left,tampered),
    /Forged|wrong-epoch/);
  const forged=f.certificate({round:1,block:"0x"+"d".repeat(64)});
  forged.proposal.previousBlockHash="0x"+"a".repeat(64);
  assert.throws(()=>verifyResearchCertificatePair(f.committee,left,forged),
    /proposal|Unsigned/);
});


test("research conflict evidence uses authenticated snapshots, not changing Proxy reads",()=>{
  const f=fixture();
  const left=f.certificate({round:0,block:"0x"+"c".repeat(64),
                            indexes:[0,1,2]});
  const right=f.certificate({round:1,block:"0x"+"d".repeat(64),
                             indexes:[1,2,3]});
  let envelopeReads=0,proposalReads=0,voteReads=0;
  const shiftingProposal=new Proxy(right.proposal,{
    get(target,key,receiver){
      proposalReads++;
      if(key==="blockHash")return "0x"+"e".repeat(64);
      return Reflect.get(target,key,receiver);
    }
  });
  const shiftingVotes=new Proxy(right.votes,{
    get(target,key,receiver){
      voteReads++;
      if(key===Symbol.iterator)return function*(){};
      if(key==="0")return right.votes[0];
      return Reflect.get(target,key,receiver);
    }
  });
  const shiftingEnvelope=new Proxy({
    proposal:shiftingProposal,votes:shiftingVotes
  },{
    get(target,key,receiver){
      envelopeReads++;
      return Reflect.get(target,key,receiver);
    }
  });
  const report=verifyResearchCertificatePair(f.committee,left,shiftingEnvelope);
  assert.equal(envelopeReads,0,"envelope Proxy getters must not run");
  assert.equal(proposalReads,0,"proposal Proxy getters must not run");
  assert.equal(voteReads,0,"vote array Proxy getters must not run");
  assert.equal(report.incompatibleCommitments,true);
  assert.equal(report.secondBlockHash,right.proposal.blockHash);
  assert.equal(report.secondParentHash,right.proposal.previousBlockHash);
  assert.equal(report.doubleSignEvidence.length,2);
  for(const evidence of report.doubleSignEvidence){
    assert.equal(verifyEvidenceSignature(f.committee,evidence.validatorId,
                                        "commit",evidence.first),true);
    assert.equal(verifyEvidenceSignature(f.committee,evidence.validatorId,
                                        "commit",evidence.second),true);
  }
  assert.equal(report.finalityProven,false);
  assert.equal(report.slashingAuthorized,false);

  let getterCalls=0;
  const accessor={votes:right.votes};
  Object.defineProperty(accessor,"proposal",{enumerable:true,get(){
    getterCalls++;
    throw Error("untrusted certificate getter executed");
  }});
  assert.throws(()=>verifyResearchCertificatePair(f.committee,left,accessor),
                /Noncanonical PoP research certificate/);
  assert.equal(getterCalls,0);
});
