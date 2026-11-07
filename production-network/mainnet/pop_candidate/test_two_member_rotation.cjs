"use strict";
// POP research only: this is a counterexample test, not a rotation authorization.
const test = require("node:test");
const assert = require("node:assert/strict");

function combinations(xs, k) {
  if (k === 0) return [[]];
  if (xs.length < k) return [];
  return combinations(xs.slice(1), k - 1).map(t => [xs[0], ...t])
    .concat(combinations(xs.slice(1), k));
}

test("two-validator rotation may eliminate guaranteed honest POP quorum overlap", () => {
  const unsafe = new Set([4, 5, 7, 8]);
  for (let n = 4; n <= 8; n++) {
    const oldMembers = Array.from({length: n}, (_, i) => i);
    const newMembers = [...oldMembers.slice(0, -2), n, n + 1];
    const quorum = Math.floor(2 * n / 3) + 1;
    const faults = Math.floor((n - 1) / 3);
    let minShared = n;
    for (const oldCert of combinations(oldMembers, quorum)) {
      for (const newCert of combinations(newMembers, quorum)) {
        minShared = Math.min(minShared, oldCert.filter(x => newCert.includes(x)).length);
      }
    }
    assert.equal(minShared, Math.max(0, 2 * quorum - (n + 2)), `N=${n} minimum overlap`);
    assert.equal(minShared <= faults, unsafe.has(n), `N=${n} Byzantine-only intersection possible`);
  }
});
