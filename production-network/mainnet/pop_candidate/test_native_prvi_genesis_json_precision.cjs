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

 
// Exact split is a proposed genesis policy, not a production bank/vesting keeper.
const LIQUID_BASE_UNITS = 900_000_000n * 10n ** 18n;
const VESTED_BASE_UNITS = 100_000_000n * 10n ** 18n;
function validateGenesisSplitFromJson(json) {
  const decoded = JSON.parse(json);
  const liquid = parseNativeGenesisAmount(decoded.liquid);
  const vested = parseNativeGenesisAmount(decoded.vested);
  return liquid === LIQUID_BASE_UNITS && vested === VESTED_BASE_UNITS &&
    liquid + vested === CAP_BASE_UNITS;
}

test('rejects split substitution even when serialized genesis supply remains at cap', () => {
  const serialize = (liquid, vested) => JSON.stringify({ liquid: liquid.toString(), vested: vested.toString() });
  assert.equal(validateGenesisSplitFromJson(serialize(LIQUID_BASE_UNITS, VESTED_BASE_UNITS)), true);
  for (const delta of [1n, 10n ** 18n, VESTED_BASE_UNITS]) {
    assert.equal(validateGenesisSplitFromJson(serialize(LIQUID_BASE_UNITS + delta, VESTED_BASE_UNITS - delta)), false);
    assert.equal(validateGenesisSplitFromJson(serialize(LIQUID_BASE_UNITS - delta, VESTED_BASE_UNITS + delta)), false);
  }
  assert.throws(() => validateGenesisSplitFromJson(JSON.stringify({ liquid: Number(LIQUID_BASE_UNITS), vested: VESTED_BASE_UNITS.toString() })), TypeError);
});
