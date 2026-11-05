'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');

// Research-only: signer intersection is not a substitute for a safe epoch handoff.
const quorum = n => Math.floor(2 * n / 3) + 1;
const intersection = (a, b) => a.filter(x => b.includes(x)).length;

test('unequal consecutive committee sizes admit tight certificate-overlap bounds', () => {
  for (let oldSize = 4; oldSize <= 31; oldSize++) {
    for (let newSize = 4; newSize <= 31; newSize++) {
      for (let shared = 0; shared <= Math.min(oldSize, newSize); shared++) {
        const sharedIds = Array.from({length: shared}, (_, i) => `shared-${i}`);
        const oldOnly = Array.from({length: oldSize - shared}, (_, i) => `old-${i}`);
        const newOnly = Array.from({length: newSize - shared}, (_, i) => `new-${i}`);
        const oldQ = quorum(oldSize);
        const newQ = quorum(newSize);
        const oldNeed = Math.max(0, oldQ - oldOnly.length);
        const newNeed = Math.max(0, newQ - newOnly.length);
        const oldCert = [...oldOnly.slice(0, oldQ), ...sharedIds.slice(0, oldNeed)];
        const newCert = [...newOnly.slice(0, newQ), ...sharedIds.slice(shared - newNeed)];
        const minimum = Math.max(0, oldQ + newQ - (oldSize + newSize - shared));
        assert.equal(oldCert.length, oldQ);
        assert.equal(newCert.length, newQ);
        assert.equal(intersection(oldCert, newCert), minimum,
          `old=${oldSize}, new=${newSize}, shared=${shared}`);
      }
    }
  }
});
