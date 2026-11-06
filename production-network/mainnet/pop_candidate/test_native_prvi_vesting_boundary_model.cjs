'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');

// Candidate-only integer vesting model; NOT integrated with SDK genesis or vesting accounts.
// 365-day cliff, then 3 * 365-day linear release; times are integer Unix seconds.
const DAY = 86400n;
const CLIFF = 365n * DAY;
const LINEAR = 3n * 365n * DAY;
const ALLOCATION = 100000000n;
function vested(start, now, allocation = ALLOCATION) {
  if (typeof start !== 'bigint' || typeof now !== 'bigint' ||
      typeof allocation !== 'bigint' || start < 0n || now < 0n || allocation < 0n ||
      allocation > ALLOCATION) throw new RangeError('invalid vesting input');
  const elapsed = now - start;
  if (elapsed <= CLIFF) return 0n;
  if (elapsed >= CLIFF + LINEAR) return allocation;
  return allocation * (elapsed - CLIFF) / LINEAR;
}

test('candidate vesting cliff and linear-release boundaries never exceed allocation', () => {
  const start = 1800000000n;
  assert.equal(vested(start, start - 1n), 0n);
  assert.equal(vested(start, start + CLIFF - 1n), 0n);
  assert.equal(vested(start, start + CLIFF), 0n);
  assert.equal(vested(start, start + CLIFF + LINEAR / 2n), 50000000n);
  assert.equal(vested(start, start + CLIFF + LINEAR - 1n), ALLOCATION * (LINEAR - 1n) / LINEAR);
  assert.equal(vested(start, start + CLIFF + LINEAR), ALLOCATION);
  assert.equal(vested(start, start + CLIFF + LINEAR + DAY), ALLOCATION);
});

test('candidate vested amount is monotonic and rejects invalid allocation/timestamps', () => {
  const start = 1800000000n;
  let previous = 0n;
  for (let i = 0n; i <= 1000n; i++) {
    const amount = vested(start, start + i * (CLIFF + LINEAR) / 1000n);
    assert.ok(amount >= previous && amount <= ALLOCATION);
    previous = amount;
  }
  for (const args of [[-1n, 0n], [0n, -1n], [0n, 0n, -1n], [0n, 0n, ALLOCATION + 1n], [0, 0n]]) {
    assert.throws(() => vested(...args), RangeError);
  }
});
