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
    const signer=options.governanceSigner||gov;
    const validators=signers.map((key,i)=>{
      const operatorId=(options.changeOperatorAt===i?"ALTERNATE_OPERATOR_":"OPERATOR_")+i;
      const faultDomain=(options.changeFaultDomainAt===i?"relocated-host":"host"+i)+".separate-operator.example";
      const companyId="ORG_"+i;
      const positionSequence=options.changePositionAt===i ? i+100 : i+1;
      const anchorBlockHash=hash(Buffer.from("research-position-anchor-"+i+
        (options.changeAnchorAt===i ? "-replacement" : "")));
      const positionHash=hash(Buffer.from(positionStamp(companyId,positionSequence)));
      const fields=[usedChain,usedGenesis,epoch,operatorId,faultDomain,
                    companyId,positionSequence,key.id,anchorBlockHash];
      return {id:key.id,keySpkiBase64:key.pub,operatorId,faultDomain,
              companyId,positionSequence,anchorBlockHash,positionHash,
              admissionSignature:crypto.sign(null,
                signedMessage("admit",fields),signer.privateKey).toString("base64")};
    });
    return parseRegistry({chainId:usedChain,genesisHash:usedGenesis,epoch,
      mode:TRUSTED_MODE,validators},signer.pub);
  }
  return {keys,committee,governance:gov};
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

test("governance-signed PoP position reassignment is not a stable epoch signer",()=>{
  const f=fixture(4),previous=f.committee(f.keys,12);
  // Keep the SAME four Ed25519 keys, operators, fault domains and governance
  // authority. Re-sign one different position for the next epoch: a valid
  // admission is not proof that the same participation identity persisted.
  const next=f.committee(f.keys,13,{changePositionAt:0});
  assert.equal(previous.validators.length,next.validators.length);
  assert.deepEqual(previous.validators.map(v=>v.id),next.validators.map(v=>v.id));
  assert.equal(previous.governanceKeyId,next.governanceKeyId);
  assert.notEqual(previous.validators.find(v=>v.stamp.includes("ORG_0")).stamp,
                  next.validators.find(v=>v.stamp.includes("ORG_0")).stamp);
  assert.throws(()=>analyzeEpochOverlap(previous,next),
    /unsafe cross-epoch quorum overlap/);
  assert.equal(analyzeEpochOverlap(previous,f.committee(f.keys,13)).permitsEpochTransition,false);
});

test("governance-signed change to a PoP anchor is not stable cross-epoch identity",()=>{
  const f=fixture(4),old=f.committee(f.keys,20);
  // Even valid fresh governance signatures cannot quietly replace the
  // position's anchored block commitment during a committee handoff.
  const changed=f.committee(f.keys,21,{changeAnchorAt:0});
  const original=old.validators.find(v=>v.stamp==="PoP:ORG_0:VALIDATOR/AUTH:000001");
  const updated=changed.validators.find(v=>v.stamp===original.stamp);
  assert.equal(old.governanceKeyId,changed.governanceKeyId);
  assert.equal(original.id,updated.id);
  assert.equal(original.positionHash,updated.positionHash);
  assert.notEqual(original.anchorBlockHash,updated.anchorBlockHash);
  assert.throws(()=>analyzeEpochOverlap(old,changed),
    /unsafe cross-epoch quorum overlap/);
  assert.equal(analyzeEpochOverlap(old,f.committee(f.keys,21)).permitsEpochTransition,false);
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


test("genuine signatures under different governance roots cannot authorize adjacent-epoch preflight",()=>{
  const f=fixture(4);
  const original=f.committee(f.keys,1);
  const replacementRoot=makeSigner();
  const replacement=f.committee(f.keys,2,{governanceSigner:replacementRoot});
  assert.notEqual(original.governanceKeyId,replacement.governanceKeyId);
  assert.equal(original.governanceKeyId,f.governance.id);
  assert.equal(replacement.governanceKeyId,replacementRoot.id);
  // Both committees have independently valid admissions and identical
  // validator signatures, but there is no signed governance handoff.
  assert.equal(original.validators.length,4);
  assert.equal(replacement.validators.length,4);
  assert.throws(()=>analyzeEpochOverlap(original,replacement),
    /governance authority change requires separately reviewed root handoff/);
  const unchangedRoot=f.committee(f.keys,2);
  assert.equal(analyzeEpochOverlap(original,unchangedRoot).permitsEpochTransition,false);
});

test("governance root cannot be overwritten on an admitted committee",()=>{
  const f=fixture(4);
  const old=f.committee(f.keys,1);
  assert.equal(Object.isFrozen(old),true);
  assert.throws(()=>{old.governanceKeyId="0x"+"f".repeat(64);},TypeError);
});

test("self-comparison is not an admitted epoch transition",()=>{
  const f=fixture(4),a=f.committee(f.keys,1);
  assert.throws(()=>analyzeEpochOverlap(a,a),/distinct admitted/);
});

test("31-member research committee loses guaranteed honest overlap after one signer rotation",()=>{
  // At the maximum admitted research size, Q=21 and f=10. Identical
  // committees guarantee 11 common quorum signatures; replacing one
  // signer reduces that lower bound to 10, which is NOT greater than f.
  // This is a necessary arithmetic screen, not production finality.
  const f=fixture(31),previous=f.committee(f.keys,40);
  const stable=f.committee(f.keys,41);
  assert.equal(previous.quorum,21);
  assert.equal(stable.quorum,21);
  const evidence=analyzeEpochOverlap(previous,stable);
  assert.equal(evidence.minimalCommonQuorumSigners,11);
  assert.equal(evidence.assumedMaxFaultySharedSigners,10);
  assert.equal(evidence.permitsEpochTransition,false);
  assert.equal(evidence.productionConsensus,false);

  const rotated=[...f.keys];
  rotated[30]=makeSigner();
  const replacement=f.committee(rotated,41);
  assert.equal(replacement.quorum,21);
  assert.throws(()=>analyzeEpochOverlap(previous,replacement),
    /unsafe cross-epoch quorum overlap/,
    "a 10-signer worst-case intersection cannot establish an honest signer");
});

test("30-member one-signer rotation passes only the necessary research overlap bound",()=>{
  // This neighboring committee size has Q=21 and f=9. One rotation
  // leaves at least 11 common signatures, which clears this arithmetic
  // prerequisite but still NEVER permits an epoch handoff or mainnet.
  const f=fixture(30),previous=f.committee(f.keys,70);
  const rotated=[...f.keys];
  rotated[29]=makeSigner();
  const next=f.committee(rotated,71);
  const evidence=analyzeEpochOverlap(previous,next);
  assert.equal(previous.quorum,21);
  assert.equal(next.quorum,21);
  assert.equal(evidence.unchangedSigners,29);
  assert.equal(evidence.minimalCommonQuorumSigners,11);
  assert.equal(evidence.assumedMaxFaultySharedSigners,9);
  assert.equal(evidence.permitsEpochTransition,false);
  assert.equal(evidence.productionConsensus,false);
});

test("30-to-31 research committee expansion preserves only a necessary overlap bound",()=>{
  // Q30=Q31=21. With 30 stable admitted identities, the union has 31
  // signers and the worst-case cross-epoch intersection is 21+21-31=11,
  // just above the larger committee's f=10 bound. This is NOT a safe
  // production handoff, independent-operator proof, or finality.
  const f=fixture(31);
  const previous=f.committee(f.keys.slice(0,30),80);
  const expanded=f.committee(f.keys,81);
  const evidence=analyzeEpochOverlap(previous,expanded);
  assert.equal(previous.quorum,21);
  assert.equal(expanded.quorum,21);
  assert.equal(evidence.unchangedSigners,30);
  assert.equal(evidence.minimalCommonQuorumSigners,11);
  assert.equal(evidence.assumedMaxFaultySharedSigners,10);
  assert.equal(evidence.permitsEpochTransition,false);
  assert.equal(evidence.productionConsensus,false);
  assert.equal(evidence.researchOnly,true);

  // Replacing one of the 30 common signers during the same expansion
  // reduces the guaranteed intersection to 10: not strictly greater
  // than the conservative f=10 Byzantine bound, so reject.
  const replaced=[...f.keys.slice(0,29),makeSigner(),f.keys[30]];
  const unsafe=f.committee(replaced,81);
  assert.throws(()=>analyzeEpochOverlap(previous,unsafe),
    /unsafe cross-epoch quorum overlap/);
});

test("31-to-30 research committee contraction retains only necessary overlap",()=>{
  // Q31=Q30=21, with f=max(10,9)=10. Dropping one of 31 signers
  // leaves 30 stable identities and a 31-member union, so two quorums
  // share at least 21+21-31=11 signers. This does NOT authorize handoff.
  const f=fixture(31);
  const previous=f.committee(f.keys,90);
  const contracted=f.committee(f.keys.slice(0,30),91);
  const evidence=analyzeEpochOverlap(previous,contracted);
  assert.equal(previous.quorum,21);
  assert.equal(contracted.quorum,21);
  assert.equal(evidence.priorValidators,31);
  assert.equal(evidence.nextValidators,30);
  assert.equal(evidence.unchangedSigners,30);
  assert.equal(evidence.minimalCommonQuorumSigners,11);
  assert.equal(evidence.assumedMaxFaultySharedSigners,10);
  assert.equal(evidence.permitsEpochTransition,false);
  assert.equal(evidence.productionConsensus,false);
  assert.equal(evidence.researchOnly,true);

  // Dropping one signer AND replacing another leaves only 29 stable
  // identities in a 32-member union: guaranteed intersection 10,
  // not strictly above the conservative Byzantine bound f=10.
  const replaced=[...f.keys.slice(0,29),makeSigner()];
  const unsafe=f.committee(replaced,91);
  assert.throws(()=>analyzeEpochOverlap(previous,unsafe),
    /unsafe cross-epoch quorum overlap/);
});

test("four-to-five research committee expansion preserves only a necessary overlap bound",()=>{
  // Q4=3 and Q5=4. Retaining the four admitted signing identities gives
  // a five-signer union and at least 3+4-5=2 common quorum signers,
  // above the conservative max Byzantine bound f=1.
  const f=fixture(5);
  const previous=f.committee(f.keys.slice(0,4),100);
  const expanded=f.committee(f.keys,101);
  const evidence=analyzeEpochOverlap(previous,expanded);
  assert.equal(previous.quorum,3);
  assert.equal(expanded.quorum,4);
  assert.equal(evidence.unchangedSigners,4);
  assert.equal(evidence.minimalCommonQuorumSigners,2);
  assert.equal(evidence.assumedMaxFaultySharedSigners,1);
  assert.equal(evidence.overlapNecessaryCondition,true);
  assert.equal(evidence.permitsEpochTransition,false);
  assert.equal(evidence.productionConsensus,false);
  assert.equal(evidence.researchOnly,true);

  // Replacing one old signer while adding two new ones leaves only three
  // stable signers in a six-signer union: guaranteed intersection is one,
  // which cannot prove an honest signer against f=1.
  const replaced=[...f.keys.slice(0,3),makeSigner(),f.keys[4]];
  const unsafe=f.committee(replaced,101);
  assert.throws(()=>analyzeEpochOverlap(previous,unsafe),
    /unsafe cross-epoch quorum overlap/);
});

test("five-to-four research committee contraction preserves only a necessary overlap bound",()=>{
  // Q5=4, Q4=3, f=max(1,1)=1. Dropping one signer retains four
  // identities in a five-signer union, so any two quorums share at least
  // 4+3-5=2 signers. This is only a necessary research preflight.
  const f=fixture(5);
  const previous=f.committee(f.keys,110);
  const contracted=f.committee(f.keys.slice(0,4),111);
  const evidence=analyzeEpochOverlap(previous,contracted);
  assert.equal(previous.quorum,4);
  assert.equal(contracted.quorum,3);
  assert.equal(evidence.priorValidators,5);
  assert.equal(evidence.nextValidators,4);
  assert.equal(evidence.unchangedSigners,4);
  assert.equal(evidence.minimalCommonQuorumSigners,2);
  assert.equal(evidence.assumedMaxFaultySharedSigners,1);
  assert.equal(evidence.overlapNecessaryCondition,true);
  assert.equal(evidence.permitsEpochTransition,false);
  assert.equal(evidence.productionConsensus,false);
  assert.equal(evidence.researchOnly,true);

  // Dropping one signer and replacing another leaves three stable
  // identities in a six-signer union; the guaranteed intersection is
  // 4+3-6=1, which cannot exceed the conservative f=1 bound.
  const replaced=[...f.keys.slice(0,3),makeSigner()];
  const unsafe=f.committee(replaced,111);
  assert.throws(()=>analyzeEpochOverlap(previous,unsafe),
    /unsafe cross-epoch quorum overlap/);
});

// A governance-signed domain change is not independent evidence of continuity:
// even the same Ed25519 key and operator must not count as an unchanged
// cross-epoch identity when its claimed failure domain changes.
test("governance-signed fault-domain reassignment must not count as stable epoch overlap",()=>{
  const f=fixture(4);
  const previous=f.committee(f.keys,120);
  const relocated=f.committee(f.keys,121,{changeFaultDomainAt:0});
  assert.equal(previous.governanceKeyId,relocated.governanceKeyId);
  assert.deepEqual(previous.validators.map(v=>v.id),relocated.validators.map(v=>v.id));
  const before=previous.validators.find(v=>v.operatorId==="OPERATOR_0");
  const after=relocated.validators.find(v=>v.operatorId==="OPERATOR_0");
  assert.notEqual(before.faultDomain,after.faultDomain);
  assert.throws(()=>analyzeEpochOverlap(previous,relocated),
    /unsafe cross-epoch quorum overlap/);
  const unchanged=f.committee(f.keys,121);
  const evidence=analyzeEpochOverlap(previous,unchanged);
  assert.equal(evidence.overlapNecessaryCondition,true);
  assert.equal(evidence.permitsEpochTransition,false);
  assert.equal(evidence.productionConsensus,false);
});
