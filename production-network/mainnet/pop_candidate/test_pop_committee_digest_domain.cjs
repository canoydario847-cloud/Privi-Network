'use strict';
// Research-only canonical commitment; does not authenticate validators or finalize blocks.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { createHash } = require('node:crypto');

function committeeDigest(chainId, epoch, members) {
  if (typeof chainId !== 'string' || !/^[a-zA-Z0-9_-]{1,64}$/.test(chainId) ||
      !Number.isSafeInteger(epoch) || epoch < 0 ||
      !Array.isArray(members) || members.length < 4 || members.length > 31 ||
      !members.every(x => typeof x === 'string' && /^[A-Za-z0-9_-]{1,64}$/.test(x)) ||
      new Set(members).size !== members.length) throw new TypeError('invalid committee commitment');
  const ordered = members.slice().sort();
  const fields = ['PRVI-POP-COMMITTEE-V1', chainId, String(epoch), String(ordered.length), ...ordered];
  const h = createHash('sha256');
  for (const field of fields) {
    const b = Buffer.from(field, 'utf8');
    const size = Buffer.alloc(4);
    size.writeUInt32BE(b.length);
    h.update(size).update(b);
  }
  return h.digest('hex');
}

const members = ['val_a', 'val_b', 'val_c', 'val_d'];
test('committee digest is order-independent but binds chain, epoch, and membership', () => {
  const base = committeeDigest('privi-mainnet', 12, members);
  assert.match(base, /^[0-9a-f]{64}$/);
  assert.equal(base, committeeDigest('privi-mainnet', 12, members.slice().reverse()));
  assert.notEqual(base, committeeDigest('privi-mainnet', 13, members));
  assert.notEqual(base, committeeDigest('privi-other', 12, members));
  assert.notEqual(base, committeeDigest('privi-mainnet', 12, ['val_a','val_b','val_c','val_x']));
});
test('committee digest rejects ambiguous and malformed inputs', () => {
  for (const invalid of [[], ['a','b','c'], ['a','b','c','c'], ['a','b','c','d\n'], ['a','b','c',null]]) {
    assert.throws(() => committeeDigest('privi-mainnet', 0, invalid), TypeError);
  }
  for (const epoch of [-1, 1.5, Number.MAX_SAFE_INTEGER + 1, '1']) {
    assert.throws(() => committeeDigest('privi-mainnet', epoch, members), TypeError);
  }
  for (const chain of ['', 'privi mainnet', 'privi\nmainnet']) {
    assert.throws(() => committeeDigest(chain, 0, members), TypeError);
  }
});
