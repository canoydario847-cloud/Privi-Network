'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');

// Research-only set arithmetic, NOT production POP or signature verification.
const quorum = n => Math.floor(2 * n / 3) + 1;
const intersection = (a, b) => a.filter(x => b.includes(x)).length;

test('same-size epoch rotation can yield disjoint valid quorums without handoff rules', () => {
  for (let n = 4; n <= 31; n++) {
    const oldCommittee = Array.from({length: n}, (_, i) => `old-${i}`);
    const newCommittee = Array.from({length: n}, (_, i) => `new-${i}`);
    const oldCertificate = oldCommittee.slice(0, quorum(n));
    const newCertificate = newCommittee.slice(0, quorum(n));
    assert.equal(oldCertificate.length, quorum(n));
    assert.equal(newCertificate.length, quorum(n));
    assert.equal(intersection(oldCertificate, newCertificate), 0,
      `N=${n}: two individually quorate certificates need not share signers across epochs`);
  }
});

test('N-1 member overlap imposes a calculable minimum certificate intersection', () => {
  for (let n = 4; n <= 31; n++) {
    const oldCommittee = Array.from({length: n}, (_, i) => `v${i}`);
    const newCommittee = [...oldCommittee.slice(1), 'replacement'];
    // This test makes no assumption that arbitrary certificates can finalize
    // conflicting blocks; it demonstrates why epoch handoff needs protocol rules.
    const oldCertificate = oldCommittee.slice(0, quorum(n));
    const newCertificate = newCommittee.slice(-quorum(n));
    assert.equal(intersection(oldCommittee, newCommittee), n - 1);
    const unionSize = n + 1;
    const guaranteedMinimum = Math.max(0, 2 * quorum(n) - unionSize);
    assert.ok(intersection(oldCertificate, newCertificate) >= guaranteedMinimum,
      `N=${n}: set intersection must meet the union-size lower bound`);
  }
});
