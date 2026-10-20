"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const {assertReceiptAuditAgreement}=require("./receipt_crosscheck.cjs");
const tx="0x"+"1".repeat(64),block="0x"+"2".repeat(64);
function valid(){
 return {
  observation:{financialMainnet:false,chainId:262144,genesisHash:"0x"+"5".repeat(64),receiptCount:1,successfulTransactions:1,failedTransactions:0,
   rawReceiptEvidence:[{txHash:tx,blockHash:block,gasUsed:"21000",effectiveGasPriceWei:"10000000000",chargedWei:"210000000000000",executionSucceeded:true}],
   observedChargedGasWei:"210000000000000",evidenceLevel:"USER_SUPPLIED_DEV_RECEIPTS_NOT_INDEPENDENTLY_VALIDATED",verifiedCollectorRevenueWei:null},
  audit:{ok:true,execution_succeeded:true,evm_chain_id:262144,genesis_hash:"0x"+"5".repeat(64),confirmations:2,tx_hash:tx,block_hash:block,
   gas_used:"21000",effective_gas_price_wei:"10000000000",gross_gas_paid_wei:"210000000000000"}
 };
}
test("valid dev receipt: gross fees only, no treasury inference",()=>{
 const {observation,audit}=valid();const result=assertReceiptAuditAgreement(observation,audit);
 assert.equal(result.grossGasPaidWei,"210000000000000");
 assert.equal(result.treasuryRevenueWei,null);
});
for(const [field,value] of [["gas_used","21001"],["effective_gas_price_wei","10000000001"],["gross_gas_paid_wei","210000000000001"],["block_hash","0x"+"3".repeat(64)],["tx_hash","0x"+"4".repeat(64)],["confirmations",1],["evm_chain_id",1]]){
 test("reject audit mismatch: "+field,()=>{
  const {observation,audit}=valid();audit[field]=value;
  assert.throws(()=>assertReceiptAuditAgreement(observation,audit));
 });
}
test("reject forged observation gross despite agreement between fields",()=>{
 const {observation,audit}=valid();observation.observedChargedGasWei="210000000000001";
 observation.rawReceiptEvidence[0].chargedWei="210000000000001";
 audit.gross_gas_paid_wei="210000000000001";
 assert.throws(()=>assertReceiptAuditAgreement(observation,audit),/gross fee mismatch/);
});
test("reject invented treasury income",()=>{
 const {observation,audit}=valid();observation.verifiedCollectorRevenueWei="1";
 assert.throws(()=>assertReceiptAuditAgreement(observation,audit));
});
test("reject malformed and excessive unsigned quantity",()=>{
 for(const value of ["-1","01","1.0",(1n<<256n).toString()]){
  const {observation,audit}=valid();audit.gas_used=value;
  assert.throws(()=>assertReceiptAuditAgreement(observation,audit));
 }
});

test("reject missing or overstated dev receipt evidence level",()=>{
 const {observation,audit}=valid();observation.evidenceLevel="INDEPENDENTLY_VERIFIED";
 assert.throws(()=>assertReceiptAuditAgreement(observation,audit));
});

test("reject absent pinned dev genesis",()=>{const {observation,audit}=valid();delete observation.genesisHash;assert.throws(()=>assertReceiptAuditAgreement(observation,audit));});

test("reject missing or mismatched audited genesis hash",()=>{
 for(const value of [undefined,"bad","0x"+"6".repeat(64)]){
  const {observation,audit}=valid();audit.genesis_hash=value;
  assert.throws(()=>assertReceiptAuditAgreement(observation,audit),/genesis hash/);
 }
});

test("reject failed or unknown execution despite matching gross gas",()=>{
 for(const value of [false,undefined,null,"true"]){
  const {observation,audit}=valid();observation.rawReceiptEvidence[0].executionSucceeded=value;
  assert.throws(()=>assertReceiptAuditAgreement(observation,audit),/execution status mismatch/);
 }
});

test("reject Python auditor failed or missing execution success",()=>{
 for(const value of [false,undefined,null,"true"]){
  const {observation,audit}=valid();audit.execution_succeeded=value;
  assert.throws(()=>assertReceiptAuditAgreement(observation,audit),/execution status mismatch/);
 }
});

test("reject inconsistent aggregate receipt execution counters",()=>{
 for(const [successful,failed] of [[0,1],[1,1],[2,0],[undefined,0],[1,undefined]]){
  const {observation,audit}=valid();
  observation.successfulTransactions=successful;observation.failedTransactions=failed;
  assert.throws(()=>assertReceiptAuditAgreement(observation,audit),/execution counters mismatch/);
 }
});
