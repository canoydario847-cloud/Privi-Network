'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');

// Research-only necessary arithmetic. This is NOT an epoch handoff protocol.
function quorum(n) {
  if (!Number.isSafeInteger(n) || n < 4 || n > 31) throw new RangeError('committee size');
  return Math.floor(2 * n / 3) + 1;
}
function guaranteedSharedHonestSigners(oldSize, newSize, sharedMembers, byzantineShared) {
  const oldQ = quorum(oldSize);
  const newQ = quorum(newSize);
  if (!Number.isSafeInteger(sharedMembers) || sharedMembers < 0 || sharedMembers > Math.min(oldSize, newSize))
    throw new RangeError('shared members');
  if (!Number.isSafeInteger(byzantineShared) || byzantineShared < 0 || byzantineShared > sharedMembers)
    throw new RangeError('shared Byzantine budget');
  const minIntersection = Math.max(0, sharedMembers - (oldSize - oldQ) - (newSize - newQ));
  return Math.max(0, minIntersection - byzantineShared);
}

test('a signer intersection may contain only Byzantine identities', () => {
  assert.equal(guaranteedSharedHonestSigners(4, 4, 3, 1), 0);
  assert.equal(guaranteedSharedHonestSigners(4, 4, 4, 1), 1);
  assert.equal(guaranteedSharedHonestSigners(7, 7, 7, 2), 1);
  assert.equal(guaranteedSharedHonestSigners(7, 7, 6, 2), 0);
});

test('necessary honest-overlap bounds hold for supported committee sizes', () => {
  for (let a = 4; a <= 31; a++) for (let b = 4; b <= 31; b++) {
    const misses = a - quorum(a) + b - quorum(b);
    for (let shared = 0; shared <= Math.min(a, b); shared++) {
      for (let faulty = 0; faulty <= shared; faulty++) {
        assert.equal(guaranteedSharedHonestSigners(a, b, shared, faulty), Math.max(0, shared - misses - faulty));
      }
    }
  }
});

test('invalid sizes and shared-fault assumptions fail closed', () => {
  for (const args of [[3, 4, 3, 0], [4, 32, 4, 0], [4, 4, 5, 0], [4, 4, -1, 0],
    [4, 4, 2, -1], [4, 4, 2, 3], [4, 4, 2, 0.5], [4, 4, NaN, 0]]) {
    assert.throws(() => guaranteedSharedHonestSigners(...args), RangeError);
  }
});
