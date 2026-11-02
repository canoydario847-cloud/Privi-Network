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

test("research proposal verifier uses descriptor snapshots, not Proxy get traps",()=>{
  const f=fixture(),{proposal,votes}=f.bundle();
  let reads=0;
  const hostile=new Proxy({...proposal},{
    get(_target,key){
      reads++;
      throw Error("unsigned proposal read: "+String(key));
    }
  });
  const proof=verifyCertificate(f.committee,hostile,votes);
  assert.equal(proof.valid,true);
  assert.equal(proof.height,proposal.height);
  assert.equal(proof.blockHash,proposal.blockHash);
  assert.equal(proof.previousBlockHash,proposal.previousBlockHash);
  assert.equal(proof.productionConsensus,false);
  assert.equal(proof.finalized,false);
  assert.equal(reads,0,"untrusted proposal getters must not execute");
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

test("research vote marker cannot be hidden from ownKeys by a Proxy",()=>{
  const f=fixture(),{proposal,votes}=f.bundle();
  // A configurable own marker may be omitted by a Proxy ownKeys trap even
  // though getOwnPropertyDescriptor still exposes its declared value.
  for(const marker of [false,true]){
    const vote={...votes[0],researchOnly:marker};
    let getterReads=0;
    const hostile=new Proxy(vote,{
      ownKeys(){return ["validatorId","signature"];},
      get(){getterReads++;throw Error("unsigned vote getter invoked");}
    });
    assert.deepEqual(Reflect.ownKeys(hostile),["validatorId","signature"]);
    assert.equal(Object.getOwnPropertyDescriptor(hostile,"researchOnly").value,marker);
    assert.throws(()=>verifyCertificate(f.committee,proposal,
      [hostile,...votes.slice(1)]),/plain own canonical data fields/);
    assert.equal(getterReads,0);
  }
  const allowed={...votes[0],researchOnly:true};
  assert.equal(verifyCertificate(f.committee,proposal,
    [allowed,...votes.slice(1)]).valid,true);
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

test("research proposer election ignores poisoned inherited Array.toJSON",()=>{
  const f=fixture(7),height=63;
  const rounds=[0,1,2,3,4,5,6,7,17,31];
  const expected=rounds.map(round=>proposer(f.committee,height,round));
  const original=Object.getOwnPropertyDescriptor(Array.prototype,"toJSON");
  try {
    Object.defineProperty(Array.prototype,"toJSON",{
      configurable:true,writable:true,
      value(){return ["attacker-controlled-election-roster"];}
    });
    for(let i=0;i<rounds.length;i++){
      const round=rounds[i];
      assert.equal(proposer(f.committee,height,round),expected[i],
        "research proposer must be bound to canonical admitted roster");
      const {proposal,votes}=f.bundle(height,round);
      const proof=verifyCertificate(f.committee,proposal,votes);
      assert.equal(proof.valid,true);
      assert.equal(proof.finalized,false);
      assert.equal(proof.productionConsensus,false);
    }
  } finally {
    if(original)Object.defineProperty(Array.prototype,"toJSON",original);
    else delete Array.prototype.toJSON;
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

test("research quorum uses declared vote descriptors, never Proxy iteration",()=>{
  const f=fixture(4),{proposal,votes}=f.bundle();
  let iteratorReads=0;
  // A Proxy of [] has a canonical zero-length array descriptor, but its
  // get trap can invent a quorum through Symbol.iterator. The declared
  // certificate must remain empty regardless of those synthetic votes.
  const phantom=new Proxy([],{
    get(target,key,receiver){
      if(key===Symbol.iterator){
        iteratorReads++;
        return function*(){yield* votes;};
      }
      return Reflect.get(target,key,receiver);
    }
  });
  assert.throws(()=>verifyCertificate(f.committee,proposal,phantom),
    /Insufficient independently signed PoP quorum/);
  assert.equal(iteratorReads,0,"untrusted vote iterator must not execute");

  // Index get traps must not replace the validated own data descriptors
  // with different votes after structural checks have passed.
  const altered=[...votes];
  altered[0]={validatorId:"0x"+"f".repeat(64),signature:votes[0].signature};
  let indexReads=0;
  const swapped=new Proxy(altered,{
    get(target,key,receiver){
      if(key==="0"){indexReads++;return votes[0];}
      return Reflect.get(target,key,receiver);
    }
  });
  assert.throws(()=>verifyCertificate(f.committee,proposal,swapped),
    /Unadmitted PoP voter/);
  assert.equal(indexReads,0,"untrusted vote index getter must not execute");
  const valid=verifyCertificate(f.committee,proposal,[...votes]);
  assert.equal(valid.signers,3);
  assert.equal(valid.finalized,false);
  assert.equal(valid.productionConsensus,false);
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
  // Proxy descriptors remain canonical data descriptors. No getter trap
  // should execute: verified fields come from the one descriptor snapshot.
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
    assert.equal(reads.get(key)||0,0,
      "verified proposal "+key+" must not invoke untrusted property getters");
  }
  assert.equal(proof.finalized,false);
  assert.equal(proof.productionConsensus,false);
});

test("research admission uses validator descriptors, not Proxy iteration or index reads",()=>{
  const f=fixture(4);
  let iteratorReads=0,indexReads=0;
  // All four declared roster entries are invalid. A hostile iterator or
  // index getter must not substitute four separately signed admissions.
  const forged=new Proxy([null,null,null,null],{
    get(target,key,receiver){
      if(key===Symbol.iterator){
        iteratorReads++;
        return function*(){yield* f.registry.validators;};
      }
      if(typeof key==="string" && /^[0-3]$/.test(key)){
        indexReads++;
        return f.registry.validators[Number(key)];
      }
      return Reflect.get(target,key,receiver);
    }
  });
  assert.throws(()=>parseRegistry({...f.registry,validators:forged},f.gov.publicKeyB64),
    /Noncanonical PoP validator/);
  assert.equal(iteratorReads,0,"unsigned validator iterator must never execute");
  assert.equal(indexReads,0,"unsigned validator index getter must never execute");
  const admitted=parseRegistry(f.registry,f.gov.publicKeyB64);
  assert.equal(admitted.quorum,3);
  assert.equal(admitted.validators.length,4);
});

test("research quorum verifies vote descriptors without Proxy getter substitution",()=>{
  const f=fixture(4),{proposal,votes}=f.bundle();
  let reads=0;
  // The declared voters are unadmitted, but a hostile get trap supplies
  // three genuine signed votes. Only the declared descriptor data may count.
  const forged=votes.map(signed=>new Proxy({
    validatorId:"0x"+"f".repeat(64),signature:signed.signature
  },{
    get(target,key,receiver){
      if(key==="validatorId"){
        reads++;
        return signed.validatorId;
      }
      return Reflect.get(target,key,receiver);
    }
  }));
  assert.throws(()=>verifyCertificate(f.committee,proposal,forged),
    /Unadmitted PoP voter/);
  assert.equal(reads,0,"vote getter must never substitute a signed voter");
  const valid=verifyCertificate(f.committee,proposal,votes);
  assert.equal(valid.signers,3);
  assert.equal(valid.finalized,false);
  assert.equal(valid.productionConsensus,false);
});

test("research admissions bind registry and validator descriptor snapshots against Proxy substitution",()=>{
  const f=fixture(4);
  let registryReads=0;
  // Declared chain ID is not the one authenticated by governance signatures.
  // A hostile getter used to swap in the signed ID during verification.
  const registry=new Proxy({...f.registry,chainId:"privi-pop-research-forged-v1"},{
    get(target,key,receiver){
      if(key==="chainId"){registryReads++;return f.registry.chainId;}
      return Reflect.get(target,key,receiver);
    }
  });
  assert.throws(()=>parseRegistry(registry,f.gov.publicKeyB64),
    /admission signature invalid or absent/);
  assert.equal(registryReads,0,"registry Proxy getter must never execute");

  let validatorReads=0;
  const validators=[...f.registry.validators];
  const signed=validators[0];
  validators[0]=new Proxy({...signed,operatorId:"UNSIGNED_OPERATOR"},{
    get(target,key,receiver){
      if(key==="operatorId"){validatorReads++;return signed.operatorId;}
      return Reflect.get(target,key,receiver);
    }
  });
  assert.throws(()=>parseRegistry({...f.registry,validators},f.gov.publicKeyB64),
    /admission signature invalid or absent/);
  assert.equal(validatorReads,0,"validator Proxy getter must never execute");
  assert.equal(parseRegistry(f.registry,f.gov.publicKeyB64).quorum,3);
});

test("research 31-member quorum boundary is 21 signatures and 32 members fail closed",()=>{
  // Research committee admission has a hard 31-member bound. A 20-of-31
  // certificate is below >2/3 even if every signature is authentic.
  const f=fixture(31);
  assert.equal(f.committee.validators.length,31);
  assert.equal(f.committee.quorum,21);
  const {proposal,votes}=f.bundle(11,0,undefined,undefined,31);
  assert.equal(votes.length,31);
  assert.throws(()=>verifyCertificate(f.committee,proposal,votes.slice(0,20)),
    /Insufficient independently signed PoP quorum/);
  const proof=verifyCertificate(f.committee,proposal,votes.slice(0,21));
  assert.equal(proof.valid,true);
  assert.equal(proof.signers,21);
  assert.equal(proof.quorum,21);
  assert.equal(proof.signerIds.length,21);
  assert.equal(proof.finalized,false);
  assert.equal(proof.productionConsensus,false);
  assert.throws(()=>fixture(32),/PoP requires 4..31 attested research validators/);
});


test("research vote lock ignores inherited JSON hooks when preventing double-signs",()=>{
  const f=fixture(4),lock=new ResearchVoteLock();
  const validatorId=f.keys[0].id,height=22,epoch=1;
  const parent="0x"+"a".repeat(64);
  const block="0x"+"b".repeat(64);
  const conflict="0x"+"c".repeat(64);
  const original=Object.getOwnPropertyDescriptor(Array.prototype,"toJSON");
  let hookCalls=0;
  try {
    Object.defineProperty(Array.prototype,"toJSON",{
      configurable:true,writable:true,
      value(){hookCalls++;return ["untrusted-key-"+hookCalls];}
    });
    lock.accept(epoch,height,0,validatorId,block,parent);
    assert.throws(()=>lock.accept(epoch,height,1,validatorId,conflict,parent),
      /conflicting-height double-sign rejected/);
    assert.throws(()=>lock.accept(epoch+1,height,0,validatorId,block,parent),
      /same-height epoch transition rejected/);
    assert.equal(hookCalls,0,"lock key derivation must not call inherited JSON hooks");
  } finally {
    if(original)Object.defineProperty(Array.prototype,"toJSON",original);
    else delete Array.prototype.toJSON;
  }
  // A matching same-epoch commitment remains idempotent after restoring
  // the runtime; this is only an in-memory research guard, not finality.
  lock.accept(epoch,height,2,validatorId,block,parent);
  assert.throws(()=>lock.accept(epoch,height,3,validatorId,conflict,parent),
    /conflicting-height double-sign rejected/);
});

test("research signatures cannot be rebound by inherited Array.toJSON",()=>{
  const original=Object.getOwnPropertyDescriptor(Array.prototype,"toJSON");
  try {
    Object.defineProperty(Array.prototype,"toJSON",{
      configurable:true,writable:true,
      value(){return ["attacker-replaced-every-signed-field"];}
    });
    const canonical=signedMessage("commit",["alpha",7]).toString("utf8");
    assert.equal(canonical,
      ["Privi/PoP/Research/2026/v1","commit",'["alpha",7]'].join("\n"));
    const f=fixture(4),{proposal,votes}=f.bundle();
    assert.equal(verifyCertificate(f.committee,proposal,votes).valid,true);
    // The proposer signed a different block; inherited serialization hooks
    // must not turn that signature into authority over this forged proposal.
    const altered={...proposal,blockHash:"0x"+"e".repeat(64)};
    assert.notEqual(altered.blockHash,proposal.blockHash);
    assert.throws(()=>verifyCertificate(f.committee,altered,votes),
      /Unsigned\/forged PoP proposal/);
  } finally {
    if(original)Object.defineProperty(Array.prototype,"toJSON",original);
    else delete Array.prototype.toJSON;
  }
});

test("research vote snapshot ignores poisoned Array.prototype iterator",()=>{
  const f=fixture(4),{proposal,votes}=f.bundle();
  // All declared votes have unadmitted signer IDs. An inherited iterator
  // must not replace their descriptor snapshots with three authentic votes.
  const forged=votes.map(v=>({
    validatorId:"0x"+"f".repeat(64),signature:v.signature
  }));
  const original=Object.getOwnPropertyDescriptor(Array.prototype,Symbol.iterator);
  let hijacks=0;
  try {
    Object.defineProperty(Array.prototype,Symbol.iterator,{
      configurable:true,writable:true,
      value:function(){
        if(this.length===forged.length && this[0]===forged[0]){
          hijacks++;
          return original.value.call(votes);
        }
        return original.value.call(this);
      }
    });
    assert.throws(()=>verifyCertificate(f.committee,proposal,forged),
      /Unadmitted PoP voter/);
    assert.equal(hijacks,0,"quorum evaluation must not invoke inherited vote iterator");
  } finally {
    Object.defineProperty(Array.prototype,Symbol.iterator,original);
  }
  const proof=verifyCertificate(f.committee,proposal,votes);
  assert.equal(proof.signers,3);
  assert.equal(proof.finalized,false);
  assert.equal(proof.productionConsensus,false);
});

test("research vote signatures cannot be rebound by inherited Array iterator",()=>{
  const f=fixture(4),{proposal,votes}=f.bundle();
  const otherHash="0x"+"d".repeat(64);
  const otherFields=proposalFields(f.committee,proposal.height,proposal.round,
    proposal.previousBlockHash,otherHash,proposal.proposerId);
  const signerById=new Map(f.keys.map(key=>[key.id,key]));
  // These votes authenticate a DIFFERENT block from the valid proposal.
  const otherVotes=votes.map(v=>({
    validatorId:v.validatorId,
    signature:sign(signerById.get(v.validatorId),"commit",
      voteFields(otherFields,v.validatorId))
  }));
  assert.throws(()=>verifyCertificate(f.committee,proposal,otherVotes),
    /Forged or wrong-epoch\/chain\/round PoP vote/);
  const original=Object.getOwnPropertyDescriptor(Array.prototype,Symbol.iterator);
  let substitutions=0;
  try {
    Object.defineProperty(Array.prototype,Symbol.iterator,{
      configurable:true,writable:true,
      value:function(){
        if(Array.isArray(this) && this.length===8 &&
           this[0]===f.committee.chainId && this[6]===proposal.blockHash){
          substitutions++;
          const changed=new Array(8);
          for(let i=0;i<8;i++)changed[i]=i===6?otherHash:this[i];
          return original.value.call(changed);
        }
        return original.value.call(this);
      }
    });
    // An inherited iterator must not rebind the proposal's block A to
    // signatures issued for block B. Old spread-based voteFields fails here.
    assert.throws(()=>verifyCertificate(f.committee,proposal,otherVotes),
      /Forged or wrong-epoch\/chain\/round PoP vote/);
    assert.equal(substitutions,0,
      "verified vote fields must never invoke inherited array iteration");
  } finally {
    Object.defineProperty(Array.prototype,Symbol.iterator,original);
  }
  assert.equal(verifyCertificate(f.committee,proposal,votes).valid,true);
});


test("research vote lock ignores poisoned inherited Map get/set methods",()=>{
  const f=fixture(4),id=f.keys[0].id;
  const first="0x"+"b".repeat(64),other="0x"+"c".repeat(64);
  const parent="0x"+"a".repeat(64);
  const lock=new ResearchVoteLock();
  lock.accept(1,61,0,id,first,parent);
  const originalGet=Map.prototype.get;
  let conflictError;
  try {
    // A poisoned inherited get must not erase a previously committed vote.
    Map.prototype.get=function(){return undefined;};
    try {lock.accept(1,61,1,id,other,parent);}
    catch(error){conflictError=error;}
  } finally {
    Map.prototype.get=originalGet;
  }
  assert.match(conflictError?.message || "",
    /PoP conflicting-height double-sign rejected/);
  const second=new ResearchVoteLock();
  const originalSet=Map.prototype.set;
  try {
    // A poisoned inherited set must not silently drop the first reservation.
    Map.prototype.set=function(){return this;};
    second.accept(1,62,0,id,first,parent);
  } finally {
    Map.prototype.set=originalSet;
  }
  assert.throws(()=>second.accept(1,62,1,id,other,parent),
    /PoP conflicting-height double-sign rejected/);
  // Both guards still permit idempotent same-height research replay.
  lock.accept(1,61,2,id,first,parent);
  second.accept(1,62,2,id,first,parent);
});


test("research proposer election ignores inherited Array.map manipulation",()=>{
  const f=fixture(7),expected=[];
  for(let round=0;round<16;round++){
    expected.push(proposer(f.committee,19,round));
  }
  const original=Array.prototype.map;
  let intercepted=0,actual;
  try {
    Array.prototype.map=function(){
      intercepted++;
      throw Error("poisoned inherited array map executed");
    };
    actual=[];
    for(let round=0;round<16;round++){
      actual.push(proposer(f.committee,19,round));
    }
  } finally {
    Array.prototype.map=original;
  }
  assert.deepEqual(actual,expected,
    "governance-admitted roster must determine the same research proposer");
  assert.equal(intercepted,0,"proposer must not invoke inherited array map");
});


test("research quorum vote descriptors resist inherited Array.map substitution",()=>{
  const f=fixture(4),{proposal,votes}=f.bundle();
  // Each declared voter is unadmitted, although the signature belongs to
  // an authentic admitted voter. A poisoned inherited map must not replace
  // the descriptors checked by the quorum verifier with authentic ones.
  const forged=votes.map(v=>({
    validatorId:"0x"+"f".repeat(64),signature:v.signature
  }));
  const original=Array.prototype.map;
  let intercepted=0,next=0;
  try {
    Array.prototype.map=function(callback,thisArg){
      if(this.length===2 && this[0]==="validatorId" && this[1]==="signature"){
        intercepted++;
        const authentic=votes[next++];
        return [
          Object.getOwnPropertyDescriptor(authentic,"validatorId"),
          Object.getOwnPropertyDescriptor(authentic,"signature")
        ];
      }
      return original.call(this,callback,thisArg);
    };
    assert.throws(()=>verifyCertificate(f.committee,proposal,forged),
      /Unadmitted PoP voter/);
    assert.equal(intercepted,0,
      "verified signer identity must not be selected by inherited map");
    const valid=verifyCertificate(f.committee,proposal,votes);
    assert.equal(valid.signers,3);
    assert.equal(valid.productionConsensus,false);
    assert.equal(valid.finalized,false);
  } finally {
    Array.prototype.map=original;
  }
});

test("admission descriptor snapshot cannot be replaced by inherited array iterator",()=>{
  const f=fixture(5);
  // The fifth admission is signed by the same governance key, but it is NOT
  // declared in this four-validator roster. An inherited iterator must not
  // replace the fourth declared operator with that valid outsider.
  const registry={...f.registry,validators:f.registry.validators.slice(0,4)};
  const outsider=f.registry.validators[4];
  const declaredIds=new Set(registry.validators.map(v=>v.id));
  const originalIterator=Array.prototype[Symbol.iterator];
  let substitutions=0;
  try {
    Array.prototype[Symbol.iterator]=function*(){
      if(this.length===4 &&
         this[0]===registry.validators[0] &&
         this[1]===registry.validators[1] &&
         this[2]===registry.validators[2] &&
         this[3]===registry.validators[3]){
        substitutions++;
        yield this[0];yield this[1];yield this[2];yield outsider;
        return;
      }
      yield* originalIterator.call(this);
    };
    const committee=parseRegistry(registry,f.gov.publicKeyB64);
    assert.equal(substitutions,0,
      "the verified admission snapshot must never invoke inherited iteration");
    assert.equal(committee.validators.length,4);
    for(let i=0;i<committee.validators.length;i++){
      assert.ok(declaredIds.has(committee.validators[i].id),
        "only descriptor-declared validator identities may be admitted");
    }
    assert.equal(committee.byId.has(outsider.id),false,
      "valid governance signature alone does not authorize undeclared admission");
  } finally {
    Array.prototype[Symbol.iterator]=originalIterator;
  }
});

test("governance admission ignores inherited Array.from and every roster substitutions",()=>{
  const f=fixture(4);
  const originalFrom=Array.from;
  let fromInterceptions=0;
  try {
    Array.from=function(source,mapper,thisArg){
      if(source && !Array.isArray(source) && source.length===4 &&
         typeof mapper==="function"){
        fromInterceptions++;
        // The old admission preflight would accept these booleans without
        // snapshotting any of the four signed validator records.
        return [true,true,true,true];
      }
      return originalFrom.call(this,source,mapper,thisArg);
    };
    const admitted=parseRegistry(f.registry,f.gov.publicKeyB64);
    assert.equal(admitted.validators.length,4);
    assert.equal(admitted.quorum,3);
    assert.equal(fromInterceptions,0,
      "untrusted Array.from must not select the admitted committee");
  } finally {
    Array.from=originalFrom;
  }

  const originalEvery=Array.prototype.every;
  let everyInterceptions=0,getterReads=0;
  const accessorRoster=f.registry.validators.slice();
  Object.defineProperty(accessorRoster,"2",{enumerable:true,configurable:true,
    get(){getterReads++;throw Error("untrusted validator index getter executed");}});
  try {
    Array.prototype.every=function(predicate,thisArg){
      if(predicate===Boolean && this.length===4){
        everyInterceptions++;
        return true; // Previously hid a failed descriptor check.
      }
      return originalEvery.call(this,predicate,thisArg);
    };
    assert.throws(()=>parseRegistry({...f.registry,validators:accessorRoster},
      f.gov.publicKeyB64),/Noncanonical PoP validator roster/);
    assert.equal(getterReads,0);
    assert.equal(everyInterceptions,0,
      "inherited every must not override roster descriptor rejection");
  } finally {
    Array.prototype.every=originalEvery;
  }
  assert.equal(parseRegistry(f.registry,f.gov.publicKeyB64).validators.length,4);
});

test("research admitted committee ignores inherited sort/map/forEach hooks",()=>{
  const f=fixture(7);
  const expectedIds=f.committee.validators.map(v=>v.id);
  const originalSort=Array.prototype.sort;
  const originalMap=Array.prototype.map;
  const originalForEach=Array.prototype.forEach;
  const intercepted={sort:0,map:0,forEach:0};
  const isAdmissionArray=a=>Array.isArray(a) && a.length===7 &&
    a[0] && typeof a[0]==="object" &&
    Object.hasOwn(a[0],"pub") && Object.hasOwn(a[0],"id");
  let admitted;
  try {
    Array.prototype.sort=function(...args){
      if(isAdmissionArray(this)){
        intercepted.sort++;
        throw Error("poisoned admitted committee sort");
      }
      return originalSort.apply(this,args);
    };
    Array.prototype.map=function(...args){
      if(isAdmissionArray(this)){
        intercepted.map++;
        throw Error("poisoned admitted committee map");
      }
      return originalMap.apply(this,args);
    };
    Array.prototype.forEach=function(...args){
      if(isAdmissionArray(this)){
        intercepted.forEach++;
        throw Error("poisoned admitted committee forEach");
      }
      return originalForEach.apply(this,args);
    };
    admitted=parseRegistry(f.registry,f.gov.publicKeyB64);
  } finally {
    Array.prototype.sort=originalSort;
    Array.prototype.map=originalMap;
    Array.prototype.forEach=originalForEach;
  }
  assert.deepEqual(intercepted,{sort:0,map:0,forEach:0},
    "signed committee admission must not invoke inherited array hooks");
  assert.deepEqual(admitted.validators.map(v=>v.id),expectedIds,
    "canonical admitted roster must be stable across hosts");
  assert.equal(admitted.quorum,5);
  for(const signer of admitted.validators){
    assert.equal(admitted.byId.get(signer.id),signer,
      "admitted signer map must match the verified canonical roster");
  }
  for(let round=0;round<16;round++){
    assert.equal(proposer(admitted,19,round),proposer(f.committee,19,round));
  }
  const {proposal,votes}=f.bundle();
  const proof=verifyCertificate(admitted,proposal,votes);
  assert.equal(proof.signers,admitted.quorum);
  assert.equal(proof.finalized,false);
  assert.equal(proof.productionConsensus,false);
});

test("inherited array iterator cannot hide a substituted admitted signer key",()=>{
  const f=fixture(4),{proposal,votes}=f.bundle();
  const map=f.committee.byId;
  const admitted=Map.prototype.get.call(map,proposal.proposerId);
  const attacker=makeKey();
  const fields=proposalFields(f.committee,proposal.height,proposal.round,
                              proposal.previousBlockHash,proposal.blockHash,
                              proposal.proposerId);
  const forgedProposal={...proposal,signature:sign(attacker,"propose",fields)};
  const keys=new Map(f.keys.map(k=>[k.id,k]));
  // An attacker-controlled proposer key must not become an admitted voter.
  // The other three signatures remain authentic and form a research quorum.
  const independentVotes=f.committee.validators
    .filter(v=>v.id!==proposal.proposerId)
    .map(v=>({validatorId:v.id,
              signature:sign(keys.get(v.id),"commit",voteFields(fields,v.id))}));
  assert.equal(independentVotes.length,3);
  const original=Object.getOwnPropertyDescriptor(Array.prototype,Symbol.iterator);
  const nativeIterator=original.value;
  let intercepted=0,proof,error;
  try {
    Map.prototype.set.call(map,proposal.proposerId,{
      ...admitted,pub:crypto.createPublicKey(attacker.privateKey)
    });
    // Only the admitted committee's iterator lies. All other arrays retain
    // their original iteration behavior so a forged certificate would pass
    // on the vulnerable membership-check path.
    Object.defineProperty(Array.prototype,Symbol.iterator,{
      configurable:true,writable:true,
      value:function(){
        if(this===f.committee.validators){
          intercepted++;
          return nativeIterator.call([]);
        }
        return nativeIterator.call(this);
      }
    });
    try {
      proof=verifyCertificate(f.committee,forgedProposal,independentVotes);
    } catch(e) { error=e; }
  } finally {
    Object.defineProperty(Array.prototype,Symbol.iterator,original);
    Map.prototype.set.call(map,proposal.proposerId,admitted);
  }
  assert.equal(intercepted,0,
    "authenticated membership checks must not consult inherited iterators");
  assert.equal(proof,undefined,
    "a forged proposer key must never authorize a research quorum certificate");
  assert.match(error?.message||"",/membership changed/);
  assert.equal(verifyCertificate(f.committee,proposal,votes).valid,true,
    "the original signed research certificate remains verifiable");
});

test("research quorum ignores poisoned Set and Array prototype methods",()=>{
  const f=fixture(4),{proposal,votes}=f.bundle();
  // Three copies of ONE valid signature are never three independent votes.
  const duplicate=[votes[0],{...votes[0]},{...votes[0]}];
  const reversed=votes.slice().reverse();
  const expectedIds=votes.map(v=>v.validatorId).sort();
  const originalHas=Set.prototype.has,originalAdd=Set.prototype.add;
  const originalSize=Object.getOwnPropertyDescriptor(Set.prototype,"size");
  const originalIterator=Object.getOwnPropertyDescriptor(Set.prototype,Symbol.iterator);
  const originalSort=Array.prototype.sort;
  let duplicateError,legitimateProof,legitimateError;
  try {
    // On the vulnerable path, a false has(), discarded add(), and forged
    // size getter could make one real signer appear to meet a 3-of-4 quorum.
    Set.prototype.has=function(){return false;};
    Set.prototype.add=function(){return this;};
    Object.defineProperty(Set.prototype,"size",{
      configurable:true,get(){return 3;}
    });
    Set.prototype[Symbol.iterator]=function*(){
      yield "0x"+"f".repeat(64);
    };
    Array.prototype.sort=function(){return this;};
    try {verifyCertificate(f.committee,proposal,duplicate);}
    catch(e) {duplicateError=e;}
    try {legitimateProof=verifyCertificate(f.committee,proposal,reversed);}
    catch(e) {legitimateError=e;}
  } finally {
    Set.prototype.has=originalHas;
    Set.prototype.add=originalAdd;
    Object.defineProperty(Set.prototype,"size",originalSize);
    Object.defineProperty(Set.prototype,Symbol.iterator,originalIterator);
    Array.prototype.sort=originalSort;
  }
  assert.match(duplicateError?.message||"",/Duplicate PoP voter/,
    "repeated signature must never become a forged research quorum");
  assert.equal(legitimateError,undefined);
  assert.equal(legitimateProof.signers,3);
  assert.deepEqual(legitimateProof.signerIds,expectedIds);
  assert.equal(legitimateProof.finalized,false);
  assert.equal(legitimateProof.productionConsensus,false);
});

test("research governance admission rejects duplicate identities despite poisoned Set methods",()=>{
  const f=fixture(4);
  const mutations=[
    registry=>{registry.validators[1]={...registry.validators[0]};},
    registry=>{registry.validators[1].operatorId=registry.validators[0].operatorId;},
    registry=>{registry.validators[1].faultDomain=registry.validators[0].faultDomain;},
    registry=>{
      const v=registry.validators[1],original=registry.validators[0];
      v.companyId=original.companyId;
      v.positionSequence=original.positionSequence;
      v.positionHash=hash(Buffer.from(positionStamp(v.companyId,v.positionSequence)));
    }
  ];
  // All four collisions retain correctly signed governance admission records.
  // The only invalid property is the duplicate signer/operator/domain/position.
  const registries=mutations.map(mutate=>{
    const registry=structuredClone(f.registry);
    mutate(registry);
    const v=registry.validators[1];
    const fields=[registry.chainId,registry.genesisHash,registry.epoch,
      v.operatorId,v.faultDomain,v.companyId,v.positionSequence,v.id,
      v.anchorBlockHash];
    v.admissionSignature=sign(f.gov,"admit",fields);
    return registry;
  });
  const originalHas=Set.prototype.has,originalAdd=Set.prototype.add;
  const errors=[];
  let validCommittee;
  try {
    // The previous parser delegated uniqueness to these mutable methods.
    // A forged always-false has() plus discarded add() admitted duplicates.
    Set.prototype.has=function(){return false;};
    Set.prototype.add=function(){return this;};
    for(let i=0;i<registries.length;i++){
      try {parseRegistry(registries[i],f.gov.publicKeyB64);}
      catch(e){errors[errors.length]=e;}
    }
    validCommittee=parseRegistry(f.registry,f.gov.publicKeyB64);
  } finally {
    Set.prototype.has=originalHas;
    Set.prototype.add=originalAdd;
  }
  assert.equal(errors.length,4,"every signed admission collision must fail closed");
  for(const error of errors){
    assert.match(error.message,/Duplicated validator, operator, failure domain, or PoP position/);
  }
  assert.equal(validCommittee.validators.length,4);
  assert.equal(validCommittee.quorum,3);
  const {proposal,votes}=f.bundle();
  assert.equal(verifyCertificate(validCommittee,proposal,votes).valid,true);
  assert.equal(verifyCertificate(validCommittee,proposal,votes).productionConsensus,false);
});


test("research admission and certificate snapshots ignore poisoned Array.prototype.push",()=>{
  const f=fixture(4),{proposal,votes}=f.bundle();
  const originalPush=Array.prototype.push;
  let intercepted=0;
  try {
    Array.prototype.push=function(...items){
      // Simulate process-wide prototype pollution targeting signed roster
      // admission records and authenticated vote descriptor snapshots.
      if(items.length===1 && items[0] && typeof items[0]==="object" &&
         (Object.hasOwn(items[0],"keySpkiBase64") ||
          Object.hasOwn(items[0],"validatorId"))){
        intercepted++;
        throw Error("poisoned Array.push intercepted signed record");
      }
      return Reflect.apply(originalPush,this,items);
    };
    const admitted=parseRegistry(f.registry,f.gov.publicKeyB64);
    assert.equal(admitted.validators.length,4);
    assert.equal(admitted.quorum,3);
    const proof=verifyCertificate(admitted,proposal,votes);
    assert.equal(proof.valid,true);
    assert.equal(proof.signers,3);
    assert.equal(proof.finalized,false);
    assert.equal(proof.productionConsensus,false);
  } finally {
    Array.prototype.push=originalPush;
  }
  assert.equal(intercepted,0,"authenticated snapshots must not call inherited push");
});
