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

// Any one of the three retained validators could be Byzantine; a transition
// safety argument must not depend on knowing which signer is faulty.
test('one-replacement unsafe overlap is independent of Byzantine signer identity', () => {
  const oldMembers = ['a', 'b', 'c', 'd'];
  const newMembers = ['a', 'b', 'c', 'e'];
  for (const faulty of ['a', 'b', 'c']) {
    assert.equal(minimumHonestOverlap(oldMembers, newMembers, new Set([faulty])), 0,
      `faulty retained signer ${faulty}`);
    assert.equal(minimumHonestOverlap(newMembers, oldMembers, new Set([faulty])), 0,
      `reverse transition, faulty retained signer ${faulty}`);
  }
});

// Conservative research-only transition preflight. This does not authorize
// epoch changes: real safety also requires authenticated joint finality,
// durable locks, operator independence, and verified fault assumptions.
function minimumGuaranteedHonestIntersection(oldMembers, newMembers, maxFaulty) {
  if (!Array.isArray(oldMembers) || !Array.isArray(newMembers) ||
      oldMembers.length < 4 || newMembers.length < 4 ||
      new Set(oldMembers).size !== oldMembers.length ||
      new Set(newMembers).size !== newMembers.length ||
      !Number.isSafeInteger(maxFaulty) || maxFaulty < 0 ||
      maxFaulty > Math.floor((Math.min(oldMembers.length, newMembers.length) - 1) / 3)) return null;
  const intersection = oldMembers.filter(v => newMembers.includes(v)).length;
  const lowerBound = Math.max(0, quorum(oldMembers.length) +
    quorum(newMembers.length) -
    (oldMembers.length + newMembers.length - intersection));
  return Math.max(0, lowerBound - maxFaulty);
}

test('conservative cross-epoch preflight rejects unsafe overlap and malformed committees', () => {
  const a = ['a', 'b', 'c', 'd'];
  assert.equal(minimumGuaranteedHonestIntersection(a, a, 1), 1);
  assert.equal(minimumGuaranteedHonestIntersection(a, ['a', 'b', 'c', 'e'], 1), 0);
  assert.equal(minimumGuaranteedHonestIntersection(a, ['e', 'f', 'g', 'h'], 0), 0);
  assert.equal(minimumGuaranteedHonestIntersection(a, ['a', 'a', 'c', 'd'], 1), null);
  assert.equal(minimumGuaranteedHonestIntersection(a, a, -1), null);
  assert.equal(minimumGuaranteedHonestIntersection(a, a, 2), null);
  assert.equal(minimumGuaranteedHonestIntersection(a, a, 1.5), null);
});
