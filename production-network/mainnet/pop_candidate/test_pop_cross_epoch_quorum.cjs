'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');

// Research-only: committee arithmetic is NOT a POP consensus implementation.
// A valid same-epoch quorum does not automatically guarantee cross-epoch safety.
const quorum = (n) => Math.floor(2 * n / 3) + 1;
const minimumIntersection = (oldCommittee, newCommittee) => {
  const qOld = quorum(oldCommittee.length);
  const qNew = quorum(newCommittee.length);
  const universe = new Set([...oldCommittee, ...newCommittee]).size;
  return Math.max(0, qOld + qNew - universe);
};

// Enumerate every possible quorum pair to verify the analytical bound.
function combinations(items, count) {
  if (count === 0) return [[]];
  if (items.length < count) return [];
  return [
    ...combinations(items.slice(1), count - 1).map(rest => [items[0], ...rest]),
    ...combinations(items.slice(1), count),
  ];
}

test('same committee quorums intersect but churn can remove that guarantee', () => {
  const oldCommittee = ['a', 'b', 'c', 'd'];
  for (const newCommittee of [
    ['a', 'b', 'c', 'd'], // same epoch
    ['a', 'b', 'c', 'e'], // one replacement
    ['a', 'b', 'e', 'f'], // two replacements
    ['e', 'f', 'g', 'h'], // entirely new epoch
  ]) {
    const oldQuorums = combinations(oldCommittee, quorum(oldCommittee.length));
    const newQuorums = combinations(newCommittee, quorum(newCommittee.length));
    const observed = Math.min(...oldQuorums.flatMap(a => newQuorums.map(b =>
      a.filter(member => b.includes(member)).length)));
    assert.equal(observed, minimumIntersection(oldCommittee, newCommittee));
  }
  assert.equal(minimumIntersection(oldCommittee, oldCommittee), 2);
  assert.equal(minimumIntersection(oldCommittee, ['a', 'b', 'e', 'f']), 0);
});

test('cross-epoch zero intersection is possible even with valid 2/3+1 votes', () => {
  const oldCommittee = ['a', 'b', 'c', 'd'];
  const newCommittee = ['a', 'b', 'e', 'f'];
  const oldVotes = ['a', 'c', 'd'];
  const newVotes = ['b', 'e', 'f'];
  assert.equal(oldVotes.length, quorum(oldCommittee.length));
  assert.equal(newVotes.length, quorum(newCommittee.length));
  assert.deepEqual(oldVotes.filter(v => newVotes.includes(v)), []);
});
