'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');

// Research only: quorum overlap does not prove honest overlap across epochs.
const quorum = n => Math.floor(2 * n / 3) + 1;
const subsets = (xs, k) => k === 0 ? [[]] : xs.length < k ? [] : [
  ...subsets(xs.slice(1), k - 1).map(t => [xs[0], ...t]),
  ...subsets(xs.slice(1), k),
];

function minimumHonestOverlap(oldMembers, newMembers, faulty) {
  const oldQuorums = subsets(oldMembers, quorum(oldMembers.length));
  const newQuorums = subsets(newMembers, quorum(newMembers.length));
  return Math.min(...oldQuorums.flatMap(a => newQuorums.map(b =>
    a.filter(v => b.includes(v) && !faulty.has(v)).length)));
}

test('one replacement leaves only a potentially Byzantine intersection', () => {
  const oldMembers = ['a', 'b', 'c', 'd'];
  const newMembers = ['a', 'b', 'c', 'e'];
  assert.equal(minimumHonestOverlap(oldMembers, newMembers, new Set()), 1);
  assert.equal(minimumHonestOverlap(oldMembers, newMembers, new Set(['a'])), 0);
});

test('unchanged four-member committee retains honest quorum intersection with one faulty voter', () => {
  const members = ['a', 'b', 'c', 'd'];
  for (const faulty of members) {
    assert.equal(minimumHonestOverlap(members, members, new Set([faulty])), 1);
  }
});

// A transition with no shared validators has no quorum intersection even
// when every signer is honest. This must fail any naive continuity gate.
test('disjoint epoch committees have zero intersection without Byzantine faults', () => {
  const oldMembers = ['a', 'b', 'c', 'd'];
  const newMembers = ['e', 'f', 'g', 'h'];
  assert.equal(minimumHonestOverlap(oldMembers, newMembers, new Set()), 0);
  assert.equal(minimumHonestOverlap(newMembers, oldMembers, new Set()), 0);
});
