'use strict';
// Research-only vesting claim state model; NOT a production keeper or transferable asset.
const test = require('node:test');
const assert = require('node:assert/strict');
const TOTAL = 100_000_000n;
const DAY = 86_400n;
const CLIFF = 365n * DAY;
const DURATION = 3n * 365n * DAY;
function vested(elapsed) {
  if (typeof elapsed !== 'bigint' || elapsed < 0n) throw new RangeError('elapsed');
  if (elapsed <= CLIFF) return 0n;
  if (elapsed >= CLIFF + DURATION) return TOTAL;
  return TOTAL * (elapsed - CLIFF) / DURATION;
}
function claim(state, elapsed, amount) {
  if (typeof amount !== 'bigint' || amount <= 0n) throw new RangeError('amount');
  if (typeof state.claimed !== 'bigint' || state.claimed < 0n || state.claimed > TOTAL) throw new RangeError('claimed');
  if (typeof state.lastElapsed !== 'bigint' || elapsed < state.lastElapsed) throw new RangeError('time rollback');
  const available = vested(elapsed) - state.claimed;
  if (amount > available) throw new RangeError('exceeds vested unclaimed');
  return {claimed: state.claimed + amount, lastElapsed: elapsed};
}
test('cliff, overclaim, and replayed claims fail closed', () => {
  const start = {claimed:0n,lastElapsed:0n};
  assert.throws(() => claim(start, CLIFF, 1n), RangeError);
  const time = CLIFF + DURATION / 2n;
  const first = claim(start, time, vested(time));
  assert.equal(first.claimed, vested(time));
  assert.throws(() => claim(first, time, 1n), RangeError);
  assert.throws(() => claim(first, time - 1n, 1n), RangeError);
  assert.throws(() => claim(first, CLIFF + DURATION, TOTAL), RangeError);
  const done = claim(first, CLIFF + DURATION, TOTAL - first.claimed);
  assert.equal(done.claimed, TOTAL);
  assert.throws(() => claim(done, CLIFF + DURATION, 1n), RangeError);
});
test('partial claims never exceed vested allocation', () => {
  let state = {claimed:0n,lastElapsed:0n};
  for (let i=1n;i<=100n;i++) {
    const time = CLIFF + DURATION * i / 100n;
    const available = vested(time) - state.claimed;
    if (available > 0n) state = claim(state, time, available);
    assert.equal(state.claimed, vested(time));
    assert.ok(state.claimed <= TOTAL);
  }
  assert.equal(state.claimed, TOTAL);
});
test('invalid amounts and state are rejected', () => {
  const s={claimed:0n,lastElapsed:0n};
  for(const amount of [0n,-1n,1,'1',null]) assert.throws(()=>claim(s,CLIFF+DURATION,amount),RangeError);
  for(const claimed of [-1n,TOTAL+1n,0]) assert.throws(()=>claim({claimed,lastElapsed:0n},CLIFF+DURATION,1n),RangeError);
});
