// Copyright (c) 2026 Privi World Corp. New original source licensed under repository LICENSE.
// Privi Duration Rewards: off-chain, non-transferable PRELAUNCH participation points.
// This module NEVER mints PRVI, signs a wallet transaction or promises conversion.
import { createHmac, timingSafeEqual } from 'node:crypto';

export const REWARD_POLICY = Object.freeze({
  name: 'Privi Duration Rewards',
  state: 'PRELAUNCH_NONFINANCIAL',
  unit: 'NONTRANSFERABLE_PARTICIPATION_POINTS',
  nativePrviMinting: false,
  redemption: false,
  rewardPerVerifiedFiveSeconds: 1,
  rewardPerAttestedUsefulAction: 1,
  maximumSecondsPerReceipt: 300,
  maximumSecondsPerUsefulAction: 30,
  maximumUsefulActionsPerReceipt: 50,
  dailyCaps: Object.freeze({ user: 1440, agent: 2880 }),
  eligibility: 'Verified uptime AND a trusted signed work receipt; idle connections, self-reported claims and browser pings earn nothing.',
  mainnetPrerequisite: 'Audited native PRVI consensus, treasury authorization and approved issuance economics.',
});

export class InvalidRewardReceipt extends Error {
  constructor(message) {
    super(message);
    this.name = 'InvalidRewardReceipt';
  }
}

export function validateRewardReceipt(receipt) {
  if (!receipt || typeof receipt !== 'object' || Array.isArray(receipt)) {
    throw new InvalidRewardReceipt('Reward receipt must be an object');
  }
  const { proofId, subjectId, role, verifiedSeconds, usefulActions, evidenceRef } = receipt;
  if (typeof proofId !== 'string' || !/^[a-zA-Z0-9:_-]{8,100}$/.test(proofId)) {
    throw new InvalidRewardReceipt('Invalid unique proof ID');
  }
  if (role !== 'user' && role !== 'agent') {
    throw new InvalidRewardReceipt('Only users and agents can earn prelaunch points');
  }
  if (typeof subjectId !== 'string' ||
      !new RegExp('^' + role + ':[a-zA-Z0-9_-]{8,96}$').test(subjectId)) {
    throw new InvalidRewardReceipt('Receipt subject must match role');
  }
  if (!Number.isSafeInteger(verifiedSeconds) || verifiedSeconds < 5 ||
      verifiedSeconds > REWARD_POLICY.maximumSecondsPerReceipt) {
    throw new InvalidRewardReceipt('Verified connected duration must be 5–300 seconds');
  }
  if (!Number.isSafeInteger(usefulActions) || usefulActions < 1 ||
      usefulActions > REWARD_POLICY.maximumUsefulActionsPerReceipt) {
    throw new InvalidRewardReceipt('Must attest 1–50 useful actions');
  }
  if (typeof evidenceRef !== 'string' ||
      !/^[a-zA-Z0-9:_/-]{12,120}$/.test(evidenceRef)) {
    throw new InvalidRewardReceipt('Auditable action evidence reference required');
  }
  // One actual work unit may justify up to 30 seconds of verified availability;
  // being connected for hours without useful work cannot farm rewards.
  const eligibleSeconds = Math.min(
    verifiedSeconds, usefulActions * REWARD_POLICY.maximumSecondsPerUsefulAction
  );
  const durationPoints = Math.floor(eligibleSeconds / 5);
  const actionPoints = usefulActions;
  return Object.freeze({
    proofId, subjectId, role, evidenceRef, verifiedSeconds, usefulActions,
    eligibleSeconds, requestedPoints: durationPoints + actionPoints,
    dailyCap: REWARD_POLICY.dailyCaps[role],
    unit: REWARD_POLICY.unit,
    financialPrviAmount: 0,
  });
}

// The trusted work executor signs the exact request body AND timestamp using a
// server-side 32+ character secret. Ordinary browsers/agents must never receive
// that secret. Expired or replayed signatures are not valid evidence.
export function verifyReceiptSignature({
  rawBody, timestamp, signature, secret, nowMs = Date.now(),
}) {
  if (typeof secret !== 'string' || secret.length < 32 ||
      typeof rawBody !== 'string' || rawBody.length > 8192 ||
      typeof timestamp !== 'string' || !/^\d{13}$/.test(timestamp) ||
      typeof signature !== 'string' || !/^[0-9a-f]{64}$/.test(signature)) {
    return false;
  }
  const issued = Number(timestamp);
  if (!Number.isSafeInteger(issued) || Math.abs(nowMs - issued) > 60_000) {
    return false;
  }
  const expected = createHmac('sha256', secret)
    .update(timestamp + '.' + rawBody).digest();
  const observed = Buffer.from(signature, 'hex');
  return observed.length === expected.length && timingSafeEqual(expected, observed);
}
