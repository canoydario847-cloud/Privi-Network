import test from 'node:test';
import assert from 'node:assert/strict';
import {
  FUTURE_PRVI_INTEGRATION,PROPOSED_PRVI_USAGE_MODEL,
  PolicyPreviewError,previewHeyJoseActivityIndex
} from '../src/prvi-future-mainnet-policy.js';

const example={usersBaseline:100,usersCurrent:120,
  usageBaseline:1000,usageCurrent:1500,
  usersWeight:0.5,usageWeight:0.5};

test('Chosen PRVI design includes ONLY verified Hey Jose users and completed usage',()=>{
  const p=PROPOSED_PRVI_USAGE_MODEL;
  assert.equal(p.designSelection,'HEY_JOSE_VERIFIED_USERS_AND_USAGE_ONLY');
  assert.deepEqual(p.allowedComponents,['verified_active_users','verified_successful_usage']);
  assert.equal(p.usdDollarIndexUsed,false);
  assert.equal(p.stablecoinSelected,false);
  assert.equal(p.usdRedemptionSelected,false);
  assert.equal(p.userActivityUsedAsCollateral,undefined);
  assert.equal(p.independentUsageAudit,false);
  assert.equal(p.metricsOracleConfigured,false);
  assert.equal(p.priceStabilizationMechanismFunded,false);
  assert.equal(p.exchangeRateGuaranteed,false);
  assert.equal(p.tokenMarketPriceUsd,null);
  assert.equal(Object.isFrozen(p),true);
});
test('Mainnet remains NO-GO, does not sign transactions or claim price stability',()=>{
  const f=FUTURE_PRVI_INTEGRATION;
  assert.equal(f.economicModel,'SELECTED_DESIGN_HEY_JOSE_USERS_AND_USAGE_ONLY');
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
  assert.equal(f.stabilizationMechanismApproved,false);
  assert.equal(f.usageProofVerified,false);
  assert.equal(f.dollarIndexConfigured,false);
  assert.equal(f.usdStablecoinSelected,false);
  assert.equal(f.publicUserDataOnChain,false);
  assert.equal(f.upstreamDemoEvmId,262144);
  assert.equal(f.priviTestDevnetId,772626);
});
test('User and usage preview computes a dimensionless nonmonetary reference',()=>{
  const r=previewHeyJoseActivityIndex(example);
  assert.equal(r.kind,'HYPOTHETICAL_HEY_JOSE_USER_USAGE_INDEX');
  assert.ok(Math.abs(r.indexValue-100*Math.sqrt(1.2*1.5))<1e-9);
  assert.equal(r.baseValue,100);
  assert.equal(r.normalizedUsers,1.2);
  assert.equal(r.normalizedUsage,1.5);
  assert.equal(r.source,'CALLER_ENTERED_SCENARIO_NOT_VERIFIED');
  assert.equal(r.syntheticScenario,true);
  assert.equal(r.oracleVerified,false);
  assert.equal(r.independentMetricsAudit,false);
  assert.equal(r.realMarketPrice,null);
  assert.equal(r.dollarIndexUsed,false);
  assert.equal(r.pricePegEnforced,false);
  assert.equal(r.priceStabilizationFunded,false);
  assert.equal(r.tokenMinted,false);
  assert.equal(r.financialMainnetLive,false);
});
test('Equal baselines always return 100 for varying explicitly selected weights',()=>{
  for(const w of [0,0.25,0.5,0.75,1]){
    const r=previewHeyJoseActivityIndex({...example,
      usersCurrent:example.usersBaseline,usageCurrent:example.usageBaseline,
      usersWeight:w,usageWeight:1-w});
    assert.equal(r.indexValue,100);
  }
});
test('Zero observed use or users returns zero when its weight is positive',()=>{
  assert.equal(previewHeyJoseActivityIndex({...example,usersCurrent:0}).indexValue,0);
  assert.equal(previewHeyJoseActivityIndex({...example,usageCurrent:0}).indexValue,0);
  assert.throws(()=>previewHeyJoseActivityIndex({...example,
    usersCurrent:0,usersWeight:0,usageWeight:1}),PolicyPreviewError);
  assert.throws(()=>previewHeyJoseActivityIndex({...example,
    usageCurrent:0,usersWeight:1,usageWeight:0}),PolicyPreviewError);
});
test('USD dollar-index, redemption, prices and missing/invalid inputs are rejected',()=>{
  const invalid=[
    null,[],{}, { ...example,usersBaseline:0},
    {...example,usageBaseline:0},
    {...example,usersCurrent:NaN},
    {...example,usageCurrent:Infinity},
    {...example,usersWeight:0.8,usageWeight:0.4},
    {...example,usersWeight:-0.2,usageWeight:1.2},
    {...example,usersBaseline:'100'},
    {...example,usageCurrent:1e13},
    {...example,dollarIndexCurrent:102},
    {...example,usdPrice:1},
    {...example,redemptionTarget:1},
    {...example,usageWeight:undefined},
  ];
  for(const input of invalid)
    assert.throws(()=>previewHeyJoseActivityIndex(input),PolicyPreviewError);
});
