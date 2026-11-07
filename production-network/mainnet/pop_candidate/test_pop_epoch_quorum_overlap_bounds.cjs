'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');

// Research-only combinatorics; no production POP finality or validator handoff.
const quorum = n => Math.floor(2 * n / 3) + 1;
const common = (a, b) => a.filter(v => b.includes(v)).length;

test('cross-epoch minimum signer intersection is tight for every committee overlap (N=4..31)', () => {
  for (let n = 4; n <= 31; n++) {
    const q = quorum(n);
    for (let shared = 0; shared <= n; shared++) {
      const oldOnly = Array.from({length: n - shared}, (_, i) => `old-${i}`);
      const newOnly = Array.from({length: n - shared}, (_, i) => `new-${i}`);
      const sharedIds = Array.from({length: shared}, (_, i) => `shared-${i}`);
      const oldCommittee = [...oldOnly, ...sharedIds];
      const newCommittee = [...newOnly, ...sharedIds];
      const minimum = Math.max(0, 2 * q - (2 * n - shared));
      // Choose each certificate's exclusive members first, then disjoint shared
      // members wherever possible. This constructs a witness for the bound.
      const oldSharedCount = Math.max(0, q - oldOnly.length);
      const newSharedCount = Math.max(0, q - newOnly.length);
      const oldCertificate = [...oldOnly.slice(0, q), ...sharedIds.slice(0, oldSharedCount)];
      const newCertificate = [...newOnly.slice(0, q), ...sharedIds.slice(shared - newSharedCount)];
      assert.equal(oldCommittee.length, n);
      assert.equal(newCommittee.length, n);
      assert.equal(common(oldCommittee, newCommittee), shared);
      assert.equal(oldCertificate.length, q);
      assert.equal(newCertificate.length, q);
      assert.equal(common(oldCertificate, newCertificate), minimum,
        `N=${n}, shared=${shared}: exact minimum certificate overlap`);
    }
  }
});
