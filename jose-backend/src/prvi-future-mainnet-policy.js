// Hey Jose / financial PRVI: design-only, fail-closed future integration.
// This module never reads a mainnet RPC, never signs transactions, changes
// token supply, quotes a PRVI price, guarantees a peg, or activates launch.
// TEST (772626), BNB PRIV and the upstream EVM demo (262144) are separate.
// Product selection: native PRVI is intended as a genuinely redeemable
// USD payment stablecoin, NOT a floating utility token with a dollar-FX index.
// None of the stablecoin's legal, banking, reserve, custody or chain gates
// are satisfied by choosing a design.
export const PROPOSED_PRVI_STABLECOIN=Object.freeze({
  proposedAsset:'native PRVI',
  designSelection:'USD_REDEEMABLE_PAYMENT_STABLECOIN',
  redemptionTarget:'USD 1.00 per issued PRVI',
  redemptionCurrency:'USD',
  usdPerTokenTarget:1,
  reserveCoveragePolicy:'at_least_one_USD_eligible_reserves_per_outstanding_PRVI',
  reserveAssetsPolicy:'cash_insured_deposits_eligible_short_term_treasuries_and_other_regulator_permitted_assets',
  issuancePolicy:'mint_only_against_verified_eligible_reserves_after_issuer_and_chain_approval',
  redemptionPolicy:'redeem_and_retire_tokens_under_approved_issuer_procedures',
  lifetimeWholeTokenCapProposed:'1000000000',
  reserveBackingForHypotheticalFullCapUsd:'1000000000',
  dollarFxIndexDeterminesRedemption:false,
  heyJoseUsageDeterminesRedemption:false,
  heyJoseUsageCanMintUnbackedTokens:false,
  userActivityUsedAsCollateral:false,
  userActivityPermittedForServiceMetricsOnly:true,
  issuerApprovalVerified:false,
  authorizedReserveCustodianVerified:false,
  reservesVerified:false,
  reserveAttestationVerified:false,
  redemptionOperationsVerified:false,
  mintingEnabled:false,
  redemptionEnabled:false,
  publicOfferingEnabled:false,
  mainnetLive:false,
  planIsNotApproval:true,
  note:'Only a design selection. There are no verified reserves or issuer authorizations; no issued/redeemable stablecoins or enforceable $1 redemption are established by this software.'
});

export const FUTURE_PRVI_INTEGRATION=Object.freeze({
  product:'Hey Jose',
  proposedNetwork:'native PRVI financial mainnet',
  readiness:'NO_GO_AWAITING_INDEPENDENT_RELEASE_EVIDENCE',
  connected:false,financialMainnetLive:false,
  chainId:null,cosmosChainId:null,rpcUrl:null,denom:null,
  upstreamDemoEvmId:262144,priviTestDevnetId:772626,
  walletSigningEnabled:false,paymentsEnabled:false,
  mintingEnabled:false,bridgingEnabled:false,
  automaticMigrationEnabled:false,
  pricePegActive:false,usdRedemptionGuaranteed:false,
  economicModel:'SELECTED_DESIGN_USD_REDEEMABLE_PAYMENT_STABLECOIN',
  selectedStablecoinDesign:'USD_REDEEMABLE_PAYMENT_STABLECOIN',
  proposedRedemptionUsdPerToken:1,
  issuerApprovalVerified:false,reservesVerified:false,
  reserveAttestationVerified:false,redemptionEnabled:false,
  issuanceAgainstReservesVerified:false,
  heyJoseUsageBacksToken:false,dollarFxIndexDeterminesTokenPrice:false,
  economicModelApproved:false,indexOracleConfigured:false,
  publicUserDataOnChain:false,
  note:'Target architecture selected: genuinely USD-redeemable PRVI stablecoin, $1/token with eligible 1:1 reserves and authorized issuer. None of those conditions are verified or active. Financial mainnet remains NO-GO.'
});

export class PolicyPreviewError extends Error {
  constructor(message){super(message);this.name='PolicyPreviewError';this.status=400;}
}
const error=message=>{throw new PolicyPreviewError(message);};
const allowedFields=new Set(['usageBaseline','usageCurrent',
  'dollarIndexBaseline','dollarIndexCurrent','usageWeight','dollarWeight']);
function number(v,name,{min=0,max=1e12,allowZero=false}={}){
  if(typeof v!=='number'||!Number.isFinite(v)||
     v<min||v>max||(!allowZero&&v===0))
    error(name+' must be a finite '+(allowZero?'non-negative':'positive')+
      ' number no greater than '+max+'.');
  return v;
}

/**
 * Demonstration of a *dimensionless* reference index, not a token price,
 * market prediction, supply oracle, redemption rate or peg mechanism.
 *
 * For explicitly provided observations in matching units/periods:
 *      I = 100 * (U_t / U_0)^wU * (D_t / D_0)^wD
 * wU + wD = 1.0, with both weights provided.
 *
 * A positive market-price reference, collateral or legally enforceable
 * redemption mechanism cannot be inferred from this arithmetic.
 */
export function previewUsageDollarReference(input){
  if(!input||typeof input!=='object'||Array.isArray(input)||
     Object.keys(input).some(k=>!allowedFields.has(k))||
     Object.keys(input).length!==allowedFields.size)
    error('Supply exactly six numeric fields: usageBaseline, usageCurrent, dollarIndexBaseline, dollarIndexCurrent, usageWeight and dollarWeight.');
  const U0=number(input.usageBaseline,'usageBaseline');
  const Ut=number(input.usageCurrent,'usageCurrent',{min:0,allowZero:true});
  const D0=number(input.dollarIndexBaseline,'dollarIndexBaseline');
  const Dt=number(input.dollarIndexCurrent,'dollarIndexCurrent');
  const wu=number(input.usageWeight,'usageWeight',{min:0,max:1,allowZero:true});
  const wd=number(input.dollarWeight,'dollarWeight',{min:0,max:1,allowZero:true});
  if(Math.abs((wu+wd)-1)>1e-10)error('Usage and dollar index weights must total exactly 1.');
  // 0^0 is formally undefined. A zero-use observation is permissible only
  // with a positive usage weight, where the reference index becomes zero.
  if(Ut===0&&wu===0)error('Zero usage with zero usage weight is undefined.');
  const normalizedUsage=Ut/U0;
  const normalizedDollar=Dt/D0;
  const indexValue=100*Math.pow(normalizedUsage,wu)*Math.pow(normalizedDollar,wd);
  if(!Number.isFinite(indexValue))error('Index calculation overflow.');
  return {
    kind:'HYPOTHETICAL_NON_FINANCIAL_REFERENCE_INDEX',
    formula:'100 * (current_verified_usage / baseline_verified_usage)^usageWeight * (current_dollar_index / baseline_dollar_index)^dollarWeight',
    baseValue:100,
    indexValue:Number(indexValue.toPrecision(12)),
    normalizedUsage:Number(normalizedUsage.toPrecision(12)),
    normalizedDollar:Number(normalizedDollar.toPrecision(12)),
    usageWeight:wu,dollarWeight:wd,
    valuesProvidedByCaller:true,oracleVerified:false,
    independentUsageAudit:false,marketPriceUsd:null,
    tokenPricePredicted:false,pegEnforced:false,
    reservesVerified:false,redemptionRightCreated:false,
    mintingEnabled:false,financialMainnetLive:false,
    warning:'Legacy scenario research only. The USD FX index and Hey Jose usage are NOT inputs to PRVI dollar redemption, backing, or issuance. This is not a PRVI price, peg, mint/burn policy, or verified on-chain data.'
  };
}
