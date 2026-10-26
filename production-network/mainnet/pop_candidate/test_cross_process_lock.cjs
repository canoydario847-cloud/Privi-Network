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
function runWorker(dir, blockHash, epoch=1) {
  const worker = `
    "use strict";
    const {reservePosition} = require(process.argv[1]);
    const dir = process.argv[2], blockHash = process.argv[3];
    const signerId = "0x" + "1".repeat(64);
    const research = {
      mode:"attested-position-research-not-live-consensus",
      chainId:"privi-pop-research-race",genesisHash:"0x"+"a".repeat(64),
      epoch:Number(process.argv[4]),byId:new Map([[signerId,{}]])
    };
    try {
      reservePosition(dir,research,7,signerId,blockHash);
      process.exitCode=0;
    } catch (e) {
      process.stderr.write(String(e.message)+"\\n");
      process.exitCode=13;
    }
  `;
  return new Promise((resolve,reject)=>{
    const child=spawn(process.execPath,["-e",worker,
      require.resolve("./persistent_vote_guard.cjs"),dir,blockHash,String(epoch)],{
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
      const file=path.join(dir,lockedFileName(recordFor(committee(),7,validatorId,left)));
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
      const file=path.join(dir,lockedFileName(recordFor(committee(),7,validatorId,firstHash)));
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
