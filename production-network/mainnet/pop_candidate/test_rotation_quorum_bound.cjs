"use strict";
// POP research regression only: membership changes are NOT authorized by this test.
const test = require("node:test");
const assert = require("node:assert/strict");

test("one-member rotation lacks guaranteed honest certificate intersection for N=4..8", () => {
  const combinations = (members, k) => {
    if (k === 0) return [[]];
    if (members.length < k) return [];
    return combinations(members.slice(1), k - 1).map(tail => [members[0], ...tail])
      .concat(combinations(members.slice(1), k));
  };
  for (let n = 4; n <= 8; n++) {
    const oldMembers = Array.from({ length: n }, (_, i) => i);
    const newMembers = [...oldMembers.slice(0, -1), n];
    const q = Math.floor(2 * n / 3) + 1;
    const f = Math.floor((n - 1) / 3);
    const oldQuorums = combinations(oldMembers, q);
    const newQuorums = combinations(newMembers, q);
    let minIntersection = n;
    for (const oldCert of oldQuorums) {
      for (const newCert of newQuorums) {
        const shared = oldCert.filter(id => newCert.includes(id)).length;
        minIntersection = Math.min(minIntersection, shared);
      }
    }
    assert.equal(minIntersection, Math.max(0, 2 * q - (n + 1)),
      `N=${n}: cross-epoch minimum intersection`);
    // Explicit expected counterexamples prevent this test from passing vacuously.
    // A static overlap bound is NOT sufficient to authorize any rotation.
    const expectedUnsafe = new Set([4, 7]);
    assert.equal(minIntersection <= f, expectedUnsafe.has(n),
      `N=${n}: unexpected honest-overlap classification`);
    assert.equal(minIntersection > f, !expectedUnsafe.has(n),
      `N=${n}: honest-overlap lower bound`);
  }
});
