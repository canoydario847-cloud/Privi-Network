'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');

// Research-only certificate arithmetic: not a signature verifier or POP implementation.
function hasQuorum(committee, signers) {
  if (!Array.isArray(committee) || !Array.isArray(signers)) return false;
  const members = new Set(committee);
  if (members.size !== committee.length || members.size < 4) return false;
  if (signers.some((s) => !members.has(s))) return false;
  return new Set(signers).size >= Math.floor((2 * members.size) / 3) + 1;
}

test('candidate POP certificate counts distinct authorized validators only', () => {
  for (let n = 4; n <= 31; n++) {
    const committee = Array.from({ length: n }, (_, i) => `v${i}`);
    const q = Math.floor((2 * n) / 3) + 1;
    assert.equal(hasQuorum(committee, committee.slice(0, q)), true, `N=${n}: valid quorum`);
    assert.equal(hasQuorum(committee, committee.slice(0, q - 1)), false, `N=${n}: short quorum`);
    assert.equal(hasQuorum(committee, [...committee.slice(0, q - 1), committee[0]]), false, `N=${n}: duplicate signer`);
    assert.equal(hasQuorum(committee, [...committee.slice(0, q - 1), 'outsider']), false, `N=${n}: outsider`);
    assert.equal(hasQuorum([...committee, committee[0]], committee.slice(0, q)), false, `N=${n}: duplicate member`);
  }
});
