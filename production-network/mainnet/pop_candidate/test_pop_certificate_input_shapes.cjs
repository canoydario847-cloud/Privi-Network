'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');

// Candidate POP certificate arithmetic only. No cryptographic verification.
function hasQuorum(committee, signers) {
  if (!Array.isArray(committee) || !Array.isArray(signers)) return false;
  if (committee.length < 4 || committee.length > 31) return false;
  if (!committee.every(id => typeof id === 'string' && id.length > 0)) return false;
  if (!signers.every(id => typeof id === 'string' && id.length > 0)) return false;
  const members = new Set(committee);
  if (members.size !== committee.length) return false;
  if (signers.some(id => !members.has(id))) return false;
  // Noncanonical repeated identities must fail even when a unique quorum exists.
  if (new Set(signers).size !== signers.length) return false;
  return signers.length >= Math.floor(2 * members.size / 3) + 1;
}

test('candidate POP quorum input validation fails closed for malformed identities and committee sizes', () => {
  const valid = ['a', 'b', 'c', 'd'];
  assert.equal(hasQuorum(valid, ['a', 'b', 'c']), true);
  for (const invalid of [null, undefined, {}, 'abcd', [], ['a', 'b', 'c'],
    Array.from({length: 32}, (_, i) => `v${i}`),
    ['a', 'b', 'c', ''], ['a', 'b', 'c', 1], ['a', 'b', 'c', null],
    ['a', 'b', 'c', 'c']]) {
    assert.equal(hasQuorum(invalid, ['a', 'b', 'c']), false);
  }
  for (const invalid of [null, undefined, {}, 'abc', ['a', 'b', 3],
    ['a', 'b', null], ['a', 'b', ''], ['a', 'b', 'outsider'],
    ['a', 'a', 'a'], ['a', 'b', 'c', 'a'], ['a', 'b', 'c', 'c']]) {
    assert.equal(hasQuorum(valid, invalid), false);
  }
});
