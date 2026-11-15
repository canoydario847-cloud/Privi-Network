// Copyright (c) 2026 Privi World Corp. All rights reserved.
// Read-only independent Base EIP-4337 v0.8 / EIP-7702 Privi anchor verifier.
// Everything is reconstructed from an onchain transaction and receipt;
// no signing keys, EOA permissions, paymaster access, or fund transfers are needed.
import { decodeFunctionData, parseEventLogs, createPublicClient, http } from "viem";
import { base } from "viem/chains";
import { pathToFileURL } from "node:url";
import process from "node:process";
import { anchorData, BASE_CHAIN_ID, BASE_USDC, DATA_SINK, EIP7702_IMPLEMENTATION } from "./anchor.mjs";

export const ENTRYPOINT_V08 = "0x4337084D9E255Ff0702461CF8895CE9E3b5Ff108";
const OP_FIELDS = [
  ["sender","address"], ["nonce","uint256"], ["initCode","bytes"],
  ["callData","bytes"], ["accountGasLimits","bytes32"],
  ["preVerificationGas","uint256"], ["gasFees","bytes32"],
  ["paymasterAndData","bytes"], ["signature","bytes"],
].map(([name,type]) => ({name,type}));

export const ENTRYPOINT_ABI = [
  {type:"function",name:"handleOps",stateMutability:"nonpayable",
   inputs:[{name:"ops",type:"tuple[]",components:OP_FIELDS},{name:"beneficiary",type:"address"}],outputs:[]},
  {type:"function",name:"getUserOpHash",stateMutability:"view",
   inputs:[{name:"userOp",type:"tuple",components:OP_FIELDS}],outputs:[{name:"",type:"bytes32"}]},
  {type:"event",name:"UserOperationEvent",anonymous:false,inputs:[
    {name:"userOpHash",type:"bytes32",indexed:true},
    {name:"sender",type:"address",indexed:true},
    {name:"paymaster",type:"address",indexed:true},
    {name:"nonce",type:"uint256",indexed:false},
    {name:"success",type:"bool",indexed:false},
    {name:"actualGasCost",type:"uint256",indexed:false},
    {name:"actualGasUsed",type:"uint256",indexed:false},
  ]},
];

export const SIMPLE_7702_ABI = [
  {type:"function",name:"execute",stateMutability:"nonpayable",inputs:[
    {name:"target",type:"address"},{name:"value",type:"uint256"},{name:"data",type:"bytes"}],outputs:[]},
  {type:"function",name:"executeBatch",stateMutability:"nonpayable",inputs:[
    {name:"calls",type:"tuple[]",components:[
      {name:"target",type:"address"},{name:"value",type:"uint256"},{name:"data",type:"bytes"}]}],outputs:[]},
];

const APPROVE_ABI = [{type:"function",name:"approve",stateMutability:"nonpayable",inputs:[
  {name:"spender",type:"address"},{name:"value",type:"uint256"}],outputs:[{name:"",type:"bool"}]}];
const HASH = /^0x[0-9a-fA-F]{64}$/;
const ADDRESS = /^0x[0-9a-fA-F]{40}$/;
const equal = (x,y) => typeof x === "string" && typeof y === "string" && x.toLowerCase() === y.toLowerCase();
function assert(condition, message) { if (!condition) throw new Error(message); }

export function decodePriviCalls(callData) {
  let decoded;
  try { decoded = decodeFunctionData({abi:SIMPLE_7702_ABI,data:callData}); }
  catch { throw new Error("Unrecognized EIP-7702 execution method; verification refused"); }
  if (decoded.functionName === "execute") {
    const [to,value,data] = decoded.args;
    return [{to,value,data}];
  }
  if (decoded.functionName === "executeBatch") {
    return decoded.args[0].map(x => ({
      to:x.target ?? x[0], value:x.value ?? x[1], data:x.data ?? x[2],
    }));
  }
  throw new Error("Unsupported execution method");
}

export function checkPriviCalls(userOp, expectedRoot, maxUsdcFeeAtomic=50000n) {
  assert(typeof maxUsdcFeeAtomic === "bigint" && maxUsdcFeeAtomic >= 0n,
         "Invalid USDC fee cap");
  const wanted = anchorData(expectedRoot);
  const calls = decodePriviCalls(userOp.callData);
  assert(calls.length === 1 || calls.length === 2,
         "Expected exactly one anchor call and at most one paymaster approval");
  const anchor = calls[calls.length-1];
  assert(equal(anchor.to,DATA_SINK) && anchor.value === 0n && equal(anchor.data,wanted),
         "Target, value or Privi Merkle root does not match the onchain operation");
  if (calls.length === 2) {
    const first = calls[0];
    assert(equal(first.to,BASE_USDC) && first.value === 0n, "Unexpected extra transfer or contract call");
    let parsed;
    try { parsed = decodeFunctionData({abi:APPROVE_ABI,data:first.data}); }
    catch { throw new Error("Unexpected extra call (not an ERC-20 approval)"); }
    assert(parsed.functionName === "approve", "Unexpected extra call");
    const paymaster = "0x" + String(userOp.paymasterAndData || "").replace(/^0x/,"").slice(0,40);
    assert(ADDRESS.test(paymaster) && paymaster !== "0x"+"0".repeat(40),
           "Missing paymaster address in the onchain operation");
    assert(equal(parsed.args[0],paymaster), "USDC spender is not the operation paymaster");
    assert(parsed.args[1] <= maxUsdcFeeAtomic, "USDC approval exceeds the configured fee cap");
  }
  return {anchorCall:anchor, approvalCalls:calls.length-1};
}

/** Fully independent proof: reads the actual Base transaction, EntryPoint hash, logs and account code. */
export async function verifyPriviUserOp(proof, client, opts={}) {
  const {root, txHash, userOpHash, sender} = proof ?? {};
  assert(HASH.test(txHash) && HASH.test(userOpHash) && ADDRESS.test(sender),
         "Expected transaction hash, userOp hash and account address");
  const wanted = anchorData(root);
  const chainId = await client.getChainId();
  assert(chainId === BASE_CHAIN_ID, "RPC chain ID is not Base mainnet");
  const tx = await client.getTransaction({hash:txHash});
  const receipt = await client.getTransactionReceipt({hash:txHash});
  assert(tx && receipt && equal(tx.hash,txHash) && equal(receipt.transactionHash,txHash),
         "Transaction or receipt not found");
  assert(receipt.status === "success", "Outer bundle transaction reverted");
  assert(equal(tx.to,ENTRYPOINT_V08), "Transaction is not an EntryPoint v0.8 bundle");
  assert(tx.blockNumber != null && receipt.blockNumber === tx.blockNumber &&
         equal(tx.blockHash,receipt.blockHash), "Inconsistent transaction and receipt block");
  const latest = await client.getBlockNumber();
  const minConfirmations = opts.minConfirmations ?? 2;
  assert(Number.isInteger(minConfirmations) && minConfirmations >= 1, "Invalid confirmation count");
  assert(latest >= tx.blockNumber && latest - tx.blockNumber + 1n >= BigInt(minConfirmations),
         "Transaction lacks required confirmations");
  const block = await client.getBlock({blockNumber:tx.blockNumber});
  assert(block && equal(block.hash,tx.blockHash), "Transaction block is no longer canonical");
  const delegatedCode = await client.getBytecode({address:sender,blockNumber:tx.blockNumber});
  assert(equal(delegatedCode, "0xef0100" + EIP7702_IMPLEMENTATION.slice(2)),
         "EIP-7702 signer was not delegated to the approved Simple7702Account at this block");

  let decoded;
  try { decoded = decodeFunctionData({abi:ENTRYPOINT_ABI,data:tx.input}); }
  catch { throw new Error("Unable to decode an EntryPoint v0.8 bundle"); }
  assert(decoded.functionName === "handleOps",
         "Unsupported EntryPoint method: only handleOps is permitted");
  const ops = decoded.args[0];
  assert(ops.length > 0 && ops.length <= 100, "Invalid or oversized UserOperation batch");
  const candidates = ops.filter(op => equal(op.sender,sender));
  assert(candidates.length > 0, "Signer not found in bundled operations");
  let matched = null;
  for (const op of candidates) {
    // Onchain EntryPoint implementation computes the EIP-712 hash, including the
    // EIP-7702 authorization/initCode rules. Hashing a raw blob offchain is insufficient.
    const hash = await client.readContract({
      address:ENTRYPOINT_V08,abi:ENTRYPOINT_ABI,functionName:"getUserOpHash",
      args:[op],blockNumber:tx.blockNumber,
    });
    if (equal(hash,userOpHash)) {
      assert(matched === null, "Ambiguous duplicate UserOperations");
      matched = op;
    }
  }
  assert(matched, "No onchain UserOperation matches the requested hash and sender");
  const parsed = parseEventLogs({
    abi:ENTRYPOINT_ABI,eventName:"UserOperationEvent",
    logs:receipt.logs.filter(l => equal(l.address,ENTRYPOINT_V08)),
    strict:true,
  });
  const events = parsed.filter(l => equal(l.args.userOpHash,userOpHash));
  assert(events.length === 1, "Expected exactly one onchain UserOperationEvent");
  assert(equal(events[0].args.sender,sender) && events[0].args.nonce === matched.nonce &&
         events[0].args.success === true, "UserOperation reverted or event attributes mismatch");
  const callInfo = checkPriviCalls(matched, root, opts.maxUsdcFeeAtomic ?? 50000n);
  assert(equal(callInfo.anchorCall.data,wanted), "Privi hash missing");
  return {
    verified:true, proof_version:"prva-userop-v1", chain_id:BASE_CHAIN_ID,
    account:sender.toLowerCase(), user_op_hash:userOpHash.toLowerCase(),
    tx_hash:txHash.toLowerCase(), block_number:Number(tx.blockNumber),
    merkle_root:root.replace(/^0x/i,"").toLowerCase(),
    confirmations:Number(latest-tx.blockNumber+1n),
    approval_calls:callInfo.approvalCalls,
    paymaster_fee_currency:"not independently attested by this proof",
    note:"Confirmed onchain execution and Privi root; receipt alone does not establish USDC price, provider sponsorship or commercial revenue."
  };
}

export async function main(argv=process.argv.slice(2)) {
  try {
    const value = flag => {const i=argv.indexOf(flag); return i >= 0 ? argv[i+1] : undefined;};
    const proof = {root:value("--root"), txHash:value("--tx"),userOpHash:value("--userop"),sender:value("--sender")};
    assert(Object.values(proof).every(Boolean), "Usage: node verify.mjs --root HASH --tx TX_HASH --userop USEROP_HASH --sender ADDRESS [--rpc HTTPS_URL]");
    const url = value("--rpc") || "https://mainnet.base.org";
    assert(/^https:\/\//.test(url), "RPC must use HTTPS");
    const client = createPublicClient({chain:base,transport:http(url)});
    const result = await verifyPriviUserOp(proof,client);
    process.stdout.write(JSON.stringify(result,null,2)+"\n");
    return 0;
  } catch(e) {
    process.stderr.write(JSON.stringify({verified:false,reason:String(e?.message||e)})+"\n");
    return 1;
  }
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exitCode = await main();
}
