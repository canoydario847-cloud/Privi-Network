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

test("candidate PoP quorum pairs retain honest overlap under bounded faults", () => {
  // Exhaustive small-committee model check; assumes unique validator IDs,
  // a fixed membership set, and at most f Byzantine identities.
  const combinations = (n, k) => {
    const result = [];
    const visit = (start, chosen) => {
      if (chosen.length === k) { result.push([...chosen]); return; }
      for (let i = start; i <= n - (k - chosen.length); i++) {
        chosen.push(i);
        visit(i + 1, chosen);
        chosen.pop();
      }
    };
    visit(0, []);
    return result;
  };
  for (let n = 4; n <= 8; n++) {
    const q = Math.floor(2 * n / 3) + 1;
    const f = Math.floor((n - 1) / 3);
    const quorums = combinations(n, q);
    for (const a of quorums) {
      for (const b of quorums) {
        const overlap = a.filter(id => b.includes(id));
        assert.ok(overlap.length > f,
          `N=${n}: two quorum certificates must overlap beyond f=${f}`);
      }
    }
  }
});

test("static quorum safety does not extend automatically across membership changes", () => {
  // Two individually valid 4-member epochs can have disjoint certificates.
  // This counterexample MUST remain possible until a separate reconfiguration
  // protocol proves cross-epoch safety (joint consensus or equivalent).
  const oldEpoch = new Set(["a", "b", "c", "d"]);
  const newEpoch = new Set(["e", "f", "g", "h"]);
  const quorumSize = n => Math.floor(2 * n / 3) + 1;
  const oldCertificate = ["a", "b", "c"];
  const newCertificate = ["e", "f", "g"];
  assert.equal(oldCertificate.length, quorumSize(oldEpoch.size));
  assert.equal(newCertificate.length, quorumSize(newEpoch.size));
  assert.ok(oldCertificate.every(id => oldEpoch.has(id)));
  assert.ok(newCertificate.every(id => newEpoch.has(id)));
  assert.equal(oldCertificate.filter(id => newCertificate.includes(id)).length, 0,
    "independent valid epoch quorums need not intersect");
});
