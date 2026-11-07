'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');

// Research-only canonicalization guard. Does not verify signatures or enforce consensus.
// Height and epoch must be positive; round may be zero. Never coerce numbers.
function canonicalDecimal(value, allowZero = false) {
  if (typeof value !== 'string' || !/^(0|[1-9][0-9]*)$/.test(value)) return false;
  if (!allowZero && value === '0') return false;
  // Bound values to uint64 without losing precision via Number conversion.
  return BigInt(value) <= 18446744073709551615n;
}
function canonicalContext(context) {
  return context !== null && typeof context === 'object' &&
    canonicalDecimal(context.epoch) && canonicalDecimal(context.height) &&
    canonicalDecimal(context.round, true);
}

test('candidate POP context numeric fields reject aliases, overflows and coercion', () => {
  const valid = {epoch: '1', height: '100', round: '0'};
  assert.equal(canonicalContext(valid), true);
  assert.equal(canonicalContext({...valid, height: '18446744073709551615'}), true);
  for (const field of ['epoch', 'height', 'round']) {
    for (const bad of ['01', '+1', '-1', '1.0', '1e0', ' 1', '1 ', '',
      '18446744073709551616', 1, 1n, null, undefined]) {
      assert.equal(canonicalContext({...valid, [field]: bad}), false, `${field}: ${String(bad)}`);
    }
  }
  assert.equal(canonicalContext({...valid, epoch: '0'}), false);
  assert.equal(canonicalContext({...valid, height: '0'}), false);
  assert.equal(canonicalContext({...valid, round: '18446744073709551615'}), true);
});
