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
  function proposal(height=5,round=0,blockHash="0x"+"c".repeat(64)){
    const previousBlockHash="0x"+"b".repeat(64);
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
      const r=recordFor(f.committee,p.height,validator.id,p.blockHash);
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

test("corrupt lock state must fail closed and remain present for audit",()=>{
  const f=fixture(),dir=tempRoot();
  try {
    const p=f.proposal(),v=f.committee.validators[0];
    const input={lockDirectory:dir,committee:f.committee,proposal:p,
                 privateKey:f.keysById.get(v.id)};
    signCommitWithResearchLock(input);
    const file=path.join(dir,lockedFileName(recordFor(f.committee,p.height,v.id,p.blockHash)));
    fs.writeFileSync(file,"broken-json");
    assert.throws(()=>signCommitWithResearchLock(input),/corrupt/);
    assert.equal(fs.readFileSync(file,"utf8"),"broken-json");
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
    assert.throws(()=>reservePosition(dir,fake,p.height,v.id,p.blockHash),/RESEARCH ONLY/);
    const another={...f.committee,chainId:"ethereum"};
    assert.throws(()=>reservePosition(dir,another,p.height,v.id,p.blockHash),/Native Privi research/);
  } finally {fs.rmSync(dir,{recursive:true,force:true});}
});
