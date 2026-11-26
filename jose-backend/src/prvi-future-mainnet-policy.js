// Privi financial-mainnet design. Intentionally fail-closed.
// The ONLY proposed economic-reference inputs are verified Hey Jose unique
// active users and verified Hey Jose completed usage. No USD price peg,
// dollar-FX index, reserves, bank/redemption claim, or token price oracle.
// An activity reference index cannot itself force a market token price.
// TEST devnet 772626, upstream demo 262144 and BNB PRIV remain separate.
export const PROPOSED_PRVI_USAGE_MODEL=Object.freeze({
  designSelection:'HEY_JOSE_VERIFIED_USERS_AND_USAGE_ONLY',
  economicReference:'NORMALIZED_COMPOSITE_ACTIVITY_INDEX',
  allowedComponents:Object.freeze(['verified_active_users','verified_successful_usage']),
  excludedComponents:Object.freeze(['usd_dollar_index','usd_market_price','usd_reserves',
    'user_personal_data','unverified_signups','failed_requests','bot_calls']),
  userMetric:'verified_unique_active_users_with_successful_use_per_reporting_period',
  usageMetric:'verified_successfully_completed_billable_or_approved_service_units_per_period',
  calculation:'100*(activeUsers/currentPeriodUsersBaseline)^usersWeight*(successfulUsage/currentPeriodUsageBaseline)^usageWeight',
  weighting:'NOT_YET_APPROVED',
  baselinePeriod:'NOT_YET_APPROVED',
  reportingPeriod:'NOT_YET_APPROVED',
  antiSybilMethod:'REQUIRED_NOT_VERIFIED',
  independentUsageAudit:false,
  metricsOracleConfigured:false,
  priceStabilizationMechanismDesigned:false,
  priceStabilizationMechanismFunded:false,
  exchangeRateGuaranteed:false,
  tokenMarketPriceUsd:null,
  usdDollarIndexUsed:false,
  stablecoinSelected:false,
  usdRedemptionSelected:false,
  noPersonallyIdentifyingMetricsOnChain:true,
  note:'User- and usage-indexed token economics is the selected design direction, not a functioning financial peg, guaranteed trading price, or authorization to mint.'
});
export const FUTURE_PRVI_INTEGRATION=Object.freeze({
  product:'Hey Jose',
  proposedNetwork:'native PRVI financial mainnet',
  readiness:'NO_GO_AWAITING_INDEPENDENT_RELEASE_EVIDENCE',
  connected:false,financialMainnetLive:false,
  chainId:null,cosmosChainId:null,rpcUrl:null,denom:null,
  upstreamDemoEvmId:262144,priviTestDevnetId:772626,
  walletSigningEnabled:false,paymentsEnabled:false,
  mintingEnabled:false,bridgingEnabled:false,automaticMigrationEnabled:false,
  pricePegActive:false,usdRedemptionGuaranteed:false,
  economicModel:'SELECTED_DESIGN_HEY_JOSE_USERS_AND_USAGE_ONLY',
  userUsageReferenceConfigured:false,
  userUsageOracleConfigured:false,
  usageProofVerified:false,
  independentMetricsAuditVerified:false,
  stabilizationMechanismApproved:false,
  economicModelApproved:false,
  dollarIndexConfigured:false,
  dollarFxIndexDeterminesTokenPrice:false,
  usdStablecoinSelected:false,
  publicUserDataOnChain:false,
  note:'Only Hey Jose verified user counts and verified completed usage are proposed as token-economic references. No USD-index component or USD redemption. No market price is guaranteed; financial mainnet remains NO-GO.'
});
export class PolicyPreviewError extends Error {
  constructor(message){super(message);this.name='PolicyPreviewError';this.status=400;}
}
const invalid=message=>{throw new PolicyPreviewError(message);};
const FIELDS=Object.freeze(['usersBaseline','usersCurrent','usageBaseline',
  'usageCurrent','usersWeight','usageWeight']);
function validateNumber(value,field,positive){
  const max=1e12;
  if(typeof value!=='number'||!Number.isFinite(value)||value<0||
    value>max||(positive&&value===0))
    invalid(field+' must be a finite '+(positive?'positive':'non-negative')+
      ' number no greater than '+max+'.');
  return value;
}
/**
 * NONFINANCIAL what-if index. All input numbers are caller-supplied,
 * not authenticated or observed by Jose. The 0–1 weights are hypothetical
 * and deliberately must be explicit; the user has not selected weights.
 *
 * I(t)=100 * (U_t/U_0)^wU * (A_t/A_0)^wA
 * where U=verified active unique user count, A=verified completed usage units.
 * The resulting number is not a price, exchange rate or monetary peg.
 */
export function previewHeyJoseActivityIndex(input){
  if(!input||typeof input!=='object'||Array.isArray(input)||
    Object.keys(input).length!==FIELDS.length||
    Object.keys(input).some(k=>!FIELDS.includes(k)))
    invalid('Supply exactly usersBaseline, usersCurrent, usageBaseline, usageCurrent, usersWeight, and usageWeight.');
  const u0=validateNumber(input.usersBaseline,'usersBaseline',true);
  const ut=validateNumber(input.usersCurrent,'usersCurrent',false);
  const a0=validateNumber(input.usageBaseline,'usageBaseline',true);
  const at=validateNumber(input.usageCurrent,'usageCurrent',false);
  const wu=validateNumber(input.usersWeight,'usersWeight',false);
  const wa=validateNumber(input.usageWeight,'usageWeight',false);
  if(wu>1||wa>1||Math.abs(wu+wa-1)>1e-10)
    invalid('usersWeight and usageWeight must each be between 0 and 1 and total 1.');
  // Prevent a misleading 0^0 when that component has zero weight.
  if((ut===0&&wu===0)||(at===0&&wa===0))
    invalid('Zero current metric with zero metric weight is undefined.');
  const usersFactor=ut/u0,usageFactor=at/a0;
  const computed=100*Math.pow(usersFactor,wu)*Math.pow(usageFactor,wa);
  if(!Number.isFinite(computed))invalid('Index calculation overflow.');
  return {
    kind:'HYPOTHETICAL_HEY_JOSE_USER_USAGE_INDEX',
    formula:'100 * (usersCurrent / usersBaseline)^usersWeight * (usageCurrent / usageBaseline)^usageWeight',
    indexValue:Number(computed.toPrecision(12)),baseValue:100,
    normalizedUsers:Number(usersFactor.toPrecision(12)),
    normalizedUsage:Number(usageFactor.toPrecision(12)),
    usersWeight:wu,usageWeight:wa,
    source:'CALLER_ENTERED_SCENARIO_NOT_VERIFIED',
    oracleVerified:false,independentMetricsAudit:false,
    syntheticScenario:true,realMarketPrice:null,
    dollarIndexUsed:false,usdRedemptionGuaranteed:false,
    pricePegEnforced:false,priceStabilizationFunded:false,
    tokenMinted:false,financialMainnetLive:false,
    warning:'Hey Jose user and usage index for research only. User activity is not financial collateral, a dollar peg, a token price, or authorization to mint. The market price cannot be guaranteed by this index alone.'
  };
}
