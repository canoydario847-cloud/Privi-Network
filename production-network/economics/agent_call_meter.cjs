"use strict";
// Privi Agent Call Meter: offline, nonfinancial developer policy only.
// No wallet custody, onchain settlement, signature verification, or deployed PoP.
const {advisoryEip1559Quote}=require("./gas_market.cjs");
const DEC=/^(0|[1-9][0-9]*)$/;
function amount(x,label){if(typeof x!=="string"||!DEC.test(x))throw Error("Invalid "+label);const n=BigInt(x);if(n>(1n<<256n)-1n)throw Error("Overflow "+label);return n;}
function quoteAgentCall({agentId,callId,requestedCalls,unitServiceFeeWei,customerMaxServiceFeeWei,customerMaxCombinedWei,gas}) {
  if(typeof agentId!=="string"||!/^[a-zA-Z0-9._-]{1,80}$/.test(agentId))throw Error("Invalid agent ID");
  if(typeof callId!=="string"||!/^[a-zA-Z0-9._-]{1,80}$/.test(callId))throw Error("Invalid call ID");
  const calls=amount(requestedCalls,"calls"),unit=amount(unitServiceFeeWei,"unit fee");
  if(calls<1n||calls>1000n)throw Error("Call count exceeds policy");
  const service=calls*unit;
  if(service>amount(customerMaxServiceFeeWei,"service cap"))throw Error("Service fee exceeds customer cap");
  const gasQuote=advisoryEip1559Quote(gas);
  const quotedCombined=service+BigInt(gasQuote.maxQuotedGasWei);
  // Future EIP-1559 inclusion can charge up to the transaction's signed
  // maxFeePerGas, not merely the current base+priority estimate.
  const authorizedCombined=service+BigInt(gasQuote.maxAuthorizedGasWei);
  if(authorizedCombined>amount(customerMaxCombinedWei,"combined cap"))throw Error("Combined fee exceeds customer cap");
  return Object.freeze({agentId,callId,calls:calls.toString(),serviceFeeWei:service.toString(),
    maxQuotedGasWei:gasQuote.maxQuotedGasWei,
    maxAuthorizedGasWei:gasQuote.maxAuthorizedGasWei,
    quotedCombinedWei:quotedCombined.toString(),maxCombinedWei:authorizedCombined.toString(),
    feeCurrency:"DEV_CHAIN_NATIVE_UNIT",financialMainnet:false,settled:false,
    customerAuthorizationVerified:false,signatureVerificationRequiredBeforeExecution:true,
    onchainEnforcement:false,treasuryRevenueWei:null,
    note:"A quote is not a payment or verified network revenue; agent calls require separate authorization and metering."});
}
/**
 * In-memory replay gate for disposable tests only. Not durable, distributed,
 * cryptographically authenticated, or an onchain settlement proof.
 * A caller MUST verify a signed authorization before invoking this gate.
 */
function createEphemeralCallGate(){
 const seen=new Set();
 return Object.freeze({accept({agentId,callId,authorizationVerified,quote}){
  if(authorizationVerified!==true)throw Error("Verified authorization required");
  if(!quote||quote.agentId!==agentId||quote.callId!==callId||
     quote.financialMainnet!==false||quote.settled!==false)
    throw Error("Call does not match nonfinancial quote");
  const key=JSON.stringify([agentId,callId]);
  if(seen.has(key))throw Error("Duplicate agent call replay");
  seen.add(key);
  return Object.freeze({accepted:true,agentId,callId,settled:false,
    authorizationEvidenceExternallyProvided:true,
    replayScope:"PROCESS_MEMORY_ONLY",treasuryRevenueWei:null});
 }});
}
module.exports={quoteAgentCall,createEphemeralCallGate};
