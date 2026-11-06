'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');

// Research-only necessary intersection arithmetic; not a POP finality protocol.
function threshold(n) {
  if (!Number.isSafeInteger(n) || n < 4 || n > 31) throw new RangeError('committee size');
  return Math.floor(2 * n / 3) + 1;
}
function minimumSharedSigners(oldSize, newSize, sharedMembers) {
  const oldQuorum = threshold(oldSize);
  const newQuorum = threshold(newSize);
  if (!Number.isSafeInteger(sharedMembers) || sharedMembers < 0 ||
      sharedMembers > Math.min(oldSize, newSize)) throw new RangeError('shared members');
  // Each quorum may avoid at most (size - quorum) committee members.
  return Math.max(0, sharedMembers - (oldSize - oldQuorum) - (newSize - newQuorum));
}

test('rotating committees require sufficient overlap for any shared quorum signer', () => {
  for (let oldSize = 4; oldSize <= 31; oldSize++) {
    for (let newSize = 4; newSize <= 31; newSize++) {
      const misses = oldSize - threshold(oldSize) + newSize - threshold(newSize);
      for (let shared = 0; shared <= Math.min(oldSize, newSize); shared++) {
        assert.equal(minimumSharedSigners(oldSize, newSize, shared), Math.max(0, shared - misses));
        assert.equal(minimumSharedSigners(oldSize, newSize, shared) > 0, shared > misses);
      }
    }
  }
});

test('quorum intersection does not prove honest overlap or safe epoch transitions', () => {
  assert.equal(minimumSharedSigners(4, 4, 2), 0);
  assert.equal(minimumSharedSigners(4, 4, 3), 1);
  assert.equal(minimumSharedSigners(4, 4, 4), 2);
  // A single overlapping signer may be Byzantine. No authenticated handoff is modeled.
  assert.equal(minimumSharedSigners(4, 4, 3) <= 1, true);
});

test('invalid committee and overlap inputs fail closed', () => {
  for (const args of [[3, 4, 2], [4, 32, 2], [4, 4, -1], [4, 4, 5], [4, 4, 1.5], [4, 4, NaN]]) {
    assert.throws(() => minimumSharedSigners(...args), RangeError);
  }
});
