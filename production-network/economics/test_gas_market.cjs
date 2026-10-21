"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const {
  CHAIN_ID,OWNER,feeFromReceipt,aggregateFeeReceipts,
  reconcileActualFeeAllocation,advisoryEip1559Quote,
  modelRevenueScenario,compareScenarios
}=require("./gas_market.cjs");
const genesis="0x"+"a".repeat(64);
const receipt=(n,gas="0x5208",price="0x3b9aca00",status="0x1")=>({
  transactionHash:"0x"+n.toString(16).padStart(64,"0"),
  blockHash:"0x"+"f".repeat(64),gasUsed:gas,effectiveGasPrice:price,status
});
test("real EVM receipt math accounts for failed as well as successful paid gas",()=>{
  const r=aggregateFeeReceipts({
    chainId:CHAIN_ID,genesisHash:genesis,
    receipts:[receipt(1),receipt(2,"0x5208","0x3b9aca00","0x0")]
  });
  assert.equal(r.receiptCount,2);
  assert.equal(r.successfulTransactions,1);
  assert.equal(r.failedTransactions,1);
  assert.equal(r.observedChargedGasWei,"42000000000000");
  assert.equal(r.verifiedCollectorRevenueWei,null,
    "gas paid must not be misreported as Privi treasury income");
  assert.equal(r.financialMainnet,false);
  assert.equal(OWNER,"0x1990589FD200E043b8C6FD9ec5956c61b3071048");
});
test("receipts cannot fake an external chain, missing confirmation or duplicate events",()=>{
  const valid={chainId:CHAIN_ID,genesisHash:genesis,receipts:[receipt(1)]};
  assert.throws(()=>aggregateFeeReceipts({...valid,chainId:56}),/developer-chain/);
  assert.throws(()=>aggregateFeeReceipts({...valid,genesisHash:"bad"}),/genesis/);
  assert.throws(()=>aggregateFeeReceipts({...valid,receipts:[receipt(1),receipt(1)]}),/Duplicate/);
  assert.throws(()=>aggregateFeeReceipts({...valid,receipts:[{...receipt(1),blockHash:"0x12"}]}),/block hash/);
  assert.throws(()=>aggregateFeeReceipts({...valid,receipts:[{...receipt(1),status:null}]}),/finalized/);
  assert.throws(()=>aggregateFeeReceipts({...valid,receipts:[{...receipt(1),effectiveGasPrice:"0x0"}]}),/Zero/);
  assert.throws(()=>aggregateFeeReceipts({...valid,receipts:[{...receipt(1),gasUsed:"-1"}]}),/Invalid unsigned/);
});
test("treasury revenue can be claimed only if all actual allocations reconcile",()=>{
  assert.deepEqual(
    reconcileActualFeeAllocation({
      observedChargedGasWei:"10000",actualBurnedWei:"4000",
      actualValidatorPaymentsWei:"2000",actualTreasuryReceiptsWei:"3000",
      actualOtherDestinationsWei:"1000"
    }).treasuryRevenueWei,"3000");
  assert.throws(()=>reconcileActualFeeAllocation({
      observedChargedGasWei:"10000",actualBurnedWei:"4000",
      actualValidatorPaymentsWei:"2000",actualTreasuryReceiptsWei:"6000",
      actualOtherDestinationsWei:"0"
    }),/mismatch/);
  assert.throws(()=>reconcileActualFeeAllocation({
      observedChargedGasWei:"10000",actualBurnedWei:"4000",
      actualValidatorPaymentsWei:"2000",actualTreasuryReceiptsWei:undefined,
      actualOtherDestinationsWei:"4000"
    }),/Invalid unsigned/);
});
test("advisory EIP-1559 quotes preserve a customer maximum rather than maximize a fee",()=>{
  const good=advisoryEip1559Quote({baseFeeWei:"10",priorityFeeWei:"2",
    customerMaxFeePerGasWei:"15",estimatedGas:"21000",customerMaxTotalWei:"350000"});
  assert.equal(good.quotedGasPriceWei,"12");
  assert.equal(good.estimatedQuotedGasWei,"252000");
  assert.equal(good.maxQuotedGasWei,"315000");
  assert.equal(good.requiredGasLimit,"21000");
  assert.equal(good.requiredMaxFeePerGasWei,"15");
  assert.equal(good.includedTipWei,"2");
  const capped=advisoryEip1559Quote({baseFeeWei:"10",priorityFeeWei:"100",
    customerMaxFeePerGasWei:"15",estimatedGas:"21000",customerMaxTotalWei:"400000"});
  assert.equal(capped.quotedGasPriceWei,"15");
  assert.equal(capped.includedTipWei,"5");
  // A low observed effective price must not conceal the signed max-fee risk.
  assert.throws(()=>advisoryEip1559Quote({baseFeeWei:"10",priorityFeeWei:"2",
    customerMaxFeePerGasWei:"15",estimatedGas:"21000",customerMaxTotalWei:"252000"}),
    /Worst-case fee quote exceeds customer's signed budget/);
  const exact=advisoryEip1559Quote({baseFeeWei:"10",priorityFeeWei:"2",
    customerMaxFeePerGasWei:"15",estimatedGas:"21000",customerMaxTotalWei:"315000"});
  assert.equal(exact.maxQuotedGasWei,"315000");
  assert.throws(()=>advisoryEip1559Quote({baseFeeWei:"20",priorityFeeWei:"1",
    customerMaxFeePerGasWei:"15",estimatedGas:"21000",customerMaxTotalWei:"900000"}),/exceeds customer/);
  assert.throws(()=>advisoryEip1559Quote({baseFeeWei:"10",priorityFeeWei:"5",
    customerMaxFeePerGasWei:"20",estimatedGas:"21000",customerMaxTotalWei:"200000"}),/signed budget/);
});
test("economic scenarios distinguish volume from expensive single transaction",()=>{
  const options=compareScenarios([
    {label:"High-fees-low-usage",transactionsPerDay:"100",
      averageGasUsed:"50000",averageEffectiveGasPriceWei:"100",
      assumedTreasuryRetentionBps:2000,averageCustomerFeeCeilingWei:"5000000"},
    {label:"Affordable-broad-adoption",transactionsPerDay:"10000",
      averageGasUsed:"50000",averageEffectiveGasPriceWei:"10",
      assumedTreasuryRetentionBps:2000,averageCustomerFeeCeilingWei:"500000"}
  ]);
  assert.equal(options.recommendedForFurtherTesting,"Affordable-broad-adoption");
  assert.equal(options.results[0].projectedDailyGrossGasFeesWei,"5000000000");
  assert.equal(options.results[0].projectedDailyTreasuryWei,"1000000000");
  assert.equal(options.results[0].projected30DayTreasuryWei,"30000000000");
  assert.equal(options.financialMainnet,false);
  assert.equal(options.results[0].assumptionsNotFacts,true);
  assert.throws(()=>modelRevenueScenario({
    label:"Predatory",transactionsPerDay:"100",averageGasUsed:"50000",
    averageEffectiveGasPriceWei:"100",assumedTreasuryRetentionBps:2000,
    averageCustomerFeeCeilingWei:"100"
  }),/customer price tolerance/);
  assert.throws(()=>modelRevenueScenario({
    label:"Fake guarantee",transactionsPerDay:"100",averageGasUsed:"50000",
    averageEffectiveGasPriceWei:"100",assumedTreasuryRetentionBps:12000,
    averageCustomerFeeCeilingWei:"5000000"
  }),/basis points/);
});
