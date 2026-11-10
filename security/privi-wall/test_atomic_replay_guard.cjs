'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { createAtomicReplayGuard } = require('./create_atomic_replay_guard.cjs');
const now = 2000000;
const claims = Object.freeze({ tenantId: 'tenant-1', agentId: 'agent-1', sessionId: 'session-1', nonce: 'n-1', issuedAtMs: now });
test('concurrent duplicate calls admit exactly once with atomic store', async () => {
  const keys = new Set();
  const reserveOnce = async (key, ttl) => {
    assert.equal(ttl, 305000);
    if (keys.has(key)) return false;
    keys.add(key);
    return true;
  };
  const guard = createAtomicReplayGuard({ reserveOnce, clock: () => now });
  const results = await Promise.all(Array.from({ length: 20 }, () => guard(claims)));
  assert.equal(results.filter(Boolean).length, 1);
});
test('tenant and session boundaries produce distinct keys', async () => {
  const keys = [];
  const guard = createAtomicReplayGuard({ reserveOnce: async key => { keys.push(key); return true; }, clock: () => now });
  assert.equal(await guard(claims), true);
  assert.equal(await guard({ ...claims, tenantId: 'tenant-2' }), true);
  assert.equal(await guard({ ...claims, sessionId: 'session-2' }), true);
  assert.equal(new Set(keys).size, 3);
});
test('storage failures and unexpected truthy values fail closed', async () => {
  for (const reserveOnce of [async () => { throw Error('down'); }, async () => 1, async () => 'OK']) {
    assert.equal(await createAtomicReplayGuard({ reserveOnce, clock: () => now })(claims), false);
  }
});
test('stale future and malformed claims fail closed', async () => {
  const guard = createAtomicReplayGuard({ reserveOnce: async () => true, clock: () => now });
  assert.equal(await guard({ ...claims, issuedAtMs: now - 300001 }), false);
  assert.equal(await guard({ ...claims, issuedAtMs: now + 5001 }), false);
  await assert.rejects(guard({ ...claims, nonce: 'a|b' }), TypeError);
  const accessor = { ...claims };
  Object.defineProperty(accessor, 'tenantId', { get() { throw Error('getter executed'); } });
  await assert.rejects(guard(accessor), TypeError);
});
