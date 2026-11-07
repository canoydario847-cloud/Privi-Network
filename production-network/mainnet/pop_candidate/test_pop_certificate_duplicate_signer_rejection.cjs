'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');

// Research-only certificate shape guard, not cryptographic signature verification.
// Reject noncanonical duplicate signer identities even when unique quorum is met.
function acceptsSignerSet(committee, signers) {
  if (!Array.isArray(committee) || !Array.isArray(signers)) return false;
  if (committee.length < 4 || committee.length > 31) return false;
  if (!committee.every(id => typeof id === 'string' && id.length > 0)) return false;
  if (!signers.every(id => typeof id === 'string' && id.length > 0)) return false;
  const members = new Set(committee);
  const uniqueSigners = new Set(signers);
  if (members.size !== committee.length || uniqueSigners.size !== signers.length) return false;
  if (signers.some(id => !members.has(id))) return false;
  return uniqueSigners.size >= Math.floor(2 * committee.length / 3) + 1;
}

test('candidate POP certificate rejects duplicate signers even with sufficient unique quorum', () => {
  for (let n = 4; n <= 31; n++) {
    const committee = Array.from({length: n}, (_, i) => `validator-${i}`);
    const q = Math.floor(2 * n / 3) + 1;
    const quorum = committee.slice(0, q);
    assert.equal(acceptsSignerSet(committee, quorum), true, `N=${n} canonical quorum`);
    assert.equal(acceptsSignerSet(committee, [...quorum, quorum[0]]), false, `N=${n} duplicate after quorum`);
    assert.equal(acceptsSignerSet(committee, [...quorum, quorum[q-1]]), false, `N=${n} duplicate final signer`);
    assert.equal(acceptsSignerSet(committee, committee.slice(0, q-1)), false, `N=${n} under quorum`);
  }
});
