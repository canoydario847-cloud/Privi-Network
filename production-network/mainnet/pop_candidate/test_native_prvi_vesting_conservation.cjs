'use strict';
// Research-only arithmetic model. Not a production vesting keeper or genesis validator.
const test = require('node:test');
const assert = require('node:assert/strict');
const CAP = 1_000_000_000n;
const LIQUID = 900_000_000n;
const VESTING = 100_000_000n;
const DAY = 86_400n;
const CLIFF = 365n * DAY;
const DURATION = 3n * 365n * DAY;
function partition(elapsed) {
  if (typeof elapsed !== 'bigint' || elapsed < 0n) throw new RangeError('elapsed must be nonnegative bigint seconds');
  const vested = elapsed <= CLIFF ? 0n : elapsed >= CLIFF + DURATION ? VESTING : VESTING * (elapsed - CLIFF) / DURATION;
  const locked = VESTING - vested;
  const spendable = LIQUID + vested;
  if (spendable + locked !== CAP) throw new Error('supply conservation violated');
  return {vested, locked, spendable};
}
test('vesting boundaries conserve exact 1B PRVI without floating-point rounding', () => {
  for (const t of [0n, CLIFF - 1n, CLIFF, CLIFF + 1n, CLIFF + DURATION / 2n, CLIFF + DURATION - 1n, CLIFF + DURATION, CLIFF + DURATION + 1n]) {
    const p = partition(t);
    assert.equal(p.spendable + p.locked, CAP);
    assert.ok(p.vested >= 0n && p.vested <= VESTING);
  }
  assert.equal(partition(CLIFF).vested, 0n);
  assert.equal(partition(CLIFF + DURATION).vested, VESTING);
  assert.equal(partition(CLIFF + DURATION).locked, 0n);
});
test('vesting is monotonic and cannot create new supply', () => {
  let previous = 0n;
  for (let i = 0n; i <= 1000n; i++) {
    const p = partition(CLIFF + DURATION * i / 1000n);
    assert.ok(p.vested >= previous);
    assert.equal(p.spendable + p.locked, CAP);
    previous = p.vested;
  }
});
test('reject invalid timestamps rather than silently coerce', () => {
  for (const t of [-1n, -100n, 1, '0', null, 0.5]) assert.throws(() => partition(t), RangeError);
});
