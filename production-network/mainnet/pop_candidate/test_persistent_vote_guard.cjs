"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const os=require("node:os");
const path=require("node:path");
const crypto=require("node:crypto");
const {
  hash,signedMessage,parseRegistry,positionStamp,proposer,
  proposalFields,verifyCertificate,TRUSTED_MODE
}=require("./engine.cjs");
const {
  recordFor,lockedFileName,reservePosition,signCommitWithResearchLock
}=require("./persistent_vote_guard.cjs");

const makeKey=()=>{
  const pair=crypto.generateKeyPairSync("ed25519");
  const der=pair.publicKey.export({type:"spki",format:"der"});
  return {id:hash(der),pub:der.toString("base64"),privateKey:pair.privateKey};
};
const sign=(privateKey,tag,fields)=>
  crypto.sign(null,signedMessage(tag,fields),privateKey).toString("base64");
function fixture(){
  const gov=makeKey(),keys=Array.from({length:4},makeKey);
  const chainId="privi-pop-research-lock-test",genesisHash="0x"+"a".repeat(64),epoch=1;
  const registry={chainId,genesisHash,epoch,mode:TRUSTED_MODE,validators:keys.map((k,i)=>{
    const operatorId="OPERATOR_"+i,faultDomain="operator"+i+".example";
    const companyId="CO_"+i,positionSequence=i+1;
    const anchorBlockHash=hash(Buffer.from("native-chain-attested-anchor-"+i));
    return {
      id:k.id,keySpkiBase64:k.pub,operatorId,faultDomain,companyId,
      positionSequence,anchorBlockHash,
      positionHash:hash(Buffer.from(positionStamp(companyId,positionSequence))),
      admissionSignature:sign(gov.privateKey,"admit",[
        chainId,genesisHash,epoch,operatorId,faultDomain,companyId,
        positionSequence,k.id,anchorBlockHash
      ])
    };
  })};
  const committee=parseRegistry(registry,gov.pub);
  const keysById=new Map(keys.map(k=>[k.id,k.privateKey]));
  function proposal(height=5,round=0,blockHash="0x"+"c".repeat(64),
                    previousBlockHash="0x"+"b".repeat(64)){
    const proposerId=proposer(committee,height,round);
    const fields=proposalFields(committee,height,round,previousBlockHash,blockHash,proposerId);
    return {height,round,blockHash,previousBlockHash,proposerId,
            signature:sign(keysById.get(proposerId),"propose",fields)};
  }
  return {committee,keysById,proposal};
}
function tempRoot(){
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),"privi-pop-research-lock-"));
  fs.chmodSync(dir,0o700);
  return dir;
}

test("3-of-4 genuine votes are reserved on disk before signature release",()=>{
  const f=fixture(),p=f.proposal(),dirs=[],votes=[];
  try {
    for(const validator of f.committee.validators.slice(0,3)){
      const dir=tempRoot();
      dirs.push(dir);
      const vote=signCommitWithResearchLock({
        lockDirectory:dir,committee:f.committee,proposal:p,
        privateKey:f.keysById.get(validator.id)
      });
      assert.equal(vote.validatorId,validator.id);
      assert.equal(vote.researchOnly,true);
      const r=recordFor(f.committee,p.height,validator.id,p.blockHash,p.previousBlockHash);
      const file=path.join(dir,lockedFileName(r));
      const saved=JSON.parse(fs.readFileSync(file,"utf8"));
      assert.deepEqual(saved,r);
      assert.equal(fs.statSync(file).mode & 0o077,0);
      votes.push(vote);
    }
    assert.equal(verifyCertificate(f.committee,p,votes).valid,true);
  } finally { for(const dir of dirs)fs.rmSync(dir,{recursive:true,force:true}); }
});

test("same height cannot sign conflicting block even across round or process restart",()=>{
  const f=fixture(),dir=tempRoot();
  try {
    const p=f.proposal(9,0,"0x"+"c".repeat(64));
    const voter=f.committee.validators[0],key=f.keysById.get(voter.id);
    const input={lockDirectory:dir,committee:f.committee,privateKey:key};
    const first=signCommitWithResearchLock({...input,proposal:p});
    const resumed=signCommitWithResearchLock({...input,proposal:p});
    assert.equal(first.signature,resumed.signature);
    const conflicting=f.proposal(9,1,"0x"+"d".repeat(64));
    assert.throws(()=>signCommitWithResearchLock({...input,proposal:conflicting}),/equivocation/);
    // Progress at a NEW height is allowed.
    assert.ok(signCommitWithResearchLock({...input,proposal:f.proposal(10,0)}).signature);
  } finally {fs.rmSync(dir,{recursive:true,force:true});}
});

test("research signer refuses same candidate block hash with a different signed parent",()=>{
  const f=fixture(),dir=tempRoot();
  try{
    const id=f.committee.validators[0].id;
    const privateKey=f.keysById.get(id);
    const first=f.proposal(19,0,"0x"+"c".repeat(64),"0x"+"a".repeat(64));
    const second=f.proposal(19,1,"0x"+"c".repeat(64),"0x"+"b".repeat(64));
    const input={lockDirectory:dir,committee:f.committee,privateKey};
    const signed=signCommitWithResearchLock({...input,proposal:first});
    const savedPath=path.join(dir,lockedFileName(recordFor(f.committee,19,id,
                                  first.blockHash,first.previousBlockHash)));
    assert.equal(signed.researchOnly,true);
    assert.equal(JSON.parse(fs.readFileSync(savedPath,"utf8")).previousBlockHash,
                 first.previousBlockHash);
    assert.throws(()=>signCommitWithResearchLock({...input,proposal:second}),
                  /conflicting parent at locked height/);
    assert.equal(fs.readdirSync(dir).length,1);
    assert.equal(JSON.parse(fs.readFileSync(savedPath,"utf8")).previousBlockHash,
                 first.previousBlockHash,"rejected vote must preserve first durable lock");
    const replay=signCommitWithResearchLock({...input,proposal:first});
    assert.equal(replay.signature,signed.signature);
  }finally{fs.rmSync(dir,{recursive:true,force:true});}
});

test("research signer refuses missing parent commitment before writing lock",()=>{
  const f=fixture(),dir=tempRoot();
  try{
    const p=f.proposal(),v=f.committee.validators[0];
    assert.throws(()=>recordFor(f.committee,p.height,v.id,p.blockHash),
                  /previous-block hash/);
    assert.throws(()=>reservePosition(dir,f.committee,p.height,v.id,p.blockHash),
                  /previous-block hash/);
    assert.deepEqual(fs.readdirSync(dir),[]);
  }finally{fs.rmSync(dir,{recursive:true,force:true});}
});

test("legacy parentless lock cannot be silently upgraded or reused",()=>{
  const f=fixture(),dir=tempRoot();
  try{
    const p=f.proposal(),v=f.committee.validators[0];
    const input={lockDirectory:dir,committee:f.committee,proposal:p,
                 privateKey:f.keysById.get(v.id)};
    signCommitWithResearchLock(input);
    const file=path.join(dir,lockedFileName(recordFor(f.committee,
                 p.height,v.id,p.blockHash,p.previousBlockHash)));
    const record=JSON.parse(fs.readFileSync(file,"utf8"));
    delete record.previousBlockHash;
    record.format="PriviPoPResearchHeightLock/v1";
    fs.writeFileSync(file,JSON.stringify(record)+"\n");
    assert.throws(()=>signCommitWithResearchLock(input),/inconsistent/);
    assert.equal(JSON.parse(fs.readFileSync(file,"utf8")).format,
                 "PriviPoPResearchHeightLock/v1");
  }finally{fs.rmSync(dir,{recursive:true,force:true});}
});

test("same-height vote lock does not reset when a research committee epoch changes",()=>{
  const f=fixture(),dir=tempRoot();
  try {
    const id=f.committee.validators[0].id;
    const oldHash="0x"+"e".repeat(64),nextHash="0x"+"f".repeat(64);
    const prior=recordFor(f.committee,25,id,oldHash,"0x"+"b".repeat(64));
    const changed={...f.committee,epoch:f.committee.epoch+1};
    const next=recordFor(changed,25,id,nextHash,"0x"+"b".repeat(64));
    assert.equal(lockedFileName(prior),lockedFileName(next),
      "same signer and height MUST share the lock across epochs");
    reservePosition(dir,f.committee,25,id,oldHash,"0x"+"b".repeat(64));
    assert.throws(()=>reservePosition(dir,changed,25,id,nextHash,"0x"+"b".repeat(64)),
      /equivocation|inconsistent/);
    assert.throws(()=>reservePosition(dir,changed,25,id,oldHash,"0x"+"b".repeat(64)),
      /inconsistent/,"unreviewed epoch migration cannot silently reset old signer state");
    const saved=JSON.parse(fs.readFileSync(path.join(dir,lockedFileName(prior)),"utf8"));
    assert.equal(saved.epoch,f.committee.epoch);
    assert.equal(saved.blockHash,oldHash);
    assert.equal(fs.readdirSync(dir).length,1);
    // A NEW height remains signable even in the changed research epoch.
    assert.equal(reservePosition(dir,changed,26,id,nextHash,"0x"+"b".repeat(64)).alreadyReserved,false);
  } finally {fs.rmSync(dir,{recursive:true,force:true});}
});

test("corrupt lock state must fail closed and remain present for audit",()=>{
  const f=fixture(),dir=tempRoot();
  try {
    const p=f.proposal(),v=f.committee.validators[0];
    const input={lockDirectory:dir,committee:f.committee,proposal:p,
                 privateKey:f.keysById.get(v.id)};
    signCommitWithResearchLock(input);
    const file=path.join(dir,lockedFileName(recordFor(f.committee,p.height,v.id,p.blockHash,p.previousBlockHash)));
    fs.writeFileSync(file,"broken-json");
    assert.throws(()=>signCommitWithResearchLock(input),/corrupt/);
    assert.equal(fs.readFileSync(file,"utf8"),"broken-json");
  } finally {fs.rmSync(dir,{recursive:true,force:true});}
});

test("ambiguous duplicate-key and noncanonical persisted locks cannot release votes",()=>{
  const f=fixture();
  const p=f.proposal(41),v=f.committee.validators[0];
  const inputKey=f.keysById.get(v.id);
  const mutations=[
    ["earlier forged blockHash masked by duplicate JSON key",original=>
      '{"blockHash":"0x'+"f".repeat(64)+'",'+original.slice(1)],
    ["equivalent JSON with different whitespace",original=>
      JSON.stringify(JSON.parse(original),null,2)+"\n"],
    ["appended trailing whitespace",original=>original+" \n"],
  ];
  for(const [kind,mutate] of mutations) {
    const dir=tempRoot();
    const input={lockDirectory:dir,committee:f.committee,proposal:p,
                 privateKey:inputKey};
    try {
      const first=signCommitWithResearchLock(input);
      assert.equal(first.researchOnly,true);
      const record=recordFor(f.committee,p.height,v.id,p.blockHash,p.previousBlockHash);
      const file=path.join(dir,lockedFileName(record));
      const original=fs.readFileSync(file,"utf8");
      const tampered=mutate(original);
      assert.deepEqual(JSON.parse(tampered),JSON.parse(original),
        "mutation must have the same decoded fields to demonstrate JSON parsing ambiguity");
      fs.writeFileSync(file,tampered);
      assert.throws(()=>signCommitWithResearchLock(input),
        /corrupt or noncanonical/,kind);
      assert.equal(fs.readFileSync(file,"utf8"),tampered,
        "ambiguous height lock must remain for forensic review");
    } finally {
      fs.rmSync(dir,{recursive:true,force:true});
    }
  }
});

test("existing lock replay re-syncs file and directory before signing",()=>{
  const f=fixture(),dir=tempRoot();
  const p=f.proposal(),v=f.committee.validators[0];
  const input={lockDirectory:dir,committee:f.committee,proposal:p,
               privateKey:f.keysById.get(v.id)};
  const originalSync=fs.fsyncSync;
  try {
    const first=signCommitWithResearchLock(input);
    const observed=[];
    fs.fsyncSync=function(fd){
      observed.push(fs.fstatSync(fd).isDirectory()?"directory":"file");
      return originalSync(fd);
    };
    const repeated=signCommitWithResearchLock(input);
    assert.equal(repeated.signature,first.signature);
    assert.deepEqual(observed,["file","directory"],
      "existing height lock must be durable before replayed signature");
  } finally {
    fs.fsyncSync=originalSync;
    fs.rmSync(dir,{recursive:true,force:true});
  }
});

test("failed existing-lock directory sync refuses a signature, then permits retry",()=>{
  const f=fixture(),dir=tempRoot();
  const p=f.proposal(),v=f.committee.validators[0];
  const input={lockDirectory:dir,committee:f.committee,proposal:p,
               privateKey:f.keysById.get(v.id)};
  const originalSync=fs.fsyncSync;
  try {
    const signed=signCommitWithResearchLock(input);
    const file=path.join(dir,lockedFileName(recordFor(f.committee,p.height,v.id,p.blockHash,p.previousBlockHash)));
    fs.fsyncSync=function(fd){
      if (fs.fstatSync(fd).isDirectory()) throw Error("simulated directory sync failure");
      return originalSync(fd);
    };
    assert.throws(()=>signCommitWithResearchLock(input),/directory sync failure/);
    assert.ok(fs.existsSync(file),"failed sync must retain lock for operator recovery");
    fs.fsyncSync=originalSync;
    assert.equal(signCommitWithResearchLock(input).signature,signed.signature);
  } finally {
    fs.fsyncSync=originalSync;
    fs.rmSync(dir,{recursive:true,force:true});
  }
});

test("hard-linked existing lock must fail closed",()=>{
  const f=fixture(),dir=tempRoot();
  try {
    const p=f.proposal(),v=f.committee.validators[0];
    const input={lockDirectory:dir,committee:f.committee,proposal:p,
                 privateKey:f.keysById.get(v.id)};
    const signed=signCommitWithResearchLock(input);
    const file=path.join(dir,lockedFileName(recordFor(f.committee,p.height,v.id,p.blockHash,p.previousBlockHash)));
    const alias=path.join(dir,"linked-lock.json");
    fs.linkSync(file,alias);
    assert.equal(fs.statSync(file).nlink,2);
    assert.throws(()=>signCommitWithResearchLock(input),/hard-linked/);
    assert.ok(fs.existsSync(file));
    fs.unlinkSync(alias);
    assert.equal(signCommitWithResearchLock(input).signature,signed.signature);
  } finally {fs.rmSync(dir,{recursive:true,force:true});}
});

test("insecure path and symlinked root are forbidden",()=>{
  const f=fixture(),dir=tempRoot();
  const tmp=path.join(os.tmpdir(),"privi-pop-link-"+crypto.randomBytes(8).toString("hex"));
  try {
    const p=f.proposal(),v=f.committee.validators[0];
    const input={lockDirectory:dir,committee:f.committee,proposal:p,
                 privateKey:f.keysById.get(v.id)};
    fs.chmodSync(dir,0o755);
    assert.throws(()=>signCommitWithResearchLock(input),/owner-only/);
    fs.chmodSync(dir,0o700);
    fs.symlinkSync(dir,tmp,"dir");
    assert.throws(()=>signCommitWithResearchLock({...input,lockDirectory:tmp}),/symlink/);
  } finally {
    fs.rmSync(tmp,{force:true});
    fs.rmSync(dir,{recursive:true,force:true});
  }
});

test("symlinked ancestor of research vote lock is rejected",()=>{
  const f=fixture(),root=tempRoot();
  try {
    const actual=path.join(root,"actual");
    fs.mkdirSync(actual,{mode:0o700});
    const alias=path.join(root,"alias");
    fs.symlinkSync(actual,alias,"dir");
    const nested=path.join(alias,"locks");
    fs.mkdirSync(nested,{mode:0o700});
    const v=f.committee.validators[0],p=f.proposal();
    assert.throws(()=>signCommitWithResearchLock({
      lockDirectory:nested,committee:f.committee,proposal:p,
      privateKey:f.keysById.get(v.id)
    }),/symlink/);
    assert.deepEqual(fs.readdirSync(path.join(actual,"locks")),[]);
  } finally {fs.rmSync(root,{recursive:true,force:true});}
});


test("caller-supplied committee cannot obtain a research signature or reserve a height",()=>{
  const f=fixture(),dir=tempRoot();
  try {
    const p=f.proposal(),v=f.committee.validators[0];
    const input={lockDirectory:dir,proposal:p,privateKey:f.keysById.get(v.id)};
    const cloned={...f.committee};
    // A shallow copy preserves the proposer, signatures and key map.
    // It does not carry proof that the actual governance root admitted it.
    assert.throws(()=>signCommitWithResearchLock({...input,committee:cloned}),
                  /Unverified PoP committee/);
    assert.deepEqual(fs.readdirSync(dir),[],"forged committee cannot leave signing state");
    const forgedQuorum={...f.committee,quorum:1};
    assert.throws(()=>signCommitWithResearchLock({...input,committee:forgedQuorum}),
                  /Unverified PoP committee/);
    assert.deepEqual(fs.readdirSync(dir),[]);
    // A genuine admitted committee can still produce a research-only signature.
    assert.ok(signCommitWithResearchLock({...input,committee:f.committee}).signature);
  } finally {fs.rmSync(dir,{recursive:true,force:true});}
});

test("mutated signer-map cannot obtain a research signature",()=>{
  const f=fixture(),dir=tempRoot(),p=f.proposal();
  const proposer=f.committee.byId.get(p.proposerId);
  const voter=f.committee.validators[0];
  const input={lockDirectory:dir,committee:f.committee,proposal:p,
               privateKey:f.keysById.get(voter.id)};
  try {
    f.committee.byId.set(p.proposerId,{...proposer});
    assert.throws(()=>signCommitWithResearchLock(input),/membership changed/);
    assert.deepEqual(fs.readdirSync(dir),[]);
  } finally {
    f.committee.byId.set(p.proposerId,proposer);
    fs.rmSync(dir,{recursive:true,force:true});
  }
});

test("unauthorized key or malformed proposal cannot obtain a lock",()=>{
  const f=fixture(),dir=tempRoot();
  try {
    const p=f.proposal(),rogue=makeKey();
    assert.throws(()=>signCommitWithResearchLock({
      lockDirectory:dir,committee:f.committee,proposal:p,privateKey:rogue.privateKey
    }),/not a registered PoP validator/);
    const voter=f.committee.validators[0];
    assert.throws(()=>signCommitWithResearchLock({
      lockDirectory:dir,committee:f.committee,
      proposal:{...p,blockHash:"0x"+"f".repeat(64)},
      privateKey:f.keysById.get(voter.id)
    }),/proposal/);
    assert.equal(fs.readdirSync(dir).length,0,"no lock should be written for invalid proposal");
  } finally {fs.rmSync(dir,{recursive:true,force:true});}
});

test("research-only network and false committee are refused",()=>{
  const f=fixture(),dir=tempRoot();
  try {
    const p=f.proposal(),v=f.committee.validators[0];
    const fake={...f.committee,mode:"production"};
    assert.throws(()=>reservePosition(dir,fake,p.height,v.id,p.blockHash,p.previousBlockHash),/RESEARCH ONLY/);
    const another={...f.committee,chainId:"ethereum"};
    assert.throws(()=>reservePosition(dir,another,p.height,v.id,p.blockHash,p.previousBlockHash),/Native Privi research/);
  } finally {fs.rmSync(dir,{recursive:true,force:true});}
});
