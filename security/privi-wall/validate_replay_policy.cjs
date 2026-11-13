'use strict';
// Fail closed at gateway startup if receipt freshness and replay retention disagree.
// Prevents an accepted receipt from outliving its single-use Redis marker.
function validateReplayPolicy({maxAgeMs,maxFutureSkewMs,maxReplayTtlMs}={}) {
  if (!Number.isSafeInteger(maxAgeMs) || maxAgeMs<1 || maxAgeMs>300000 ||
      !Number.isSafeInteger(maxFutureSkewMs) || maxFutureSkewMs<0 || maxFutureSkewMs>30000 ||
      !Number.isSafeInteger(maxReplayTtlMs) || maxReplayTtlMs<1 || maxReplayTtlMs>86400000)
    throw new TypeError('Invalid Privi Wall replay policy');
  // verifyOnceTenantReceipt expires at executedAt + maxAge + skew + 1.
  // A future-dated receipt can therefore require this entire retention budget.
  const requiredTtlMs=maxAgeMs+maxFutureSkewMs+1;
  if (requiredTtlMs>maxReplayTtlMs)
    throw new RangeError('Replay TTL shorter than receipt acceptance horizon');
  return Object.freeze({maxAgeMs,maxFutureSkewMs,maxReplayTtlMs,requiredTtlMs});
}
module.exports={validateReplayPolicy};
