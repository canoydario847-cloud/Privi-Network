"use strict";
const test=require("node:test"),assert=require("node:assert/strict");
const {quoteAgentCall,createEphemeralCallGate}=require("./agent_call_meter.cjs");
const base={agentId:"mr-lee",callId:"task-001",requestedCalls:"2",unitServiceFeeWei:"100",
 customerMaxServiceFeeWei:"200",customerMaxCombinedWei:"252200",
 gas:{baseFeeWei:"10",priorityFeeWei:"2",customerMaxFeePerGasWei:"15",estimatedGas:"21000",customerMaxTotalWei:"300000"}};
test("agent quote separates service fee and network gas without asserting revenue",()=>{
 const q=quoteAgentCall(base);
 assert.equal(q.serviceFeeWei,"200");assert.equal(q.maxQuotedGasWei,"252000");
 assert.equal(q.maxCombinedWei,"252200");assert.equal(q.treasuryRevenueWei,null);
 assert.equal(q.settled,false);assert.equal(q.customerAuthorizationVerified,false);
});
test("reject service and combined cap overruns",()=>{
 assert.throws(()=>quoteAgentCall({...base,customerMaxServiceFeeWei:"199"}),/service fee exceeds customer cap/i);
 assert.throws(()=>quoteAgentCall({...base,customerMaxCombinedWei:"252199"}),/combined fee exceeds customer cap/i);
});
test("reject invalid call counts, identifiers, and gas caps",()=>{
 assert.throws(()=>quoteAgentCall({...base,requestedCalls:"1001"}),/Call count/);
 assert.throws(()=>quoteAgentCall({...base,requestedCalls:"-1"}),/Invalid/);
 assert.throws(()=>quoteAgentCall({...base,agentId:"../unsafe"}),/Invalid agent/);
 assert.throws(()=>quoteAgentCall({...base,gas:{...base.gas,customerMaxTotalWei:"100"}}),/signed budget/);
});

test("authorized call replay gate rejects duplicates and mismatched quote",()=>{
 const gate=createEphemeralCallGate(),quote=quoteAgentCall(base);
 const req={agentId:base.agentId,callId:base.callId,quote,authorizationVerified:true};
 assert.throws(()=>gate.accept({...req,authorizationVerified:false}),/Verified authorization/);
 assert.throws(()=>gate.accept({...req,callId:"other"}),/does not match/);
 const first=gate.accept(req);assert.equal(first.accepted,true);
 assert.equal(first.settled,false);assert.equal(first.treasuryRevenueWei,null);
 assert.equal(first.replayScope,"PROCESS_MEMORY_ONLY");
 assert.throws(()=>gate.accept(req),/Duplicate agent call replay/);
});
