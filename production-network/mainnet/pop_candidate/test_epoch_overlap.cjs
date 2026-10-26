"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const crypto=require("node:crypto");
const {hash,signedMessage,parseRegistry,positionStamp,TRUSTED_MODE} = require("./engine.cjs");
const {analyzeEpochOverlap}=require("./epoch_overlap.cjs");

function makeSigner() {
  const pair=crypto.generateKeyPairSync("ed25519");
  const der=pair.publicKey.export({type:"spki",format:"der"});
  return {id:hash(der),pub:der.toString("base64"),privateKey:pair.privateKey};
}
function fixture(n) {
  const gov=makeSigner(),keys=Array.from({length:n},makeSigner);
  const chainId="privi-pop-research-overlap-v1",genesisHash="0x"+"a".repeat(64);
  function committee(signers,epoch,options={}) {
    const usedChain=options.chainId||chainId;
    const usedGenesis=options.genesisHash||genesisHash;
    const validators=signers.map((key,i)=>{
      const operatorId=(options.changeOperatorAt===i?"ALTERNATE_OPERATOR_":"OPERATOR_")+i;
      const faultDomain="host"+i+".separate-operator.example";
      const companyId="ORG_"+i,positionSequence=i+1;
      const anchorBlockHash=hash(Buffer.from("research-position-anchor-"+i));
      const positionHash=hash(Buffer.from(positionStamp(companyId,positionSequence)));
      const fields=[usedChain,usedGenesis,epoch,operatorId,faultDomain,
                    companyId,positionSequence,key.id,anchorBlockHash];
      return {id:key.id,keySpkiBase64:key.pub,operatorId,faultDomain,
              companyId,positionSequence,anchorBlockHash,positionHash,
              admissionSignature:crypto.sign(null,
                signedMessage("admit",fields),gov.privateKey).toString("base64")};
    });
    return parseRegistry({chainId:usedChain,genesisHash:usedGenesis,epoch,
      mode:TRUSTED_MODE,validators},gov.pub);
  }
  return {keys,committee};
}

test("4-of-4 stable identities meet necessary adjacent-epoch overlap, but cannot authorize handoff",()=>{
  const f=fixture(4),one=f.committee(f.keys,1),two=f.committee(f.keys,2);
  const result=analyzeEpochOverlap(one,two);
  assert.equal(result.minimalCommonQuorumSigners,2);
  assert.equal(result.assumedMaxFaultySharedSigners,1);
  assert.equal(result.unchangedSigners,4);
  assert.equal(result.overlapNecessaryCondition,true);
  assert.equal(result.permitsEpochTransition,false);
  assert.equal(result.productionConsensus,false);
  assert.equal(result.researchOnly,true);
  assert.equal(Object.isFrozen(result),true);
});

test("7-of-7 stable identities meet only a necessary 5-of-7 quorum intersection",()=>{
  const f=fixture(7),old=f.committee(f.keys,7),next=f.committee(f.keys,8);
  const result=analyzeEpochOverlap(old,next);
  assert.equal(old.quorum,5);
  assert.equal(next.quorum,5);
  assert.equal(result.minimalCommonQuorumSigners,3);
  assert.equal(result.assumedMaxFaultySharedSigners,2);
  assert.equal(result.permitsEpochTransition,false);
});

test("even one 4-validator signer replacement can destroy guaranteed honest cross-epoch intersection",()=>{
  const f=fixture(4),old=f.committee(f.keys,10);
  const rotated=[...f.keys];
  rotated[0]=makeSigner();
  const next=f.committee(rotated,11);
  assert.throws(()=>analyzeEpochOverlap(old,next),/unsafe cross-epoch quorum overlap/);
});

test("one of seven changed signers fails conservative overlap under f=2",()=>{
  const f=fixture(7),old=f.committee(f.keys,1);
  const next=f.committee([...f.keys.slice(0,6),makeSigner()],2);
  assert.throws(()=>analyzeEpochOverlap(old,next),/unsafe cross-epoch quorum overlap/);
});

test("identical key with newly claimed operator is not a stable shared identity",()=>{
  const f=fixture(4);
  const old=f.committee(f.keys,1),next=f.committee(f.keys,2,{changeOperatorAt:0});
  assert.throws(()=>analyzeEpochOverlap(old,next),/unsafe cross-epoch quorum overlap/);
});

test("four-to-seven committee expansion has no proven honest quorum intersection",()=>{
  const f=fixture(7),a=f.committee(f.keys.slice(0,4),1);
  const b=f.committee(f.keys,2);
  assert.throws(()=>analyzeEpochOverlap(a,b),/unsafe cross-epoch quorum overlap/);
});

test("rejects epoch jumps, rollback, unchanged epoch, and changed chain or genesis",()=>{
  const f=fixture(4),a=f.committee(f.keys,4);
  for (const epoch of [3,4,6,7]) {
    assert.throws(()=>analyzeEpochOverlap(a,f.committee(f.keys,epoch)),/one forward epoch/);
  }
  assert.throws(()=>analyzeEpochOverlap(a,f.committee(f.keys,5,{chainId:"privi-pop-research-elsewhere"})),
    /chain or genesis/);
  assert.throws(()=>analyzeEpochOverlap(a,f.committee(f.keys,5,{genesisHash:"0x"+"c".repeat(64)})),
    /chain or genesis/);
});

test("rejects forged admission wrappers and mutated member maps, even with copied keys",()=>{
  const f=fixture(4),a=f.committee(f.keys,1),b=f.committee(f.keys,2);
  assert.throws(()=>analyzeEpochOverlap(a,{...b}),/Unverified PoP committee/);
  assert.throws(()=>analyzeEpochOverlap({...a},b),/Unverified PoP committee/);
  const first=b.validators[0],original=b.byId.get(first.id);
  try {
    b.byId.set(first.id,{...first});
    assert.throws(()=>analyzeEpochOverlap(a,b),/membership changed/);
  } finally { b.byId.set(first.id,original); }
  assert.equal(analyzeEpochOverlap(a,b).overlapNecessaryCondition,true);
});

test("self-comparison is not an admitted epoch transition",()=>{
  const f=fixture(4),a=f.committee(f.keys,1);
  assert.throws(()=>analyzeEpochOverlap(a,a),/distinct admitted/);
});
