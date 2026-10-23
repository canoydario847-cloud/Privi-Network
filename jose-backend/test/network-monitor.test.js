// Copyright (c) 2026 Privi World Corp. Unit tests use fake HTTP only.
import test from 'node:test';
import assert from 'node:assert/strict';
import { createNetworkMonitor, gradeForScore, TARGETS } from '../src/network-monitor.js';

function mockGood(url) {
  const item = TARGETS.find((s) => s.url === url);
  return Promise.resolve({ status: 200, json: async () => ({
    ok: true, service: item.id, version: 'test-only',
  }) });
}

test('Jose gives a current A grade for five verified service replies, without mainnet claims', async () => {
  let now = 1_000_000;
  const monitor = createNetworkMonitor({ fetchImpl: mockGood, clock: () => now });
  const report = await monitor.checkNow();
  assert.equal(report.grade, 'A');
  assert.equal(report.score, 100);
  assert.equal(report.available, 5);
  assert.equal(report.total, 5);
  assert.equal(report.monitoringScope, 'APPLICATION_SERVICES_ONLY');
  assert.equal(report.consensusHealthVerified, false);
  assert.equal(report.financialMainnetActivated, false);
  assert.equal(report.financialRewardClaimsAllowed, false);
  now += 16_000;
  const stale = monitor.getReport();
  assert.equal(stale.grade, 'N/A');
  assert.equal(stale.score, null);
  assert.equal(stale.fresh, false);
});

test('HTTP 200 without exact signed-off health schema is DOWN', async () => {
  const monitor = createNetworkMonitor({
    fetchImpl: async () => ({ status: 200, json: async () => ({ ok: true, service: 'incorrect' }) }),
  });
  const report = await monitor.checkNow();
  assert.equal(report.grade, 'F');
  assert.equal(report.score, 0);
  assert.equal(report.available, 0);
  assert.equal(report.services.every((s) => !s.healthy), true);
});

test('a single unavailable health route is graded down, never disguised as A', async () => {
  const monitor = createNetworkMonitor({
    fetchImpl: async (url) => {
      if (url.includes('privi-anchor')) throw new Error('fake network outage');
      return mockGood(url);
    },
  });
  const report = await monitor.checkNow();
  assert.equal(report.available, 4);
  assert.notEqual(report.grade, 'A');
  assert.equal(report.services.find((s) => s.id === 'privi-anchor').status, 'DOWN');
  assert.equal(report.history.length, 1);
});

test('all probes running concurrently collapse into at most one round', async () => {
  let resolve;
  let requests = 0;
  const fetchImpl = () => {
    requests++;
    return new Promise((accept) => { resolve = accept; });
  };
  const monitor = createNetworkMonitor({
    targets: [TARGETS[0]],
    fetchImpl,
    timeoutMs: 300,
  });
  const first = monitor.checkNow();
  const second = await monitor.checkNow();
  assert.equal(second.fresh, false);
  assert.equal(requests, 1);
  resolve({ status: 200, json: async () => ({ ok: true, service: 'privi-ledger' }) });
  assert.equal((await first).available, 1);
});

test('monitor permits no untrusted probe locations or sub-five-second schedule', () => {
  assert.throws(() => createNetworkMonitor({
    targets: [{ id: 'privi-ledger', name: 'SSRF', url: 'http://127.0.0.1/health' }],
  }), /Unapproved/);
  assert.throws(() => createNetworkMonitor({
    targets: [{ id: 'privi-ledger', name: 'Host', url: 'https://example.com/health' }],
  }), /Unapproved/);
  assert.throws(() => createNetworkMonitor({ intervalMs: 100 }), /five seconds/);
  assert.equal(gradeForScore(Number.NaN), 'N/A');
  assert.equal(gradeForScore(89), 'B');
  assert.equal(gradeForScore(69), 'D');
});

test('monitor handles failed JSON body without exiting or crashing', async () => {
  const monitor = createNetworkMonitor({
    fetchImpl: async () => ({ status: 200, json: async () => { throw new Error('invalid json'); } }),
  });
  const report = await monitor.checkNow();
  assert.equal(report.available, 0);
  assert.equal(report.grade, 'F');
});

test('report history is bounded to 120 samples and response to 12', async () => {
  const monitor = createNetworkMonitor({ fetchImpl: mockGood });
  for (let i = 0; i < 124; i++) await monitor.checkNow();
  assert.equal(monitor.getReport().history.length, 12);
  assert.equal(monitor.getReport().available, 5);
});
