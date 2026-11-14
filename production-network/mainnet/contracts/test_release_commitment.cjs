'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const solc=require('solc');
const source=fs.readFileSync(path.join(__dirname,'PriviMainnetReleaseCommitment.sol'),'utf8');
function compile() {
  const input={language:'Solidity',sources:{'PriviMainnetReleaseCommitment.sol':{content:source}},settings:{optimizer:{enabled:true,runs:200},outputSelection:{'*':{'*':['abi','evm.bytecode.object']}}}};
  const output=JSON.parse(solc.compile(JSON.stringify(input)));
  const errors=(output.errors||[]).filter(x=>x.severity==='error');
  assert.deepEqual(errors,[],JSON.stringify(errors));
  return output.contracts['PriviMainnetReleaseCommitment.sol'].PriviMainnetReleaseCommitment;
}
test('Solidity release-commitment contract compiles cleanly',()=>{
 const c=compile();
 assert.ok(c.evm.bytecode.object.length>100);
});
test('registry stores hashes without balance, mint, transfers or launch approval entrypoints',()=>{
 const c=compile();
 const methods=c.abi.filter(x=>x.type==='function').map(x=>x.name).sort();
 assert.deepEqual(methods,['acceptOwnership','genesisRecorded','getRelease','nextRelease','nominateOwner','owner','pendingOwner','recordRelease'].sort());
 const record=c.abi.find(x=>x.name==='recordRelease');
 assert.equal(record.inputs.length,5);
 assert.equal(record.stateMutability,'nonpayable');
 assert.ok(!c.abi.some(x=>x.type==='fallback'||x.type==='receive'));
});
