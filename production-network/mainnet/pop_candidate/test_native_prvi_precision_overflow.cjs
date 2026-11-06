'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');

// Research-only arithmetic: the native chain's actual denomination and keeper
// must be reviewed independently before this can be used as a release gate.
const CAP = 1_000_000_000n;
const LIQUID = 900_000_000n;
const LOCKED = 100_000_000n;

function units(tokens, decimals) {
  if (typeof tokens !== 'bigint' || tokens < 0n ||
      !Number.isSafeInteger(decimals) || decimals < 0 || decimals > 30) {
    throw new RangeError('invalid token amount or decimal precision');
  }
  return tokens * 10n ** BigInt(decimals);
}

function validateAllocation(liquid, locked, decimals) {
  if (typeof liquid !== 'bigint' || typeof locked !== 'bigint' ||
      liquid < 0n || locked < 0n) return false;
  return liquid + locked === units(CAP, decimals);
}

test('cap and vesting conservation are exact for plausible native precisions', () => {
  for (const decimals of [0, 6, 9, 18]) {
    const liquid = units(LIQUID, decimals);
    const locked = units(LOCKED, decimals);
    assert.equal(validateAllocation(liquid, locked, decimals), true);
    assert.equal(validateAllocation(liquid + 1n, locked, decimals), false);
    assert.equal(validateAllocation(liquid, locked - 1n, decimals), false);
  }
});

test('unsafe JavaScript Number conversion would lose base-unit precision', () => {
  const total = units(CAP, 18);
  assert.ok(total > BigInt(Number.MAX_SAFE_INTEGER));
  assert.notEqual(BigInt(Number(total + 1n)), total + 1n);
  assert.equal(validateAllocation(units(LIQUID, 18), units(LOCKED, 18), 18), true);
});

test('rejects malformed amounts and decimal precision', () => {
  for (const bad of [-1, 1.5, Number.NaN, 31, '18']) {
    assert.throws(() => units(CAP, bad), RangeError);
  }
  assert.throws(() => units(-1n, 18), RangeError);
  assert.equal(validateAllocation(-1n, units(CAP, 18) + 1n, 18), false);
  assert.equal(validateAllocation(1, units(CAP, 18) - 1n, 18), false);
});
