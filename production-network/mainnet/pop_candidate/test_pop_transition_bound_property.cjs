'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');

// Research-only: verify the conservative cross-epoch bound against enumeration.
// This is NOT an implementation of POP finality or permission to rotate validators.
const quorum = n => Math.floor(2 * n / 3) + 1;
function choose(items, k) {
  if (k === 0) return [[]];
  if (items.length < k) return [];
  return [
    ...choose(items.slice(1), k - 1).map(xs => [items[0], ...xs]),
    ...choose(items.slice(1), k),
  ];
}
function analytic(oldMembers, newMembers, f) {
  const shared = oldMembers.filter(v => newMembers.includes(v)).length;
  const union = oldMembers.length + newMembers.length - shared;
  return Math.max(0, quorum(oldMembers.length) + quorum(newMembers.length) - union - f);
}
function exhaustive(oldMembers, newMembers, faulty) {
  let min = Infinity;
  for (const a of choose(oldMembers, quorum(oldMembers.length))) {
    for (const b of choose(newMembers, quorum(newMembers.length))) {
      const overlap = a.filter(v => b.includes(v) && !faulty.has(v)).length;
      min = Math.min(min, overlap);
    }
  }
  return min;
}
test('analytical cross-epoch bound matches exhaustive worst case for all 4-member rotations', () => {
  const oldMembers = ['a', 'b', 'c', 'd'];
  const candidates = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'];
  let cases = 0;
  for (const newMembers of choose(candidates, 4)) {
    const union = [...new Set([...oldMembers, ...newMembers])];
    for (const faulty of [new Set(), ...union.map(v => new Set([v]))]) {
      const expected = analytic(oldMembers, newMembers, faulty.size);
      assert.equal(exhaustive(oldMembers, newMembers, faulty), expected,
        `rotation ${newMembers.join(',')} faulty ${[...faulty].join(',')}`);
      assert.equal(exhaustive(newMembers, oldMembers, faulty), expected,
        'reverse rotation must have same bound');
      cases++;
    }
  }
  assert.equal(cases, 560); // 70 committees, each with empty + 7 faulty choices.
});
