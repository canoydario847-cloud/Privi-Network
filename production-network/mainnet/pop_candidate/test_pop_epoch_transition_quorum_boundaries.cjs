'use strict';
// Research-only membership arithmetic, not cryptographic signature validation or POP finality.
const { test } = require('node:test');
const assert = require('node:assert/strict');

function checkCommittee(members, signers) {
  if (!Array.isArray(members) || members.length < 4 || members.length > 31 ||
      !Array.isArray(signers) ||
      !members.every(x => typeof x === 'string' && /^[A-Za-z0-9_-]{1,64}$/.test(x)) ||
      new Set(members).size !== members.length ||
      !signers.every(x => typeof x === 'string' && members.includes(x)) ||
      new Set(signers).size !== signers.length) return false;
  return signers.length >= Math.floor(2 * members.length / 3) + 1;
}

test('both outgoing and incoming committees require independent strict two-thirds quorums at every supported size', () => {
  for (let oldSize = 4; oldSize <= 31; oldSize++) {
    for (let nextSize = 4; nextSize <= 31; nextSize++) {
      const old = Array.from({length: oldSize}, (_, i) => `old_${i}`);
      const next = Array.from({length: nextSize}, (_, i) => `next_${i}`);
      const oldQ = Math.floor(2 * oldSize / 3) + 1;
      const nextQ = Math.floor(2 * nextSize / 3) + 1;
      assert.equal(checkCommittee(old, old.slice(0, oldQ)), true);
      assert.equal(checkCommittee(next, next.slice(0, nextQ)), true);
      assert.equal(checkCommittee(old, old.slice(0, oldQ - 1)), false);
      assert.equal(checkCommittee(next, next.slice(0, nextQ - 1)), false);
    }
  }
});

test('committee identities and signer lists fail closed for malformed or duplicated entries', () => {
  const members = ['v0', 'v1', 'v2', 'v3'];
  for (const invalid of [null, [], ['v0','v1','v1'], ['v0','v1','outsider'], ['v0','v1',null], ['v0','v1',' v2'], ['v0','v1','v2\n']]) {
    assert.equal(checkCommittee(members, invalid), false);
  }
  for (const invalid of [['v0','v1','v2','v2'], ['v0','v1','v2',' '], ['v0','v1','v2',null]]) {
    assert.equal(checkCommittee(invalid, ['v0','v1','v2']), false);
  }
});
