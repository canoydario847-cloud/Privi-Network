"use strict";
/*
 * READ-ONLY PRVI fee economics research for valueless Privi developer EVM.
 * No production node mutation, arbitrary fees, wallet signing, transfers,
 * issuance, treasury credit, financial mainnet or consensus implementation.
 *
 * IMPORTANT: "total gas paid" != "network operator revenue". The base fee
 * may be burned, tips may go to validators, fees may be refunded, and a
 * protocol treasury earns only amounts proved by ACTUAL bank state changes.
 * EIP-1559 routes require separate pinned Cosmos EVM source-level audits.
 */
const CHAIN_ID=262144;
const OWNER="0x1990589FD200E043b8C6FD9ec5956c61b3071048";
const DEC=/^(?:0|[1-9][0-9]*)$/;
const HEX=/^0x[0-9a-f]+$/i;
const HASH=/^0x[0-9a-fA-F]{64}$/;
function need(ok,message){if(!ok)throw Error(message)}
function unsigned(value,label,{nonZero=false}={}){
  const ok=typeof value==="bigint"?value>=0n:
    typeof value==="string"&&(DEC.test(value)||HEX.test(value));
  need(ok,"Invalid unsigned "+label);
  const n=BigInt(value);
  need(n<=(1n<<256n)-1n, "Excessive "+label);
  need(!nonZero||n>0n, "Zero "+label);
  return n;
}
function bps(value,label){
  need(Number.isSafeInteger(value)&&value>=0&&value<=10000,"Invalid "+label+" basis points");
  return BigInt(value);
}
function checkNetwork(chainId,genesisHash){
  need(chainId===CHAIN_ID,"Only valueless Privi developer-chain fee evidence allowed");
  need(typeof genesisHash==="string"&&HASH.test(genesisHash),"Pinned developer genesis hash required");
}
function feeFromReceipt(receipt){
  need(receipt&&typeof receipt==="object"&&!Array.isArray(receipt),"Receipt required");
  need(typeof receipt.transactionHash==="string"&&HASH.test(receipt.transactionHash),
    "Fee receipt transaction hash missing");
  need(receipt.status==="0x1"||receipt.status==="0x0",
    "Only finalized successful or failed transactions have charged gas");
  need(typeof receipt.blockHash==="string"&&HASH.test(receipt.blockHash),
    "Canonical block hash proof reference required");
  const gas=unsigned(receipt.gasUsed,"gas used",{nonZero:true});
  const price=unsigned(receipt.effectiveGasPrice,"effective gas price",{nonZero:true});
  need(gas<=30000000n,"Gas usage is above the dev observation policy limit");
  return Object.freeze({txHash:receipt.transactionHash.toLowerCase(),blockHash:receipt.blockHash.toLowerCase(),
    gasUsed:gas.toString(),effectiveGasPriceWei:price.toString(),
    chargedWei:(gas*price).toString(),executionSucceeded:receipt.status==="0x1"});
}
function aggregateFeeReceipts({chainId,genesisHash,receipts}){
  checkNetwork(chainId,genesisHash);
  need(Array.isArray(receipts)&&receipts.length>0&&receipts.length<=10000,
    "Fee observation batch must contain 1..10000 receipts");
  const used=new Set(),lines=[];let total=0n,successful=0,failed=0;
  for(const receipt of receipts){
    const row=feeFromReceipt(receipt);
    need(!used.has(row.txHash),"Duplicate fee transaction observation");
    used.add(row.txHash);total+=BigInt(row.chargedWei);lines.push(row);
    if(row.executionSucceeded)successful++;else failed++;
  }
  return Object.freeze({chainId,genesisHash,receiptCount:lines.length,
    successfulTransactions:successful,failedTransactions:failed,
    observedChargedGasWei:total.toString(),rawReceiptEvidence:lines,
    verifiedCollectorRevenueWei:null,
    reason:"Receipts alone do NOT prove burned fees, validator income, or treasury balance deltas",
    evidenceLevel:"USER_SUPPLIED_DEV_RECEIPTS_NOT_INDEPENDENTLY_VALIDATED",
    financialMainnet:false});
}
/** Arithmetic of caller-supplied allocations is NOT authenticated bank-state evidence. */
function reconcileActualFeeAllocation({observedChargedGasWei,actualBurnedWei,
  actualValidatorPaymentsWei,actualTreasuryReceiptsWei,actualOtherDestinationsWei}){
  const paid=unsigned(observedChargedGasWei,"gas charged");
  const burned=unsigned(actualBurnedWei,"actual burned fee");
  const validators=unsigned(actualValidatorPaymentsWei,"actual validator allocation");
  const treasury=unsigned(actualTreasuryReceiptsWei,"actual treasury receipt");
  const other=unsigned(actualOtherDestinationsWei,"other actual fee destinations");
  need(burned+validators+treasury+other===paid,
    "Fee accounting mismatch: no invented treasury revenue or untracked burned gas");
  return Object.freeze({chargedWei:paid.toString(),
    reportedBurnedWei:burned.toString(),
    reportedValidatorAllocationWei:validators.toString(),
    reportedTreasuryAllocationWei:treasury.toString(),
    reportedOtherDestinationsWei:other.toString(),
    treasuryRevenueWei:null,verifiedBurnedWei:null,verifiedValidatorPaymentsWei:null,
    evidenceLevel:"UNVERIFIED_CALLER_SUPPLIED_ALLOCATIONS",
    note:"Balanced caller-supplied allocations are NOT authenticated SDK bank-state fee destinations"});
}
/**
 * Advisory quotes only. Caller-signed fee caps always win. Raising prices
 * to maximize a single transaction is not a recommendation to overcharge.
 */
function advisoryEip1559Quote({baseFeeWei,priorityFeeWei,customerMaxFeePerGasWei,
   estimatedGas,customerMaxTotalWei}){
  const base=unsigned(baseFeeWei,"base fee"),priority=unsigned(priorityFeeWei,"priority fee");
  const customerMax=unsigned(customerMaxFeePerGasWei,"customer max fee per gas",{nonZero:true});
  const gas=unsigned(estimatedGas,"estimated gas",{nonZero:true});
  const budget=unsigned(customerMaxTotalWei,"customer fee budget",{nonZero:true});
  need(gas<=1000000n,"Do not quote runaway gas consumption");
  need(base<=customerMax,"Network base fee exceeds customer-approved limit");
  // EIP1559 effective price is bounded by the customer's maximum.
  const effective=(base+priority>customerMax)?customerMax:base+priority;
  // The observed effective price can rise before inclusion. A transaction
  // may spend as much as gasLimit * maxFeePerGas, not gasLimit * this quote.
  const estimatedCharged=gas*effective;
  const worstCaseCharged=gas*customerMax;
  need(worstCaseCharged<=budget,"Worst-case fee quote exceeds customer's signed budget");
  return Object.freeze({quotedGasPriceWei:effective.toString(),
    estimatedQuotedGasWei:estimatedCharged.toString(),
    maxQuotedGasWei:worstCaseCharged.toString(),
    requiredGasLimit:gas.toString(),requiredMaxFeePerGasWei:customerMax.toString(),
    baseFeeWei:base.toString(),includedTipWei:(effective-base).toString(),
    mayChangeBeforeInclusion:true,noOnchainEnforcement:true});
}
/**
 * ECONOMICS WHAT-IF: revenue volume is manually assumed, not a forecast
 * from actual demand. Assumed retained BPS is not an observed fee route.
 */
function modelRevenueScenario({label,transactionsPerDay,averageGasUsed,
  averageEffectiveGasPriceWei,assumedTreasuryRetentionBps,
  averageCustomerFeeCeilingWei}){
  need(typeof label==="string"&&/^[A-Za-z0-9 _-]{1,70}$/.test(label),"Invalid scenario label");
  const txs=unsigned(transactionsPerDay,"transactions/day",{nonZero:true});
  const gas=unsigned(averageGasUsed,"average gas used",{nonZero:true});
  const price=unsigned(averageEffectiveGasPriceWei,"average gas price",{nonZero:true});
  const cap=unsigned(averageCustomerFeeCeilingWei,"customer ceiling",{nonZero:true});
  const retention=bps(assumedTreasuryRetentionBps,"assumed treasury retention");
  need(txs<=1000000000n,"Unfounded transaction throughput assumption");
  need(gas<=1000000n,"Invalid gas-use scenario");
  const perTx=gas*price;
  need(perTx<=cap,"Scenario violates assumed customer price tolerance");
  const dailyGross=txs*perTx;
  const retained=dailyGross*retention/10000n;
  return Object.freeze({label,assumedTxPerDay:txs.toString(),
    assumedAverageGasPerTx:gas.toString(),
    assumedUserFeePerTxWei:perTx.toString(),
    projectedDailyGrossGasFeesWei:dailyGross.toString(),
    projectedDailyTreasuryWei:retained.toString(),
    projected30DayTreasuryWei:(retained*30n).toString(),
    assumptionsNotFacts:true,priceElasticityNotModeled:true,
    noActualCollectorPolicyDeployed:true});
}
function compareScenarios(scenarios){
  need(Array.isArray(scenarios)&&scenarios.length>0&&scenarios.length<=15,
    "Specify 1..15 labeled and independently assumed fee scenarios");
  const results=scenarios.map(modelRevenueScenario);
  const ordered=results.slice().sort((a,b)=>{
    const x=BigInt(a.projectedDailyTreasuryWei),y=BigInt(b.projectedDailyTreasuryWei);
    return x===y?a.label.localeCompare(b.label):x>y?-1:1;
  });
  return Object.freeze({recommendedForFurtherTesting:ordered[0].label,
    results:ordered,
    caution:"A simulation cannot prove future usage, fee retention, competitor leadership, or investment return",
    financialMainnet:false});
}
module.exports={CHAIN_ID,OWNER,feeFromReceipt,aggregateFeeReceipts,
  reconcileActualFeeAllocation,advisoryEip1559Quote,
  modelRevenueScenario,compareScenarios};
