// Copyright (c) 2026 Privi World Corp — Jose monitoring regression tests.
import test from 'node:test';
import assert from 'node:assert/strict';
import { createNetworkMonitor, gradeFromScore } from '../src/network-monitor.js';

const targets = ['a', 'b', 'c', 'd', 'e', 'f'].map(id => ({
  id, name: id, url: 'https://' + id + '.example.invalid/health',
}));
const healthy = async () => ({ ok: true, json: async () => ({ ok: true }) });

test('grades only after 3 fresh cycles and never claims PRVI mainnet', async () => {
  let t = 1000;
  const m = createNetworkMonitor({ targets, fetchImpl: healthy, now: () => t });
  assert.equal(m.report().grade, 'N/A');
  await m.poll();
  assert.equal(m.report().grade, 'N/A');
  t += 5000; await m.poll();
  t += 5000; await m.poll();
  assert.equal(m.report().grade, 'A');
  assert.equal(m.report().score, 100);
  assert.equal(m.report().servicesUp, 6);
  assert.equal(m.report().financialMainnetVerified, false);
  assert.equal(m.report().realPrviRewardsEnabled, false);
  t += 16000;
  assert.equal(m.report().state, 'STALE');
  assert.equal(m.report().grade, 'N/A');
  assert.equal(m.report().servicesUp, 0);
});

test('HTTP 200 with negative or malformed health JSON fails closed', async () => {
  let t = 5000;
  const m = createNetworkMonitor({
    targets, now: () => t,
    fetchImpl: async () => ({ ok: true, json: async () => ({ ok: false }) }),
  });
  for (let i = 0; i < 3; i++) { await m.poll(); t += 5000; }
  assert.equal(m.report().grade, 'F');
  assert.equal(m.report().servicesUp, 0);
  assert.ok(m.report().services.every(s => s.lastError === 'HEALTH_NOT_OK'));
});

test('partial outage degrades scores and records failures without phantom uptime', async () => {
  let t = 100;
  const m = createNetworkMonitor({
    targets, now: () => t,
    fetchImpl: async url => {
      if (url.includes('a.example') || url.includes('b.example')) {
        return { ok: false, status: 503 };
      }
      return { ok: true, json: async () => ({ ok: true }) };
    },
  });
  for (let i = 0; i < 4; i++) { await m.poll(); t += 5000; }
  const r = m.report();
  assert.equal(r.servicesUp, 4);
  assert.ok(r.score < 95);
  assert.equal(r.services.find(s => s.id === 'a').lastError, 'HTTP_503');
  assert.equal(r.services.find(s => s.id === 'a').uptimePercent, 0);
});

test('nonoverlapping polling and bounded report history', async () => {
  let resolve;
  const fetchImpl = () => new Promise(r => { resolve = r; });
  const m = createNetworkMonitor({ targets: [targets[0]], fetchImpl, maxCycles: 3 });
  const first = m.poll();
  assert.equal(await m.poll(), false);
  resolve({ ok: true, json: async () => ({ ok: true }) });
  await first;
  const later = createNetworkMonitor({ targets: [targets[0]], fetchImpl: healthy, maxCycles: 3 });
  for (let i = 0; i < 6; i++) await later.poll();
  assert.equal(later.report().sampleCycles, 3);
  assert.equal(gradeFromScore(95), 'A');
  assert.equal(gradeFromScore(54), 'F');
});

test('rejects dynamic insecure or malformed monitoring targets', () => {
  assert.throws(() => createNetworkMonitor({ targets: [{ id: 'e', name: 'x', url: 'http://evil.test' }] }));
  assert.throws(() => createNetworkMonitor({ targets: [] }));
});
