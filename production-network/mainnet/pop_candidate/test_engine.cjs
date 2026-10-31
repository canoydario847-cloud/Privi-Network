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

test("noncanonical SPKI aliases cannot duplicate a research validator signing key",()=>{
  const f=fixture(4),registry=structuredClone(f.registry);
  const original=Buffer.from(registry.validators[0].keySpkiBase64,"base64");
  const aliased=Buffer.concat([original,Buffer.from([0x00])]);
  // Node accepts this DER input as the same Ed25519 key despite trailing data.
  assert.equal(crypto.createPublicKey({key:aliased,format:"der",type:"spki"})
    .export({type:"spki",format:"der"}).equals(original),true);
  const second=registry.validators[1];
  second.keySpkiBase64=aliased.toString("base64");
  second.id=hash(aliased);
  const fields=[registry.chainId,registry.genesisHash,registry.epoch,
    second.operatorId,second.faultDomain,second.companyId,
    second.positionSequence,second.id,second.anchorBlockHash];
  second.admissionSignature=sign(f.gov,"admit",fields);
  assert.throws(()=>parseRegistry(registry,f.gov.publicKeyB64),
    /Noncanonical Ed25519 SPKI encoding/);
  const aliasedGovernance=Buffer.concat([
    Buffer.from(f.gov.publicKeyB64,"base64"),Buffer.from([0x00])]).toString("base64");
  assert.throws(()=>parseRegistry(f.registry,aliasedGovernance),
    /Noncanonical Ed25519 SPKI encoding/);
  assert.equal(parseRegistry(f.registry,f.gov.publicKeyB64).quorum,3);
});

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

test("research proposal verifier rejects getters and unsigned metadata before field reads",()=>{
  const f=fixture(),{proposal,votes}=f.bundle();
  let getterReads=0;
  const accessor={...proposal};
  Object.defineProperty(accessor,"height",{
    enumerable:true,get(){getterReads++;return proposal.height;}
  });
  const inherited=Object.create({height:proposal.height});
  Object.assign(inherited,proposal);
  delete inherited.height;
  const hidden={...proposal};
  Object.defineProperty(hidden,"finalized",{value:true,enumerable:false});
  const symbolic={...proposal};
  symbolic[Symbol("productionConsensus")]=true;
  const nonenumerable={...proposal};
  Object.defineProperty(nonenumerable,"signature",{
    value:proposal.signature,enumerable:false
  });
  for(const untrusted of [
    accessor,inherited,hidden,symbolic,nonenumerable,
    Object.assign(Object.create(null),proposal)
  ]){
    assert.throws(()=>verifyCertificate(f.committee,untrusted,votes),
                  /plain own canonical data fields/);
  }
  assert.equal(getterReads,0,"proposal getter must never execute");
  assert.equal(verifyCertificate(f.committee,proposal,votes).valid,true);
});

test("research certificate rejects unsigned vote metadata and getters before field reads",()=>{
  const f=fixture(),{proposal,votes}=f.bundle();
  let getterReads=0;
  const getter={...votes[0]};
  Object.defineProperty(getter,"signature",{
    enumerable:true,get(){getterReads++;return votes[0].signature;}
  });
  const inherited=Object.assign(Object.create({validatorId:votes[0].validatorId}),votes[0]);
  delete inherited.validatorId;
  const hidden={...votes[0]};
  Object.defineProperty(hidden,"finalized",{value:true,enumerable:false});
  const symbolic={...votes[0]};
  symbolic[Symbol("productionConsensus")]=true;
  const extra={...votes[0],finalized:true};
  const nonenumerable={...votes[0]};
  Object.defineProperty(nonenumerable,"validatorId",{
    value:votes[0].validatorId,enumerable:false
  });
  const untrusted=[getter,inherited,hidden,symbolic,extra,nonenumerable,
    Object.assign(Object.create(null),votes[0]),
    {...votes[0],researchOnly:false}];
  for(const vote of untrusted){
    assert.throws(()=>verifyCertificate(f.committee,proposal,[vote,...votes.slice(1)]),
                  /plain own canonical data fields/);
  }
  assert.equal(getterReads,0,"vote getter must never execute");
  // The durable research signer emits this non-production marker, which is
  // allowed only as the literal own enumerable value true.
  const marked={...votes[0],researchOnly:true};
  assert.equal(verifyCertificate(f.committee,proposal,[marked,...votes.slice(1)]).valid,true);
  assert.equal(verifyCertificate(f.committee,proposal,votes).productionConsensus,false);
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

test("research proposer seed is domain-separated and bound to the signed roster",()=>{
  const first=fixture(7),second=fixture(7);
  const ordered=first.committee;
  // Registry JSON ordering is not consensus ordering: admission sorts keys.
  const reversed=parseRegistry({
    ...first.registry,validators:[...first.registry.validators].reverse()
  },first.gov.publicKeyB64);
  function electionSeed(c,height,round){
    return hash(Buffer.from(JSON.stringify([
      "Privi/PoP/Research/ProposerElection/v2",
      c.chainId,c.genesisHash,c.epoch,c.governanceKeyId,
      c.validators.map(v=>v.id),height,round
    ]),"utf8"));
  }
  const height=63;
  assert.equal(electionSeed(ordered,height,0),electionSeed(reversed,height,0));
  // The same chain, genesis, epoch, height and round must not produce the
  // same election seed when a different roster/governance root was admitted.
  assert.equal(ordered.chainId,second.committee.chainId);
  assert.equal(ordered.genesisHash,second.committee.genesisHash);
  assert.equal(ordered.epoch,second.committee.epoch);
  assert.notEqual(electionSeed(ordered,height,0),
                  electionSeed(second.committee,height,0));
  for(const c of [ordered,reversed,second.committee]){
    for(const round of [0,1,2,17]){
      const slot=Number(BigInt(electionSeed(c,height,round))%
                        BigInt(c.validators.length));
      assert.equal(proposer(c,height,round),c.validators[slot].id);
    }
  }
  for(const round of [0,1,2,17]){
    assert.equal(proposer(ordered,height,round),proposer(reversed,height,round));
  }
});

test("research proposer roster ordering is ASCII-canonical, not locale-dependent",()=>{
  const f=fixture(7);
  const expected=f.registry.validators.map(v=>v.id).sort();
  const originalLocaleCompare=String.prototype.localeCompare;
  try {
    // Simulate hosts with incompatible ICU collation. A consensus seed must
    // never depend on host locale, even for otherwise valid signer keys.
    String.prototype.localeCompare=function(){
      throw Error("locale-dependent comparator invoked");
    };
    const reordered=parseRegistry({
      ...f.registry,validators:[...f.registry.validators].reverse()
    },f.gov.publicKeyB64);
    assert.deepEqual(reordered.validators.map(v=>v.id),expected);
    for(const round of [0,1,3,17]){
      assert.equal(proposer(reordered,44,round),proposer(f.committee,44,round));
    }
  } finally {
    String.prototype.localeCompare=originalLocaleCompare;
  }
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

test("two valid governance admissions cannot reuse one PoP position as two quorum votes",()=>{
  const f=fixture(4),registry=structuredClone(f.registry);
  const first=registry.validators[0],second=registry.validators[1];
  // Keep distinct signing keys, operators, and fault domains. The only
  // collision is the independently meaningful PoP position identity.
  assert.notEqual(first.id,second.id);
  assert.notEqual(first.operatorId,second.operatorId);
  assert.notEqual(first.faultDomain,second.faultDomain);
  second.companyId=first.companyId;
  second.positionSequence=first.positionSequence;
  second.positionHash=hash(Buffer.from(
    positionStamp(second.companyId,second.positionSequence),"utf8"));
  const admission=[registry.chainId,registry.genesisHash,registry.epoch,
    second.operatorId,second.faultDomain,second.companyId,
    second.positionSequence,second.id,second.anchorBlockHash];
  // A real signature under the authorized governance key is not sufficient
  // to count the same position twice toward a research quorum.
  second.admissionSignature=sign(f.gov,"admit",admission);
  assert.throws(()=>parseRegistry(registry,f.gov.publicKeyB64),
    /Duplicated validator, operator, failure domain, or PoP position/);
  assert.equal(parseRegistry(f.registry,f.gov.publicKeyB64).quorum,3);
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

test("research certificate refuses vote array metadata and index accessors",()=>{
  const f=fixture(),{proposal,votes}=f.bundle();
  let getterReads=0;
  const decorated=[...votes];
  decorated.finalized=true;
  const hidden=[...votes];
  Object.defineProperty(hidden,"productionConsensus",{value:true});
  const symbolic=[...votes];
  symbolic[Symbol("finalized")]=true;
  const accessor=[...votes];
  Object.defineProperty(accessor,"0",{
    enumerable:true,configurable:true,
    get(){getterReads++;return votes[0];}
  });
  const sparse=[...votes];
  delete sparse[1];
  const inherited=[...votes];
  Object.setPrototypeOf(inherited,Object.create(Array.prototype));
  for(const untrusted of [decorated,hidden,symbolic,accessor,sparse,inherited]){
    assert.throws(()=>verifyCertificate(f.committee,proposal,untrusted),
                  /dense plain array|Malformed PoP vote certificate/);
  }
  assert.equal(getterReads,0,"index accessor must not execute");
  const proof=verifyCertificate(f.committee,proposal,[...votes]);
  assert.equal(proof.valid,true);
  assert.equal(proof.finalized,false);
  assert.equal(proof.productionConsensus,false);
});

test("governance admission rejects unsigned roster metadata and accessor traps",()=>{
  const f=fixture();
  const extra=structuredClone(f.registry);
  extra.productionFinalized=true;
  assert.throws(()=>parseRegistry(extra,f.gov.publicKeyB64),/Noncanonical PoP registry/);
  const hidden=structuredClone(f.registry);
  Object.defineProperty(hidden,"live",{value:true});
  assert.throws(()=>parseRegistry(hidden,f.gov.publicKeyB64),/Noncanonical PoP registry/);
  const symbol=structuredClone(f.registry);
  symbol[Symbol("finality")]=true;
  assert.throws(()=>parseRegistry(symbol,f.gov.publicKeyB64),/Noncanonical PoP registry/);
  const inherited=Object.assign(Object.create({productionFinalized:true}),f.registry);
  assert.throws(()=>parseRegistry(inherited,f.gov.publicKeyB64),/Noncanonical PoP registry/);
  const getter=structuredClone(f.registry);
  let registryGetterReads=0;
  Object.defineProperty(getter,"validators",{enumerable:true,get(){
    registryGetterReads++;
    throw Error("untrusted registry getter executed");
  }});
  assert.throws(()=>parseRegistry(getter,f.gov.publicKeyB64),/Noncanonical PoP registry/);
  assert.equal(registryGetterReads,0);
  const memberExtra=structuredClone(f.registry);
  memberExtra.validators[0].productionFinalized=true;
  assert.throws(()=>parseRegistry(memberExtra,f.gov.publicKeyB64),/Noncanonical PoP validator/);
  const memberGetter=structuredClone(f.registry);
  let validatorGetterReads=0;
  Object.defineProperty(memberGetter.validators[0],"operatorId",{enumerable:true,get(){
    validatorGetterReads++;
    throw Error("untrusted validator getter executed");
  }});
  assert.throws(()=>parseRegistry(memberGetter,f.gov.publicKeyB64),/Noncanonical PoP validator/);
  assert.equal(validatorGetterReads,0);
  assert.equal(parseRegistry(structuredClone(f.registry),f.gov.publicKeyB64).quorum,3);
});

test("governance admission rejects decorated, sparse and accessor validator arrays",()=>{
  const f=fixture(4);
  let getterReads=0;
  const extra=[...f.registry.validators];
  extra.productionFinalized=true;
  const hidden=[...f.registry.validators];
  Object.defineProperty(hidden,"finality",{value:true});
  const symbolic=[...f.registry.validators];
  symbolic[Symbol("mainnet")]=true;
  const accessor=[...f.registry.validators];
  Object.defineProperty(accessor,"0",{
    enumerable:true,configurable:true,
    get(){getterReads++;throw Error("untrusted validator index getter executed");}
  });
  const sparse=[...f.registry.validators];
  delete sparse[1];
  const inherited=[...f.registry.validators];
  Object.setPrototypeOf(inherited,Object.create(Array.prototype));
  for(const validators of [extra,hidden,symbolic,accessor,sparse,inherited]){
    assert.throws(()=>parseRegistry({...f.registry,validators},f.gov.publicKeyB64),
      /Noncanonical PoP validator roster/);
  }
  assert.equal(getterReads,0,"admission must not read an untrusted index getter");
  assert.equal(parseRegistry(f.registry,f.gov.publicKeyB64).quorum,3);
});

test("research quorum intersection bound holds across admitted committee sizes",()=>{
  // These are arithmetic safety prerequisites for the RESEARCH certificate
  // format, not evidence of honest operators or production BFT finality.
  for(const count of [4,5,6,7,10,31]){
    const f=fixture(count);
    const quorum=Math.floor(2*count/3)+1;
    const assumedByzantine=Math.floor((count-1)/3);
    assert.equal(f.committee.quorum,quorum);
    assert.ok(2*quorum-count>assumedByzantine,
      "two research quorums must intersect in more than f signer IDs");
    const {proposal,votes}=f.bundle(13,0,undefined,undefined,count);
    const first=votes.slice(0,quorum);
    const last=votes.slice(-quorum);
    const firstProof=verifyCertificate(f.committee,proposal,first);
    const lastProof=verifyCertificate(f.committee,proposal,last);
    assert.equal(firstProof.signers,quorum);
    assert.equal(lastProof.signers,quorum);
    const intersection=first.filter(v=>
      last.some(other=>other.validatorId===v.validatorId)).length;
    assert.equal(intersection,2*quorum-count,
      "extremal quorums must realize the mathematical intersection bound");
    assert.throws(()=>
      verifyCertificate(f.committee,proposal,votes.slice(0,quorum-1)),
      /quorum/,"one fewer vote must not form a certificate");
    assert.equal(firstProof.finalized,false);
    assert.equal(lastProof.productionConsensus,false);
  }
});

test("validly signed admissions cannot reuse an operator or fault domain",()=>{
  const f=fixture(4);
  for(const collision of ["operatorId","faultDomain"]){
    const registry=structuredClone(f.registry);
    const first=registry.validators[0],second=registry.validators[1];
    // Both admissions remain genuinely signed by the governance root.
    // A duplicate organizational or failure-domain identity cannot count
    // as two independent research votes merely by changing the signature.
    second[collision]=first[collision];
    const fields=[registry.chainId,registry.genesisHash,registry.epoch,
      second.operatorId,second.faultDomain,second.companyId,
      second.positionSequence,second.id,second.anchorBlockHash];
    second.admissionSignature=sign(f.gov,"admit",fields);
    assert.throws(()=>parseRegistry(registry,f.gov.publicKeyB64),
      /Duplicated validator, operator, failure domain, or PoP position/);
  }
  assert.equal(parseRegistry(f.registry,f.gov.publicKeyB64).quorum,3);
});

test("research governance admissions cannot replay across signed chain, genesis or epoch",()=>{
  const f=fixture();
  // Each replacement is syntactically valid; only the governance signature
  // binds it to the original chain/genesis/epoch. No mainnet authority implied.
  const changes=[
    ["chainId","privi-pop-research-foreign-v1"],
    ["genesisHash","0x"+"e".repeat(64)],
    ["epoch",f.registry.epoch+1]
  ];
  for(const [field,replacement] of changes){
    const altered=structuredClone(f.registry);
    altered[field]=replacement;
    assert.throws(()=>parseRegistry(altered,f.gov.publicKeyB64),
      /admission signature invalid or absent/,
      "signed admission must not replay after changing "+field);
  }
  assert.equal(parseRegistry(f.registry,f.gov.publicKeyB64).quorum,3);
});

test("research signer map overrides cannot redirect certificate verification",()=>{
  const f=fixture(4),{proposal,votes}=f.bundle();
  const map=f.committee.byId;
  let intercepted=0;
  // A frozen committee does not freeze the mutable Map it contains.
  // Instance methods and accessors must not influence authenticated lookup.
  Object.defineProperties(map,{
    get:{value(){intercepted++;throw Error("untrusted map get executed");}},
    has:{value(){intercepted++;throw Error("untrusted map has executed");}},
    size:{get(){intercepted++;throw Error("untrusted map size executed");}}
  });
  assert.equal(proposer(f.committee,proposal.height,proposal.round),
               proposal.proposerId);
  assert.equal(verifyCertificate(f.committee,proposal,votes).valid,true);
  assert.equal(intercepted,0,"shadowed map methods must never execute");
  const member=f.committee.validators[0];
  const original=Map.prototype.get.call(map,member.id);
  try {
    Map.prototype.set.call(map,member.id,{...original});
    assert.throws(()=>verifyCertificate(f.committee,proposal,votes),
                  /membership changed/,"shadowed get cannot conceal altered membership");
  } finally {
    Map.prototype.set.call(map,member.id,original);
  }
  assert.equal(verifyCertificate(f.committee,proposal,votes).finalized,false);
  assert.equal(intercepted,0);
});

test("research quorum cannot be inflated by changing proxy vote identities",()=>{
  const f=fixture(4),{proposal,votes}=f.bundle();
  const signed=votes[0];
  const aliases=f.committee.validators.map(v=>v.id)
    .filter(id=>id!==signed.validatorId);
  assert.equal(aliases.length,3);
  // Each proxy presents the genuine signer's ID to the key lookup and
  // signature verifier, but three distinct IDs to duplicate detection.
  // Old code reread validatorId four times and accepted a forged quorum.
  const forgedVotes=aliases.map(alias=>{
    let reads=0;
    return new Proxy({...signed},{
      get(target,key,receiver){
        if(key==="validatorId"){
          reads++;
          return (reads===1 || reads===3) ? signed.validatorId : alias;
        }
        return Reflect.get(target,key,receiver);
      }
    });
  });
  assert.throws(()=>verifyCertificate(f.committee,proposal,forgedVotes),
    /Duplicate PoP voter|Forged or wrong-epoch\/chain\/round PoP vote/,
    "one Ed25519 signature cannot count as three independent voters");
  const authentic=verifyCertificate(f.committee,proposal,votes);
  assert.equal(authentic.signers,3);
  assert.equal(authentic.finalized,false);
  assert.equal(authentic.productionConsensus,false);
});

test("research certificate metadata cannot change after proposal signature verification",()=>{
  const f=fixture(),{proposal,votes}=f.bundle();
  const alternate={
    height:proposal.height+1,round:proposal.round+1,
    previousBlockHash:"0x"+"d".repeat(64),
    blockHash:"0x"+"e".repeat(64)
  };
  const reads=new Map();
  // Proxy descriptors remain canonical data descriptors; the getter trap
  // supplies valid signed values once and different values on later reads.
  const shifting=new Proxy({...proposal},{
    get(target,key,receiver){
      if(Object.hasOwn(alternate,key)){
        const count=reads.get(key)||0;
        reads.set(key,count+1);
        return count===0 ? Reflect.get(target,key,receiver) : alternate[key];
      }
      return Reflect.get(target,key,receiver);
    }
  });
  const proof=verifyCertificate(f.committee,shifting,votes);
  assert.equal(proof.valid,true);
  for(const key of Object.keys(alternate)){
    assert.equal(proof[key],proposal[key],
      "certificate "+key+" must be bound to signed proposal fields");
    assert.equal(reads.get(key),1,
      "verified proposal "+key+" must not be reread from untrusted input");
  }
  assert.equal(proof.finalized,false);
  assert.equal(proof.productionConsensus,false);
});
