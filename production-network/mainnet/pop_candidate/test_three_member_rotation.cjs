"use strict";
// POP research only: quorum arithmetic cannot authorize validator rotation.
const test = require("node:test");
const assert = require("node:assert/strict");

function combinations(xs, k) {
  if (k === 0) return [[]];
  if (xs.length < k) return [];
  return combinations(xs.slice(1), k - 1).map(t => [xs[0], ...t])
    .concat(combinations(xs.slice(1), k));
}

test("three-member rotation cross-epoch quorum overlap is not a finality proof", () => {
  for (let n = 4; n <= 8; n++) {
    const oldMembers = Array.from({ length: n }, (_, i) => i);
    const newMembers = [...oldMembers.slice(0, -3), n, n + 1, n + 2];
    const q = Math.floor(2 * n / 3) + 1;
    const f = Math.floor((n - 1) / 3);
    let minShared = n;
    for (const a of combinations(oldMembers, q)) {
      for (const b of combinations(newMembers, q)) {
        minShared = Math.min(minShared, a.filter(id => b.includes(id)).length);
      }
    }
    const bound = Math.max(0, 2 * q - (n + 3));
    assert.equal(minShared, bound, `N=${n}: exhaustive minimum overlap`);
    assert.equal(minShared <= f, true, `N=${n}: cannot guarantee honest intersection`);
  }
});
