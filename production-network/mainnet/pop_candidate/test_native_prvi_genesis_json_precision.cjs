'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');

// Research-only boundary test. Cosmos genesis amounts are decimal strings;
// this does not prove production keeper or genesis import enforcement.
const CAP_BASE_UNITS = 1_000_000_000n * 10n ** 18n;

function parseNativeGenesisAmount(value) {
  if (typeof value !== 'string' || !/^(0|[1-9][0-9]*)$/.test(value)) {
    throw new TypeError('native amount must be a canonical unsigned decimal string');
  }
  const amount = BigInt(value);
  if (amount > CAP_BASE_UNITS) throw new RangeError('native amount exceeds PRVI cap');
  return amount;
}

test('round-trips exact cap and one-base-unit-under-cap through JSON', () => {
  for (const amount of [0n, 1n, CAP_BASE_UNITS - 1n, CAP_BASE_UNITS]) {
    const encoded = JSON.stringify({ amount: amount.toString() });
    assert.equal(parseNativeGenesisAmount(JSON.parse(encoded).amount), amount);
  }
});

test('rejects noncanonical or lossy JSON amounts', () => {
  for (const value of [0, 1, Number(CAP_BASE_UNITS), null, '-1', '+1', '01', '1.0', '1e18', ' 1', '1 ', '', 'NaN']) {
    assert.throws(() => parseNativeGenesisAmount(value));
  }
  assert.throws(() => parseNativeGenesisAmount((CAP_BASE_UNITS + 1n).toString()), RangeError);
});
