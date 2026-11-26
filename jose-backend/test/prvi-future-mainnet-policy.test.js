import test from 'node:test';
import assert from 'node:assert/strict';
import {
  FUTURE_PRVI_INTEGRATION,
  PROPOSED_PRVI_STABLECOIN,
  PolicyPreviewError,
  previewUsageDollarReference,
} from '../src/prvi-future-mainnet-policy.js';

const sample={
  usageBaseline:1000,usageCurrent:1250,
  dollarIndexBaseline:100,dollarIndexCurrent:102,
  usageWeight:0.5,dollarWeight:0.5,
};
test('Future PRVI launch status remains fail-closed with unassigned production identity',()=>{
  const f=FUTURE_PRVI_INTEGRATION;
  assert.equal(Object.isFrozen(f),true);
  assert.equal(f.readiness,'NO_GO_AWAITING_INDEPENDENT_RELEASE_EVIDENCE');
  assert.equal(f.connected,false);
  assert.equal(f.financialMainnetLive,false);
  assert.equal(f.chainId,null);
  assert.equal(f.cosmosChainId,null);
  assert.equal(f.rpcUrl,null);
  assert.equal(f.walletSigningEnabled,false);
  assert.equal(f.mintingEnabled,false);
  assert.equal(f.paymentsEnabled,false);
  assert.equal(f.bridgingEnabled,false);
  assert.equal(f.automaticMigrationEnabled,false);
  assert.equal(f.pricePegActive,false);
  assert.equal(f.usdRedemptionGuaranteed,false);
  assert.equal(f.economicModelApproved,false);
  assert.equal(f.indexOracleConfigured,false);
  assert.equal(f.economicModel,'SELECTED_DESIGN_USD_REDEEMABLE_PAYMENT_STABLECOIN');
  assert.equal(f.selectedStablecoinDesign,'USD_REDEEMABLE_PAYMENT_STABLECOIN');
  assert.equal(f.proposedRedemptionUsdPerToken,1);
  assert.equal(f.issuerApprovalVerified,false);
  assert.equal(f.reservesVerified,false);
  assert.equal(f.reserveAttestationVerified,false);
  assert.equal(f.redemptionEnabled,false);
  assert.equal(f.issuanceAgainstReservesVerified,false);
  assert.equal(f.heyJoseUsageBacksToken,false);
  assert.equal(f.dollarFxIndexDeterminesTokenPrice,false);
  assert.equal(f.publicUserDataOnChain,false);
  assert.equal(f.upstreamDemoEvmId,262144);
  assert.equal(f.priviTestDevnetId,772626);
});
test('The indicative reference computes normalized math but never a PRVI price',()=>{
  const r=previewUsageDollarReference(sample);
  assert.ok(Math.abs(r.indexValue-100*Math.sqrt(1.25*1.02))<1e-9);
  assert.equal(r.baseValue,100);
  assert.equal(r.kind,'HYPOTHETICAL_NON_FINANCIAL_REFERENCE_INDEX');
  assert.equal(r.marketPriceUsd,null);
  assert.equal(r.tokenPricePredicted,false);
  assert.equal(r.pegEnforced,false);
  assert.equal(r.reservesVerified,false);
  assert.equal(r.oracleVerified,false);
  assert.equal(r.independentUsageAudit,false);
  assert.equal(r.mintingEnabled,false);
  assert.equal(r.financialMainnetLive,false);
  assert.equal(r.redemptionRightCreated,false);
});
test('Reference index stays 100 at baseline for arbitrary approved hypothetical weights',()=>{
  for(const w of [0,0.25,0.5,0.75,1]){
    const r=previewUsageDollarReference({...sample,
      usageCurrent:sample.usageBaseline,
      dollarIndexCurrent:sample.dollarIndexBaseline,
      usageWeight:w,dollarWeight:1-w
    });
    assert.equal(r.indexValue,100);
  }
});
test('Reference accepts zero observed usage only when usage actually contributes',()=>{
  const r=previewUsageDollarReference({...sample,usageCurrent:0});
  assert.equal(r.indexValue,0);
  assert.throws(()=>previewUsageDollarReference({...sample,
    usageCurrent:0,usageWeight:0,dollarWeight:1}),PolicyPreviewError);
});
test('Reference rejects guessed weights, tampered fields, nonnumeric input and invalid baselines',()=>{
  for(const input of [
    null,[],{},
    {...sample,usageBaseline:0},
    {...sample,usageBaseline:-1},
    {...sample,dollarIndexBaseline:0},
    {...sample,dollarIndexCurrent:-1},
    {...sample,usageCurrent:NaN},
    {...sample,usageCurrent:Infinity},
    {...sample,usageWeight:0.7,dollarWeight:0.7},
    {...sample,usageWeight:-0.2,dollarWeight:1.2},
    {...sample,usageBaseline:'1000'},
    {...sample,marketPriceUsd:1},
    {...sample,walletAddress:'0xBAD'},
    {...sample,dollarWeight:undefined},
    {...sample,usageCurrent:1e13},
  ])assert.throws(()=>previewUsageDollarReference(input),PolicyPreviewError);
});
test('No dollar value, chain state, minting or live oracle is inferred from this policy module',()=>{
  const js=[
    FUTURE_PRVI_INTEGRATION.pricePegActive,
    FUTURE_PRVI_INTEGRATION.paymentsEnabled,
    FUTURE_PRVI_INTEGRATION.walletSigningEnabled,
    FUTURE_PRVI_INTEGRATION.indexOracleConfigured,
  ];
  assert.deepEqual(js,[false,false,false,false]);
  assert.equal(FUTURE_PRVI_INTEGRATION.economicModel,'SELECTED_DESIGN_USD_REDEEMABLE_PAYMENT_STABLECOIN');
});


test('Selected PRVI stablecoin policy targets cash USD par, not a USD FX index or user activity',()=>{
 const p=PROPOSED_PRVI_STABLECOIN;
 assert.equal(Object.isFrozen(p),true);
 assert.equal(p.proposedAsset,'native PRVI');
 assert.equal(p.designSelection,'USD_REDEEMABLE_PAYMENT_STABLECOIN');
 assert.equal(p.redemptionTarget,'USD 1.00 per issued PRVI');
 assert.equal(p.usdPerTokenTarget,1);
 assert.match(p.reserveCoveragePolicy,/one_USD_eligible_reserves_per_outstanding_PRVI/);
 assert.equal(p.lifetimeWholeTokenCapProposed,'1000000000');
 assert.equal(p.reserveBackingForHypotheticalFullCapUsd,'1000000000');
 assert.equal(p.dollarFxIndexDeterminesRedemption,false);
 assert.equal(p.heyJoseUsageDeterminesRedemption,false);
 assert.equal(p.heyJoseUsageCanMintUnbackedTokens,false);
 assert.equal(p.userActivityUsedAsCollateral,false);
 assert.equal(p.userActivityPermittedForServiceMetricsOnly,true);
});
test('Stablecoin issuer authority, reserve accounting and redemption gates all fail closed',()=>{
 const p=PROPOSED_PRVI_STABLECOIN;
 for(const k of [
   'issuerApprovalVerified','authorizedReserveCustodianVerified','reservesVerified',
   'reserveAttestationVerified','redemptionOperationsVerified','mintingEnabled',
   'redemptionEnabled','publicOfferingEnabled','mainnetLive'
 ])assert.equal(p[k],false,k);
 assert.equal(p.planIsNotApproval,true);
 assert.equal(FUTURE_PRVI_INTEGRATION.financialMainnetLive,false);
 assert.equal(FUTURE_PRVI_INTEGRATION.pricePegActive,false);
 assert.equal(FUTURE_PRVI_INTEGRATION.usdRedemptionGuaranteed,false);
});
test('Legacy usage and FX index preview cannot authorize redemption or issuance',()=>{
 const result=previewUsageDollarReference(sample);
 assert.equal(result.kind,'HYPOTHETICAL_NON_FINANCIAL_REFERENCE_INDEX');
 assert.equal(result.redemptionRightCreated,false);
 assert.equal(result.pegEnforced,false);
 assert.equal(result.mintingEnabled,false);
 assert.equal(result.reservesVerified,false);
 assert.match(result.warning,/NOT inputs to PRVI dollar redemption/);
});
