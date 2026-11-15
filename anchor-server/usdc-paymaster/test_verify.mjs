// Offline verifier regression suite. All chain operations are mocked; no keys or spending.
import test from "node:test";
import assert from "node:assert/strict";
import { encodeFunctionData, encodeEventTopics, encodeAbiParameters, parseAbiParameters } from "viem";
import { verifyPriviUserOp, checkPriviCalls, ENTRYPOINT_ABI, SIMPLE_7702_ABI,
         ENTRYPOINT_V08 } from "./verify.mjs";
import { anchorData, BASE_USDC, DATA_SINK, EIP7702_IMPLEMENTATION } from "./anchor.mjs";

const root="ab".repeat(32), sender="0x4228f264fEA8e2FDb1e21a3d124673653E4B3bF7";
const paymaster="0x000000000000000000000000000000000000bEEF";
const userOpHash="0x"+"11".repeat(32), txHash="0x"+"22".repeat(32),
      blockHash="0x"+"33".repeat(32);
const lower=x=>x.toLowerCase();

function calls(approve=false, fee=2000n) {
  const list=[{target:DATA_SINK,value:0n,data:anchorData(root)}];
  if (approve) list.unshift({target:BASE_USDC,value:0n,data:encodeFunctionData({
    abi:[{type:"function",name:"approve",stateMutability:"nonpayable",
      inputs:[{name:"spender",type:"address"},{name:"value",type:"uint256"}],outputs:[{name:"",type:"bool"}]}],
    functionName:"approve",args:[paymaster,fee],
  })});
  return encodeFunctionData({abi:SIMPLE_7702_ABI,functionName:"executeBatch",args:[list]});
}
function entry(callData=calls()) {
  return {sender,nonce:1n,initCode:"0x",callData,
    accountGasLimits:"0x"+"00".repeat(32),preVerificationGas:100n,
    gasFees:"0x"+"00".repeat(32),
    paymasterAndData:paymaster+"12".repeat(32),signature:"0x1234"};
}
function mock(overrides={}) {
  const op=overrides.op||entry();
  const tx={hash:txHash,to:ENTRYPOINT_V08,blockHash,blockNumber:100n,
    input:encodeFunctionData({abi:ENTRYPOINT_ABI,functionName:"handleOps",args:[[op],sender]})};
  const topics=encodeEventTopics({abi:ENTRYPOINT_ABI,eventName:"UserOperationEvent",
    args:{userOpHash,sender,paymaster}});
  const log={address:ENTRYPOINT_V08,topics,
    data:encodeAbiParameters(parseAbiParameters("uint256 nonce, bool success, uint256 actualGasCost, uint256 actualGasUsed"),
    [op.nonce,overrides.success ?? true,100n,42n])};
  const receipt={status:"success",transactionHash:txHash,blockNumber:100n,
    blockHash,logs:[log]};
  const client={
    getChainId:async()=>8453,
    getTransaction:async()=>({...tx,...overrides.tx}),
    getTransactionReceipt:async()=>({...receipt,...overrides.receipt}),
    getBlockNumber:async()=>102n,
    getBlock:async()=>({hash:blockHash}),
    getBytecode:async()=> "0xef0100"+EIP7702_IMPLEMENTATION.slice(2),
    readContract:async({args})=>args[0].nonce===1n?userOpHash:"0x"+"44".repeat(32),
    ...overrides.client,
  };
  return {proof:{root,txHash,userOpHash,sender},client};
}

test("read-only verifier confirms one onchain PRVA root, no wallet or API keys",async()=>{
  const {proof,client}=mock();
  const result=await verifyPriviUserOp(proof,client);
  assert.equal(result.verified,true);
  assert.equal(result.merkle_root,root);
  assert.equal(result.confirmations,3);
  assert.equal(result.approval_calls,0);
  assert.match(result.paymaster_fee_currency,/not independently/);
});
test("single bounded Base USDC approval to actual operation paymaster is allowed",async()=>{
  const {proof,client}=mock({op:entry(calls(true))});
  const result=await verifyPriviUserOp(proof,client);
  assert.equal(result.approval_calls,1);
});
test("reject changed root, forged event, wrong delegation and outer failed tx",async()=>{
  for(const mutate of [
    ({proof})=>{proof.root="cd".repeat(32);},
    ({client})=>{client.readContract=async()=> "0x"+"44".repeat(32);},
    ({client})=>{client.getBytecode=async()=> "0xef0100"+"00".repeat(20);},
  ]) {
    const v=mock();mutate(v);await assert.rejects(verifyPriviUserOp(v.proof,v.client));
  }
  const bad=mock({receipt:{status:"reverted"}});
  await assert.rejects(verifyPriviUserOp(bad.proof,bad.client),/reverted/);
});
test("reject reverted user op even if bundle succeeded",async()=>{
  const {proof,client}=mock({success:false});
  await assert.rejects(verifyPriviUserOp(proof,client),/reverted/);
});
test("reject false EntryPoint and unconfirmed tx",async()=>{
  const w=mock({tx:{to:"0x0000000000000000000000000000000000000001"}});
  await assert.rejects(verifyPriviUserOp(w.proof,w.client),/EntryPoint/);
  const v=mock({client:{getBlockNumber:async()=>100n}});
  await assert.rejects(verifyPriviUserOp(v.proof,v.client,{minConfirmations:2}),/confirmations/);
});
test("reject extra arbitrary transfers and unlimited approvals",()=>{
  const other=encodeFunctionData({abi:SIMPLE_7702_ABI,functionName:"executeBatch",
    args:[[{target:"0x0000000000000000000000000000000000000001",value:100n,data:"0x"},
           {target:DATA_SINK,value:0n,data:anchorData(root)}]]});
  assert.throws(()=>checkPriviCalls(entry(other),root),/Unexpected extra/);
  assert.throws(()=>checkPriviCalls(entry(calls(true,50001n)),root),/fee cap/);
});
test("accept single-call execute and reject wrong sink",()=>{
  const direct=encodeFunctionData({abi:SIMPLE_7702_ABI,functionName:"execute",args:[DATA_SINK,0n,anchorData(root)]});
  assert.equal(checkPriviCalls(entry(direct),root).approvalCalls,0);
  const bad=encodeFunctionData({abi:SIMPLE_7702_ABI,functionName:"execute",args:[BASE_USDC,0n,anchorData(root)]});
  assert.throws(()=>checkPriviCalls(entry(bad),root),/Target/);
});
