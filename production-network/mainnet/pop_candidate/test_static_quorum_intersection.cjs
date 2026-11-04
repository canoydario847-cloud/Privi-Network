"use strict";
// Static quorum arithmetic research only. This is NOT a PoP consensus protocol,
// proof of finality, validator independence, or permission to launch mainnet.
const test = require("node:test");
const assert = require("node:assert/strict");

test("candidate PoP static committees have Byzantine quorum intersection", () => {
  // Research engine permits N = 4..31, with q = floor(2N/3) + 1.
  // For any two quorums of size q drawn from the SAME N-member committee,
  // minimum overlap is 2q-N; safety requires it exceed f=floor((N-1)/3).
  for (let n = 4; n <= 31; n++) {
    const quorum = Math.floor((2 * n) / 3) + 1;
    const faults = Math.floor((n - 1) / 3);
    const minOverlap = 2 * quorum - n;
    assert.ok(minOverlap > faults,
      `N=${n}: quorum intersection ${minOverlap} must exceed ${faults} Byzantine members`);
    assert.ok(quorum <= n, `N=${n}: quorum must fit committee`);
  }
});

test("candidate PoP quorum cannot be reduced to simple majority", () => {
  for (let n = 4; n <= 31; n++) {
    const faults = Math.floor((n - 1) / 3);
    const majority = Math.floor(n / 2) + 1;
    // A majority may intersect in <= f validators, so it is not a
    // substitute for the candidate supermajority threshold.
    if (2 * majority - n <= faults) {
      assert.ok(majority < Math.floor((2 * n) / 3) + 1);
    }
  }
});
