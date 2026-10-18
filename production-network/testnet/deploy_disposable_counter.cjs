#!/usr/bin/env node
"use strict";
/*
 * Disposable GitHub CI-only EVM contract deployment/state write.
 * Creates no real PRVI or BNB PRIV and never sends transactions to public RPC.
 * Reuses a local upstream TEST account key only in runner memory, with no log.
 */
const fs=require("node:fs");
const path=require("node:path");
const crypto=require("node:crypto");
const {localGate,exportDevKey}=require("./send_disposable_test_transfer.cjs");

function check(ok,why){if(!ok)throw new Error(why);}
const RPC="http://127.0.0.1:8545";
const ID=262144;
const SHA=x=>crypto.createHash("sha256").update(x).digest("hex");

function compileFixture(solc, source){
  check(typeof solc.version==="function" &&
        solc.version().startsWith("0.8.26+"),
        "unexpected Solidity compiler; expected pinned 0.8.26");
  check(source.includes("contract PriviDevCounter") && source.length<20000,
        "unexpected nonfinancial source fixture");
  const input={
    language:"Solidity",
    sources:{"PriviDevCounter.sol":{content:source}},
    settings:{optimizer:{enabled:true,runs:200},evmVersion:"paris",
      outputSelection:{"*":{"*":["abi","evm.bytecode.object","evm.deployedBytecode.object"]}}}
  };
  const output=JSON.parse(solc.compile(JSON.stringify(input)));
  const errors=(output.errors||[]).filter(x=>x.severity==="error");
  check(errors.length===0, "Solidity compilation errors: "+errors.length);
  const c=output.contracts?.["PriviDevCounter.sol"]?.PriviDevCounter;
  check(c && Array.isArray(c.abi), "no contract ABI");
  const init=c.evm?.bytecode?.object,runtime=c.evm?.deployedBytecode?.object;
  check(typeof init==="string" && /^[0-9a-fA-F]+$/.test(init),
        "missing init EVM bytecode");
  check(typeof runtime==="string" && /^[0-9a-fA-F]+$/.test(runtime),
        "missing deployed EVM bytecode");
  return {abi:c.abi,bytecode:"0x"+init,expectedRuntime:"0x"+runtime};
}
function guardDeps(env){
  localGate(env,RPC);
  check(env.PRIVI_ETHERS_MODULE_PATH?.includes("privi-test-ethers"),
        "expected isolated ethers path");
  check(env.PRIVI_SOLC_MODULE_PATH?.includes("privi-test-ethers"),
        "expected isolated solc path");
}
async function run(env=process.env){
  guardDeps(env);
  const {ethers}=require(env.PRIVI_ETHERS_MODULE_PATH);
  const solc=require(env.PRIVI_SOLC_MODULE_PATH);
  const source=fs.readFileSync(path.join(__dirname,"contracts","PriviDevCounter.sol"),"utf8");
  const compiled=compileFixture(solc,source);
  const provider=new ethers.JsonRpcProvider(RPC,{name:"privi-local-ephemeral",chainId:ID},
                                           {staticNetwork:true});
  const observed=BigInt(await provider.send("eth_chainId",[]));
  check(observed===BigInt(ID),"unexpected network: refusing contract deployment");
  const key=exportDevKey(path.resolve(__dirname,"..",".upstream-evm"));
  const wallet=new ethers.Wallet(key,provider);
  const before=await provider.getBalance(wallet.address);
  const gasPrice=10000000000n;
  check(before>gasPrice*2700000n, "disposable developer account lacks contract gas");
  const factory=new ethers.ContractFactory(compiled.abi,compiled.bytecode,wallet);
  const contract=await factory.deploy({gasLimit:2500000n,gasPrice,type:0});
  const deployment=contract.deploymentTransaction();
  check(!!deployment && /^0x[0-9a-f]{64}$/i.test(deployment.hash),
        "no contract deployment tx hash");
  const deployed=await deployment.wait(2,120000);
  check(deployed && deployed.status===1, "contract deployment failed");
  const address=await contract.getAddress();
  check(/^0x[0-9a-f]{40}$/i.test(address),"invalid deployed contract address");
  check(deployed.contractAddress?.toLowerCase()===address.toLowerCase(),
        "receipt deployment contract address mismatch");
  const actualRuntime=await provider.getCode(address);
  check(actualRuntime!=="0x" && actualRuntime.toLowerCase()===compiled.expectedRuntime.toLowerCase(),
        "deployed bytecode differs from compiler fixture");
  check(await contract.count()===0n,"new contract counter not zero");

  const call=await contract.increment({gasLimit:200000n,gasPrice,type:0});
  const receipt=await call.wait(2,120000);
  check(receipt && receipt.status===1,"counter state transaction not mined successfully");
  check(receipt.to?.toLowerCase()===address.toLowerCase(),"state-write receipt to wrong contract");
  const matching=[];
  for(const entry of receipt.logs){
    if(entry.address.toLowerCase()!==address.toLowerCase())continue;
    try{
      const decoded=contract.interface.parseLog(entry);
      if(decoded?.name==="Incremented")matching.push(decoded);
    }catch(_){}
  }
  check(matching.length===1,"missing or duplicate Incremented event");
  check(matching[0].args[0].toLowerCase()===wallet.address.toLowerCase() &&
        matching[0].args[1]===1n,"event sender/updated value mismatch");
  const count=await contract.count();
  check(count===1n,"contract state not persisted after transaction");
  const runtimeHash=SHA(Buffer.from(actualRuntime.slice(2),"hex"));
  console.log(JSON.stringify({
    status:"DISPOSABLE_LOCAL_EVM_CONTRACT_DEPLOY_AND_STATE_WRITE_VERIFIED",
    cosmos_chain_id:"local-4221",evm_chain_id:ID,asset:"valueless atest only",
    source_sha256:SHA(source),
    solidity_compiler:solc.version(),runtime_code_sha256:runtimeHash,
    contract_address:address,
    deploy_transaction:deployment.hash,deploy_block:deployed.blockNumber,
    state_transaction:call.hash,state_block:receipt.blockNumber,
    counter_before:"0",counter_after:count.toString(),
    increment_event_verified:true,
    deploy_confirmations:2,state_confirmations:2,
    limitations:"Temporary same-runner developer chain only; no production PRVI, public validators or financial launch"
  },null,2));
}
if(require.main===module){
  run().catch(error=>{
    // This CI output never dumps private key, runner environment or raw commands.
    console.error("Disposable contract test FAILED: "+
      String(error?.shortMessage||error?.message||"unknown").slice(0,240));
    process.exitCode=1;
  });
}
module.exports={guardDeps,compileFixture};
