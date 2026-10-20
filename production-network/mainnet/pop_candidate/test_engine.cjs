"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const crypto=require("node:crypto");
const {
  hash,signedMessage,parseRegistry,positionStamp,proposer,
  proposalFields,voteFields,verifyCertificate,ResearchVoteLock,TRUSTED_MODE,
  OWNER_OPERATOR_ID,OWNER_COMPANY_ID,OWNER_EVM_WALLET
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
    ownerWallet:OWNER_EVM_WALLET,operatorId:OWNER_OPERATOR_ID,
    validators:keys.map((k,i)=>{
      const operatorId=OWNER_OPERATOR_ID;
      const faultDomain="node"+i+".distinct-host.example";
      const companyId=OWNER_COMPANY_ID,positionSequence=i+1;
      const anchorBlockHash=hash(Buffer.from("privi-test-position-block-"+i));
      const positionHash=hash(Buffer.from(positionStamp(companyId,positionSequence)));
      const fields=[chainId,genesisHash,epoch,OWNER_EVM_WALLET,operatorId,faultDomain,companyId,
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

test("one Privi World Corp operator with four unique PoP signing positions yields three-of-four quorum",()=>{
  const f=fixture();
  assert.equal(f.committee.quorum,3);
  assert.equal(f.committee.validators.length,4);
  assert.equal(f.committee.epoch,1);
  assert.equal(f.committee.mode,TRUSTED_MODE);
  assert.equal(f.committee.validators.every(v=>v.stamp.startsWith("PoP:PRIVI_WORLD_CORP")),true);
  assert.equal(f.committee.validators.every(v=>v.operatorId===OWNER_OPERATOR_ID),true);
  assert.equal(new Set(f.committee.validators.map(v=>v.faultDomain)).size,4);
  assert.equal(f.committee.ownerWallet,OWNER_EVM_WALLET);
  assert.equal(f.committee.operatorId,OWNER_OPERATOR_ID);
  const {proposal,votes}=f.bundle();
  const proof=verifyCertificate(f.committee,proposal,votes);
  assert.equal(proof.valid,true);
  assert.equal(proof.signers,3);
  assert.equal(proof.productionConsensus,false);
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

test("reject unapproved, copied or forged PoP authority",()=>{
  const f=fixture();
  const invalid=structuredClone(f.registry);
  invalid.validators[0].admissionSignature=f.registry.validators[1].admissionSignature;
  assert.throws(()=>parseRegistry(invalid,f.gov.publicKeyB64),/admission signature/);
  const otherOperator=structuredClone(f.registry);
  otherOperator.validators[1].operatorId="OTHER_CORP";
  assert.throws(()=>parseRegistry(otherOperator,f.gov.publicKeyB64),/Only the disclosed/);
  const otherCompany=structuredClone(f.registry);
  otherCompany.validators[1].companyId="OTHER_CORP";
  assert.throws(()=>parseRegistry(otherCompany,f.gov.publicKeyB64),/Privi World Corp positions/);
  const foreignWallet=structuredClone(f.registry);
  foreignWallet.ownerWallet="0x"+"f".repeat(40);
  assert.throws(()=>parseRegistry(foreignWallet,f.gov.publicKeyB64),/sole proposed Privi founder wallet/);
  const otherRegisteredOperator=structuredClone(f.registry);
  otherRegisteredOperator.operatorId="OTHER_CORP";
  assert.throws(()=>parseRegistry(otherRegisteredOperator,f.gov.publicKeyB64),/ONE operator/);
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
  lock.accept(f.committee.epoch,5,0,v.id,"0x"+"b".repeat(64));
  lock.accept(f.committee.epoch,5,0,v.id,"0x"+"b".repeat(64));
  assert.throws(()=>lock.accept(f.committee.epoch,5,1,v.id,"0x"+"c".repeat(64)),
    /double-sign/);
  lock.accept(f.committee.epoch,6,0,v.id,"0x"+"c".repeat(64));
});

test("no valid validator quorum with ambiguous unsigned position proof",()=>{
  const f=fixture();
  const noAnchor=structuredClone(f.registry);
  noAnchor.validators[0].anchorBlockHash="missing";
  assert.throws(()=>parseRegistry(noAnchor,f.gov.publicKeyB64),/position-block commitment/);
  assert.throws(()=>positionStamp("ORG_TEST","bad"),/safe integer/);
});
