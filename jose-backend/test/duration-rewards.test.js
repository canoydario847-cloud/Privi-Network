// Copyright (c) 2026 Privi World Corp. No wallets, PRVI issuance or financial assets.
import test from 'node:test';
import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import { mkdtempSync, rmSync, existsSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import {
  REWARD_POLICY, validateRewardReceipt, verifyReceiptSignature, InvalidRewardReceipt,
} from '../src/duration-rewards.js';

function receipt(override = {}) {
  return {
    proofId: 'receipt-valid-0001',
    subjectId: 'user:0123456789abcdef',
    role: 'user',
    verifiedSeconds: 60,
    usefulActions: 2,
    evidenceRef: 'tasks/proof-001',
    ...override,
  };
}

test('duration points reward verified time AND useful work but never native PRVI', () => {
  const grant = validateRewardReceipt(receipt());
  assert.equal(grant.eligibleSeconds, 60);
  assert.equal(grant.requestedPoints, 14);
  assert.equal(grant.financialPrviAmount, 0);
  assert.equal(grant.unit, 'NONTRANSFERABLE_PARTICIPATION_POINTS');
  assert.equal(REWARD_POLICY.nativePrviMinting, false);
  assert.equal(REWARD_POLICY.redemption, false);
});

test('one verified action cannot claim a five-minute idle presence', () => {
  const limited = validateRewardReceipt(receipt({ verifiedSeconds: 300, usefulActions: 1 }));
  assert.equal(limited.eligibleSeconds, 30);
  assert.equal(limited.requestedPoints, 7);
});

test('agent role has an independent daily cap', () => {
  const agent = validateRewardReceipt(receipt({
    subjectId: 'agent:verified_agent_001', role: 'agent',
  }));
  assert.equal(agent.dailyCap, 2880);
});

test('invalid, idle, oversized or role-crossing claims fail closed', () => {
  const bad = [
    { usefulActions: 0 }, { usefulActions: 51 },
    { verifiedSeconds: 0 }, { verifiedSeconds: 301 },
    { verifiedSeconds: 5.5 }, { verifiedSeconds: Infinity },
    { role: 'admin' }, { subjectId: 'agent:0123456789abcdef' },
    { proofId: '../accounts' }, { evidenceRef: '' },
    { usefulActions: '100' }, { subjectId: '__proto__' },
  ];
  for (const patch of bad) {
    assert.throws(() => validateRewardReceipt(receipt(patch)), InvalidRewardReceipt,
      JSON.stringify(patch));
  }
});

test('only timestamp-bound HMAC receipt issued by trusted backend is accepted', () => {
  const body = JSON.stringify(receipt());
  const secret = 'test-only-secret-of-at-least-32-characters';
  const nowMs = 1800000000000;
  const timestamp = String(nowMs);
  const signature = createHmac('sha256', secret).update(timestamp + '.' + body).digest('hex');
  assert.equal(verifyReceiptSignature({
    rawBody: body, timestamp, signature, secret, nowMs,
  }), true);
  assert.equal(verifyReceiptSignature({
    rawBody: body + ' ', timestamp, signature, secret, nowMs,
  }), false);
  assert.equal(verifyReceiptSignature({
    rawBody: body, timestamp, signature, secret: 'wrong-key-of-at-least-32-characters', nowMs,
  }), false);
  assert.equal(verifyReceiptSignature({
    rawBody: body, timestamp, signature, secret, nowMs: nowMs + 70_000,
  }), false);
  assert.equal(verifyReceiptSignature({
    rawBody: body, timestamp, signature, secret: '', nowMs,
  }), false);
  assert.equal(verifyReceiptSignature({
    rawBody: body, timestamp, signature: 'invalid', secret, nowMs,
  }), false);
});

test('JSON-backed prelaunch ledger persists, deduplicates and caps daily credits', async () => {
  const directory = mkdtempSync(join(tmpdir(), 'jose-points-'));
  const previousPath = process.env.DB_FILE;
  const path = join(directory, 'db.json');
  process.env.DB_FILE = path;
  try {
    mkdirSync(directory, { recursive: true });
    const { db } = await import('../src/store.js?test_participation_receipts=1');
    const t = Date.parse('2026-10-22T12:00:00.000Z');
    const firstQuote = validateRewardReceipt(receipt());
    const first = db.creditParticipation(firstQuote, t);
    assert.equal(first.grantedPoints, 14);
    assert.equal(first.totalPoints, 14);
    assert.equal(first.financialPrviAmount, 0);
    assert.equal(existsSync(path), true);
    const replay = db.creditParticipation(firstQuote, t + 5000);
    assert.equal(replay.duplicate, true);
    assert.equal(db.getParticipationBalance(firstQuote.subjectId, t).totalPoints, 14);
    for (let i = 0; i < 20; i++) {
      db.creditParticipation(validateRewardReceipt(receipt({
        proofId: 'another-work-proof-' + i,
        verifiedSeconds: 300, usefulActions: 50,
      })), t + i * 1000);
    }
    const balance = db.getParticipationBalance(firstQuote.subjectId, t);
    assert.equal(balance.todayPoints, REWARD_POLICY.dailyCaps.user);
    assert.equal(balance.totalPoints, REWARD_POLICY.dailyCaps.user);
    const next = db.getParticipationBalance(firstQuote.subjectId, t + 86400 * 1000);
    assert.equal(next.todayPoints, 0);
    assert.equal(next.totalPoints, REWARD_POLICY.dailyCaps.user);
    const nextDayCredit = db.creditParticipation(validateRewardReceipt(receipt({
      proofId: 'following-day-work',
    })), t + 86400 * 1000);
    assert.equal(nextDayCredit.grantedPoints, 14);
    assert.equal(nextDayCredit.totalPoints, REWARD_POLICY.dailyCaps.user + 14);
  } finally {
    if (previousPath === undefined) delete process.env.DB_FILE;
    else process.env.DB_FILE = previousPath;
    rmSync(directory, { recursive: true, force: true });
  }
});
