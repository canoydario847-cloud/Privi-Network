"use strict";
/*
 * Privi PoP deterministic state-binding RESEARCH ONLY.
 * Non-financial toy counter application. No wallet, token transfer, staking,
 * minting, IoT production data, actual ABCI state, or live validator changes.
 *
 * Guarantees only: given an externally pinned starting state digest and
 * separately authenticated research checkpoint CLAIM, every supplied block
 * reproduces its signed candidate hash from bounded canonical operations
 * and deterministic state transition results. Neither the state nor the
 * checkpoint is shown to be canonical/financially finalized.
 */
const {hash,assertValidatedCommittee}=require("./engine.cjs");
const {verifyAttestedCandidateAncestry}=require("./checkpoint_attestation.cjs");
const APP_DOMAIN="Privi/PoP/Research/ToyCounterState/2026/v1";
const ACCOUNT=/^[a-z][a-z0-9_-]{1,31}$/;
const HEX=/^0x[0-9a-f]{64}$/;
const MAX_ACCOUNTS=128,MAX_OPS=64,MAX_BLOCKS=64,MAX_DELTA=1000000;
const BLOCK_FIELDS=["blockHash","height","operations","operationsRoot","previousBlockHash","stateRoot"];
const OP_FIELDS=["account","amount","kind","nonce"];
function need(ok,why){if(!ok)throw Error(why);}
function plain(x){return x!==null&&typeof x==="object"&&!Array.isArray(x)&&
  Object.getPrototypeOf(x)===Object.prototype;}
function exactFields(obj,fields,label){
  // Commitments must reject unsigned hidden/symbol metadata and accessors
  // before reading any operation, state-record or block field.
  need(plain(obj)&&Reflect.ownKeys(obj).length===fields.length&&
       fields.every(k=>{
         const d=Object.getOwnPropertyDescriptor(obj,k);
         return d&&Object.hasOwn(d,"value")&&d.enumerable;
       }),"PoP toy "+label+" invalid or unexpected fields");
}
function integer(x,label,allowZero=true){
  need(Number.isSafeInteger(x)&&x>=(allowZero?0:1),
       "PoP toy invalid safe integer: "+label);
}
function normalizedState(input){
  need(plain(input),"PoP toy state must have at most 128 plain-object accounts");
  // A starting-state commitment must not silently ignore nonenumerable or
  // symbol metadata, nor execute an untrusted account getter before hashing.
  const accounts=Reflect.ownKeys(input);
  need(accounts.length<=MAX_ACCOUNTS,
       "PoP toy state must have at most 128 plain-object accounts");
  const output=new Map();
  for(const account of accounts){
    const descriptor=Object.getOwnPropertyDescriptor(input,account);
    need(typeof account==="string" && descriptor &&
         Object.hasOwn(descriptor,"value") && descriptor.enumerable,
         "PoP toy state requires plain enumerable own account data fields");
    need(ACCOUNT.test(account),"PoP toy invalid account key");
    const entry=descriptor.value;
    exactFields(entry,["nonce","value"],"state record");
    integer(entry.value,"state value");integer(entry.nonce,"state nonce");
    output.set(account,{value:entry.value,nonce:entry.nonce});
  }
  return output;
}
function stateEntries(map){
  return [...map.entries()].sort(([a],[b])=>a<b?-1:a>b?1:0)
    .map(([name,v])=>[name,v.value,v.nonce]);
}
function digest(label,value){
  return hash(Buffer.from(APP_DOMAIN+"\n"+label+"\n"+JSON.stringify(value),"utf8"));
}
function stateRoot(state){
  return digest("state",stateEntries(normalizedState(state)));
}
function snapshot(map) {
  // Keep ordinary JSON-compatible objects for strict revalidation on each height.
  const result={};
  for(const [k,v] of map)result[k]=Object.freeze({value:v.value,nonce:v.nonce});
  return Object.freeze(result);
}
function applyOps(state,operations){
  const length=operations?.length;
  need(Array.isArray(operations)&&Number.isSafeInteger(length)&&length>=1&&
       length<=MAX_OPS,"PoP toy requires 1..64 operations per block");
  // Read each validated own data descriptor exactly once. Iterating the
  // caller's array or indexing it afterward could execute a Proxy's forged
  // Symbol.iterator/index getter and commit to different unsigned operations.
  need(Object.getPrototypeOf(operations)===Array.prototype &&
       Reflect.ownKeys(operations).length===length+1,
       "PoP toy requires a dense plain operation array without unsigned metadata or accessors");
  const accepted=[];
  for(let i=0;i<length;i++){
    const d=Object.getOwnPropertyDescriptor(operations,String(i));
    need(d&&Object.hasOwn(d,"value")&&d.enumerable,
         "PoP toy requires a dense plain operation array without unsigned metadata or accessors");
    accepted.push(d.value);
  }
  const next=normalizedState(state),serialized=[];
  for(const op of accepted){
    exactFields(op,OP_FIELDS,"operation");
    need(op.kind==="increment","PoP toy unsupported/non-financial operation");
    need(typeof op.account==="string"&&ACCOUNT.test(op.account),
         "PoP toy invalid operation account");
    integer(op.amount,"increment amount",false);
    need(op.amount<=MAX_DELTA,"PoP toy increment exceeds test-only limit");
    integer(op.nonce,"operation nonce",false);
    const old=next.get(op.account)||{value:0,nonce:0};
    need(old.nonce<Number.MAX_SAFE_INTEGER&&op.nonce===old.nonce+1,
         "PoP toy replayed, missing or reordered operation nonce");
    need(old.value<=Number.MAX_SAFE_INTEGER-op.amount,
         "PoP toy counter overflow");
    need(next.has(op.account)||next.size<MAX_ACCOUNTS,
         "PoP toy account limit exceeded");
    next.set(op.account,{value:old.value+op.amount,nonce:op.nonce});
    serialized.push([op.kind,op.account,op.amount,op.nonce]);
  }
  return {nextState:snapshot(next),operationsRoot:digest("operations",serialized)};
}
function computeResearchBlock(committee,state,height,previousBlockHash,operations){
  assertValidatedCommittee(committee);
  integer(height,"height",false);
  need(typeof previousBlockHash==="string"&&HEX.test(previousBlockHash),
       "PoP toy previous-block hash invalid");
  const {nextState,operationsRoot}=applyOps(state,operations);
  const nextStateRoot=stateRoot(nextState);
  const blockHash=digest("block",[
    committee.chainId,committee.genesisHash,committee.epoch,height,
    previousBlockHash,operationsRoot,nextStateRoot
  ]);
  need(blockHash!==previousBlockHash,"PoP toy self-referencing block");
  return Object.freeze({
    block:Object.freeze({
      height,previousBlockHash,operations,operationsRoot,
      stateRoot:nextStateRoot,blockHash
    }),
    nextState
  });
}
function verifyResearchStateSequence(committee,signedCheckpoint,
                                     trustedGovernancePublicKey,startingState,
                                     expectedStartingStateRoot,certificates,blocks){
  assertValidatedCommittee(committee);
  need(typeof expectedStartingStateRoot==="string"&&HEX.test(expectedStartingStateRoot),
       "PoP toy externally expected initial state root invalid");
  const initialRoot=stateRoot(startingState);
  need(initialRoot===expectedStartingStateRoot,
       "PoP toy starting state does not match independently supplied expected root");
  need(Array.isArray(blocks)&&blocks.length>=1&&blocks.length<=MAX_BLOCKS,
       "PoP toy block list must have 1..64 entries");
  need(Array.isArray(certificates)&&blocks.length===certificates.length,
       "PoP toy block/certificate count mismatch");
  // This authenticates an issuer assertion, and verifies each committee
  // Ed25519 quorum + contiguous candidate hash before toy execution.
  const candidateProof=verifyAttestedCandidateAncestry(
    committee,signedCheckpoint,trustedGovernancePublicKey,certificates);
  let nextState=snapshot(normalizedState(startingState));
  for(let index=0;index<blocks.length;index++){
    const actual=blocks[index],signed=certificates[index].proposal;
    exactFields(actual,BLOCK_FIELDS,"candidate block");
    const expected=computeResearchBlock(
      committee,nextState,signed.height,signed.previousBlockHash,
      actual.operations
    );
    need(actual.height===signed.height&&
         actual.previousBlockHash===signed.previousBlockHash,
         "PoP toy candidate header does not match signed proposal");
    need(actual.operationsRoot===expected.block.operationsRoot,
         "PoP toy operations root mismatch");
    need(actual.stateRoot===expected.block.stateRoot,
         "PoP toy claimed state root mismatch");
    need(actual.blockHash===expected.block.blockHash &&
         signed.blockHash===expected.block.blockHash,
         "PoP toy signed block hash does not bind deterministic application execution");
    nextState=expected.nextState;
  }
  return Object.freeze({
    researchOnly:true,
    nonFinancialToyState:true,
    productionConsensus:false,
    finalized:false,
    validatesLiveCosmosEvmState:false,
    checkpointFinalityVerified:false,
    startingStateExternallyAuthenticated:false,
    verifiedToyTransitions:blocks.length,
    endingHeight:candidateProof.endingHeight,
    endingBlockHash:candidateProof.endingBlockHash,
    startingStateRoot:initialRoot,
    endingStateRoot:stateRoot(nextState),
    // Snapshot is a toy counter state for test inspection; no real balances.
    endingState:nextState,
    warning:"Verified deterministic toy counter execution bound to research signed votes only. Neither canonical state, external checkpoint, live PoP consensus nor financial PRVI finality is proven."
  });
}
module.exports={
  APP_DOMAIN,MAX_ACCOUNTS,MAX_OPS,MAX_BLOCKS,
  stateRoot,computeResearchBlock,verifyResearchStateSequence
};
