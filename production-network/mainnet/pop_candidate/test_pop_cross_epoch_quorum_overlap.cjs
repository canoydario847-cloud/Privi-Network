'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');

// Research-only safety counterexample; does not implement POP or verify signatures.
// Static >2/3 thresholds alone cannot guarantee cross-epoch quorum intersection.
function threshold(n) {
  if (!Number.isSafeInteger(n) || n < 4 || n > 31) throw new RangeError('committee size');
  return Math.floor(2 * n / 3) + 1;
}
function quorum(committee, signers) {
  if (!Array.isArray(committee) || !Array.isArray(signers)) return false;
  const members = new Set(committee);
  const votes = new Set(signers);
  return members.size === committee.length && votes.size === signers.length &&
    signers.every(id => members.has(id)) && signers.length >= threshold(committee.length);
}

test('disjoint rotating committees can independently certify conflicting blocks', () => {
  const oldCommittee = ['a', 'b', 'c', 'd'];
  const newCommittee = ['e', 'f', 'g', 'h'];
  const oldSigners = ['a', 'b', 'c'];
  const newSigners = ['e', 'f', 'g'];
  assert.equal(quorum(oldCommittee, oldSigners), true);
  assert.equal(quorum(newCommittee, newSigners), true);
  assert.equal(oldSigners.filter(id => newSigners.includes(id)).length, 0);
  // Both certificates can pass isolated quorum checks at the SAME height.
  // Production finality must bind transitions and prevent conflicting commits.
});

test('even overlapping committees may have disjoint valid signer quorums', () => {
  const oldCommittee = ['a', 'b', 'c', 'd'];
  const newCommittee = ['c', 'd', 'e', 'f'];
  assert.equal(quorum(oldCommittee, ['a', 'b', 'c']), true);
  assert.equal(quorum(newCommittee, ['d', 'e', 'f']), true);
  assert.equal(new Set(['a', 'b', 'c'].filter(id => ['d', 'e', 'f'].includes(id))).size, 0);
});

test('reject malformed quorum inputs', () => {
  assert.equal(quorum(['a', 'a', 'b', 'c'], ['a', 'b', 'c']), false);
  assert.equal(quorum(['a', 'b', 'c', 'd'], ['a', 'a', 'b']), false);
  assert.equal(quorum(['a', 'b', 'c', 'd'], ['a', 'b', 'x']), false);
  assert.throws(() => threshold(3), RangeError);
  assert.throws(() => threshold(32), RangeError);
});
