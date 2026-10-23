// Copyright (c) 2026 Privi World Corp — nonfinancial reward accounting tests.
import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { createParticipationEngine, getAgentActor, POLICY } from '../src/participation.js';

function fixture() {
  let t = 1_000_000;
  const data = new Map();
  const store = {
    getRewardState: id => data.get(id),
    putRewardState: (id, entry) => data.set(id, structuredClone(entry)),
  };
  const engine = createParticipationEngine({ store, now: () => t });
  const good = { state: 'OBSERVING', stale: false, servicesUp: 6,
    servicesTotal: 6, grade: 'A', checkedAt: new Date(t).toISOString() };
  const clock = amount => { t += amount; good.checkedAt = new Date(t).toISOString(); };
  return { engine, good, clock, data };
}
const alice = 'user:11111111-1111-4111-a111-111111111111';

test('authenticated presence accrues one provisional credit per measured minute', () => {
  const { engine, good, clock } = fixture();
  let r = engine.heartbeat(alice, good);
  assert.equal(r.totalCredits, 0);
  for (let i = 0; i < 4; i++) {
    clock(15_000);
    r = engine.heartbeat(alice, good);
  }
  assert.equal(r.todayPresenceMinutes, 1);
  assert.equal(r.totalCredits, 1);
  assert.equal(r.lifetimePresenceMinutes, 1);
  assert.equal(r.realPrviIssued, false);
  assert.equal(r.transferable, false);
  assert.equal(r.redeemable, false);
  assert.equal(r.rewardType, POLICY.rewardType);
});

test('duplicate tabs, fast retries and disconnected gaps cannot farm duration', () => {
  const { engine, good, clock } = fixture();
  engine.heartbeat(alice, good);
  for (let i = 0; i < 50; i++) engine.heartbeat(alice, good);
  assert.equal(engine.get(alice, good).pendingPresenceSeconds, 0);
  clock(300_000); engine.heartbeat(alice, good);
  assert.equal(engine.get(alice, good).totalCredits, 0);
  clock(15_000); engine.heartbeat(alice, good);
  assert.equal(engine.get(alice, good).pendingPresenceSeconds, 15);
});

test('ineligible service health never produces presence or inspection rewards', () => {
  const { engine, good, clock } = fixture();
  engine.heartbeat(alice, good);
  const bad = { ...good, servicesUp: 2, grade: 'F' };
  for (let i = 0; i < 6; i++) { clock(15_000); engine.heartbeat(alice, bad); }
  assert.equal(engine.get(alice, bad).totalCredits, 0);
  assert.equal(engine.inspect(alice, bad).credited, false);
  assert.equal(engine.get(alice, bad).totalCredits, 0);
});

test('server-verified inspections are once per minute and capped daily', () => {
  const { engine, good, clock } = fixture();
  const actor = 'agent:monitor01';
  assert.equal(engine.inspect(actor, good).credited, true);
  assert.equal(engine.inspect(actor, good).credited, false);
  assert.equal(engine.get(actor, good).totalCredits, 2);
  for (let i = 1; i < POLICY.maxInspectionsPerUtcDay; i++) {
    clock(60_000);
    assert.equal(engine.inspect(actor, good).credited, true);
  }
  clock(60_000);
  assert.equal(engine.inspect(actor, good).credited, false);
  assert.equal(engine.get(actor, good).totalCredits, 60);
  assert.ok(engine.get(actor, good).recentActivity.length <= 10);
});

test('connected-time daily cap and per-account isolation', () => {
  const { engine, good, clock } = fixture();
  engine.heartbeat(alice, good);
  for (let i = 0; i < (POLICY.maxPresenceMinutesPerUtcDay + 30) * 4; i++) {
    clock(15_000); engine.heartbeat(alice, good);
  }
  const final = engine.get(alice, good);
  assert.equal(final.todayPresenceMinutes, POLICY.maxPresenceMinutesPerUtcDay);
  assert.equal(final.totalCredits, POLICY.maxPresenceMinutesPerUtcDay);
  assert.equal(engine.get('agent:anotherAgent', good).totalCredits, 0);
});

test('agent credentials require a configured high-entropy SHA-256 hash', () => {
  const token = 'a'.repeat(40);
  const hash = createHash('sha256').update(token).digest('hex');
  assert.equal(getAgentActor('Bearer ' + token, 'probeAgent:' + hash), 'agent:probeAgent');
  assert.equal(getAgentActor('Bearer ' + 'b'.repeat(40), 'probeAgent:' + hash), null);
  assert.equal(getAgentActor('Bearer ' + token, 'probeAgent:bad-hash'), null);
  assert.equal(getAgentActor('Basic abc', 'probeAgent:' + hash), null);
});

test('rejects raw unauthenticated identifiers as rewards actor', () => {
  const { engine, good } = fixture();
  assert.throws(() => engine.heartbeat('anonymous', good), /Invalid authenticated/);
  assert.throws(() => engine.inspect('user:!', good), /Invalid authenticated/);
});
