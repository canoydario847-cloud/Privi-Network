"use strict";
/* Read-only crosscheck: two auditors of the same disposable RPC are not independent bank-state proof. */
const HASH=/^0x[0-9a-fA-F]{64}$/;
const DEC=/^(?:0|[1-9][0-9]*)$/;
function check(ok,message){if(!ok)throw Error(message)}
function quantity(value,label){
  check(typeof value==="string"&&DEC.test(value),"Invalid decimal "+label);
  const n=BigInt(value);
  check(n<=(1n<<256n)-1n,"Invalid range "+label);
  return n;
}
function assertReceiptAuditAgreement(observation,audit){
  check(observation&&observation.financialMainnet===false&&observation.chainId===262144&&observation.receiptCount===1,
    "Expected one valueless developer receipt observation");
  check(audit&&audit.ok===true&&audit.evm_chain_id===262144&&
    Number.isSafeInteger(audit.confirmations)&&audit.confirmations>=2,
    "Auditor chain identity or confirmations invalid");
  check(Array.isArray(observation.rawReceiptEvidence)&&observation.rawReceiptEvidence.length===1,
    "Receipt observation missing");
  const row=observation.rawReceiptEvidence[0];
  check(row&&typeof row==="object","Receipt observation invalid");
  // The Python native-transfer auditor rejects failed receipts; a gross-fee
  // match must never hide a conflicting failed EVM execution status.
  check(row.executionSucceeded===true&&audit.execution_succeeded===true,"Auditor execution status mismatch");
  check(typeof row.txHash==="string"&&HASH.test(row.txHash)&&
    typeof audit.tx_hash==="string"&&HASH.test(audit.tx_hash)&&
    audit.tx_hash.toLowerCase()===row.txHash.toLowerCase(),"Auditor transaction hash mismatch");
  check(typeof row.blockHash==="string"&&HASH.test(row.blockHash)&&
    typeof audit.block_hash==="string"&&HASH.test(audit.block_hash)&&
    audit.block_hash.toLowerCase()===row.blockHash.toLowerCase(),"Auditor block hash mismatch");
  const gas=quantity(row.gasUsed,"observed gas"),price=quantity(row.effectiveGasPriceWei,"observed price");
  check(quantity(audit.gas_used,"audited gas")===gas,"Auditor gas usage mismatch");
  check(quantity(audit.effective_gas_price_wei,"audited price")===price,"Auditor effective gas price mismatch");
  const charged=quantity(observation.observedChargedGasWei,"aggregate gross fee");
  check(quantity(audit.gross_gas_paid_wei,"audited gross fee")===charged&&
    quantity(row.chargedWei,"receipt gross fee")===charged&&gas*price===charged,
    "Auditor gross fee mismatch");
  check(typeof observation.genesisHash==="string"&&HASH.test(observation.genesisHash)&&
    typeof audit.genesis_hash==="string"&&HASH.test(audit.genesis_hash)&&
    observation.genesisHash.toLowerCase()===audit.genesis_hash.toLowerCase(),
    "Developer genesis hash mismatch or missing");
  check(observation.evidenceLevel==="USER_SUPPLIED_DEV_RECEIPTS_NOT_INDEPENDENTLY_VALIDATED",
    "Receipt observation evidence level missing or overstated");
  check(observation.verifiedCollectorRevenueWei===null,
    "No collector revenue may be inferred from a receipt");
  return Object.freeze({ok:true,devOnly:true,grossGasPaidWei:charged.toString(),
    treasuryRevenueWei:null,evidenceLevel:"TWO_IMPLEMENTATIONS_SAME_LOCAL_RPC"});
}
module.exports={assertReceiptAuditAgreement};
