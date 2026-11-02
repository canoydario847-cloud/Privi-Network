"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const {spawn} = require("node:child_process");
const {recordFor,lockedFileName} = require("./persistent_vote_guard.cjs");
const {TRUSTED_MODE} = require("./engine.cjs");

// Cross-process research signing-state race test. No tokens, mainnet IDs,
// network listeners, actual private keys or validator nodes are touched.
const validatorId = "0x" + "1".repeat(64);
const genesisHash = "0x" + "a".repeat(64);
function committee() {
  return {chainId:"privi-pop-research-race",genesisHash,epoch:1,
          mode:TRUSTED_MODE,byId:new Map([[validatorId,{}]])};
}
function runWorker(dir, blockHash, epoch=1, previousBlockHash="0x"+"b".repeat(64)) {
  const worker = `
    "use strict";
    const {reservePosition} = require(process.argv[1]);
    const dir = process.argv[2], blockHash = process.argv[3];
    const previousBlockHash=process.argv[5];
    const signerId = "0x" + "1".repeat(64);
    const research = {
      mode:"attested-position-research-not-live-consensus",
      chainId:"privi-pop-research-race",genesisHash:"0x"+"a".repeat(64),
      epoch:Number(process.argv[4]),byId:new Map([[signerId,{}]])
    };
    try {
      reservePosition(dir,research,7,signerId,blockHash,previousBlockHash);
      process.exitCode=0;
    } catch (e) {
      process.stderr.write(String(e.message)+"\\n");
      process.exitCode=13;
    }
  `;
  return new Promise((resolve,reject)=>{
    const child=spawn(process.execPath,["-e",worker,
      require.resolve("./persistent_vote_guard.cjs"),dir,blockHash,String(epoch),previousBlockHash],{
      stdio:["ignore","pipe","pipe"]
    });
    let stderr="";
    child.stderr.setEncoding("utf8");
    child.stderr.on("data",chunk=>{stderr+=chunk;});
    child.on("error",reject);
    child.on("close",code=>resolve({code,stderr}));
  });
}

test("two competing research validator processes cannot reserve opposing commits",async()=>{
  for(let i=0;i<5;i++){
    const dir=fs.mkdtempSync(path.join(os.tmpdir(),"privi-pop-vote-race-"));
    fs.chmodSync(dir,0o700);
    try {
      const left="0x"+"c".repeat(64), right="0x"+"d".repeat(64);
      const results=await Promise.all([runWorker(dir,left),runWorker(dir,right)]);
      assert.deepEqual(results.map(x=>x.code).sort((a,b)=>a-b),[0,13],
        "at most one validator process may reserve a conflicting block");
      assert.match(results.find(x=>x.code===13).stderr,/equivocation|corrupt/);
      const file=path.join(dir,lockedFileName(recordFor(committee(),7,validatorId,left,"0x"+"b".repeat(64))));
      const saved=JSON.parse(fs.readFileSync(file,"utf8"));
      assert.ok(saved.blockHash===left || saved.blockHash===right);
      assert.equal(fs.readdirSync(dir).length,1);
      assert.equal(fs.statSync(file).mode & 0o077,0);
    } finally {
      fs.rmSync(dir,{recursive:true,force:true});
    }
  }
});


test("concurrent cross-epoch attempts never reopen same-height signing lock",async()=>{
  for(const sameHash of [true,false]){
    const dir=fs.mkdtempSync(path.join(os.tmpdir(),"privi-pop-cross-epoch-race-"));
    fs.chmodSync(dir,0o700);
    try{
      const firstHash="0x"+"c".repeat(64);
      const nextHash=sameHash?firstHash:"0x"+"d".repeat(64);
      const results=await Promise.all([
        runWorker(dir,firstHash,1),
        runWorker(dir,nextHash,2)
      ]);
      assert.deepEqual(results.map(x=>x.code).sort((a,b)=>a-b),[0,13],
        "a signer must not accept two same-height votes across research epochs");
      assert.match(results.find(x=>x.code===13).stderr,/inconsistent|equivocation|corrupt/);
      const file=path.join(dir,lockedFileName(recordFor(committee(),7,validatorId,firstHash,"0x"+"b".repeat(64))));
      const saved=JSON.parse(fs.readFileSync(file,"utf8"));
      assert.ok(saved.epoch===1 || saved.epoch===2);
      assert.equal(saved.blockHash,saved.epoch===1?firstHash:nextHash);
      assert.equal(fs.readdirSync(dir).length,1);
      // The previously accepted epoch wins; the other epoch cannot
      // replay even an identical hash after a validator process restart.
      const replay=await runWorker(dir,saved.blockHash,saved.epoch===1?2:1);
      assert.equal(replay.code,13);
      assert.match(replay.stderr,/inconsistent|equivocation/);
    }finally{
      fs.rmSync(dir,{recursive:true,force:true});
    }
  }
});


test("two research signing processes cannot lock the same candidate hash under different parents",async()=>{
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),"privi-pop-parent-race-"));
  fs.chmodSync(dir,0o700);
  try{
    const blockHash="0x"+"c".repeat(64);
    const firstParent="0x"+"a".repeat(64);
    const otherParent="0x"+"b".repeat(64);
    const results=await Promise.all([
      runWorker(dir,blockHash,1,firstParent),
      runWorker(dir,blockHash,1,otherParent)
    ]);
    assert.deepEqual(results.map(x=>x.code).sort((a,b)=>a-b),[0,13]);
    assert.match(results.find(x=>x.code===13).stderr,/conflicting parent|corrupt/);
    const file=path.join(dir,lockedFileName(recordFor(committee(),7,
                                    validatorId,blockHash,firstParent)));
    const saved=JSON.parse(fs.readFileSync(file,"utf8"));
    assert.ok(saved.previousBlockHash===firstParent||saved.previousBlockHash===otherParent);
    assert.equal(saved.blockHash,blockHash);
    assert.equal(saved.format,"PriviPoPResearchHeightLock/v2");
    assert.equal(fs.readdirSync(dir).length,1);
    assert.equal((await runWorker(dir,blockHash,1,saved.previousBlockHash)).code,0);
    const rejected=saved.previousBlockHash===firstParent?otherParent:firstParent;
    assert.equal((await runWorker(dir,blockHash,1,rejected)).code,13);
  }finally{fs.rmSync(dir,{recursive:true,force:true});}
});
