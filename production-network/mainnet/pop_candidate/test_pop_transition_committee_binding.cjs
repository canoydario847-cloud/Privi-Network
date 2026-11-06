'use strict';
// Research-only membership binding. No signatures or consensus finality are verified.
const { test } = require('node:test');
const assert = require('node:assert/strict');

function verifyMembershipBinding(transition, expected) {
  if (!transition || !expected || !Array.isArray(transition.oldCommittee) ||
      !Array.isArray(transition.nextCommittee)) return false;
  for (const side of ['old', 'next']) {
    const actual = transition[side + 'Committee'];
    const committed = expected[side + 'Committee'];
    if (!Array.isArray(committed) || actual.length < 4 || actual.length > 31 ||
        actual.length !== committed.length ||
        !actual.every(id => typeof id === 'string' && /^[A-Za-z0-9_-]{1,64}$/.test(id)) ||
        !committed.every(id => typeof id === 'string' && /^[A-Za-z0-9_-]{1,64}$/.test(id)) ||
        new Set(actual).size !== actual.length || new Set(committed).size !== committed.length ||
        actual.slice().sort().some((id, i) => id !== committed.slice().sort()[i])) return false;
  }
  return true;
}

const expected = { oldCommittee: ['a','b','c','d'], nextCommittee: ['e','f','g','h'] };
test('transition committee identity is bound to expected membership, not only signer counts', () => {
  assert.equal(verifyMembershipBinding(expected, expected), true);
  assert.equal(verifyMembershipBinding({oldCommittee:['d','c','b','a'],nextCommittee:['h','g','f','e']}, expected), true);
  assert.equal(verifyMembershipBinding({oldCommittee:['a','b','c','x'],nextCommittee:expected.nextCommittee}, expected), false);
  assert.equal(verifyMembershipBinding({oldCommittee:expected.oldCommittee,nextCommittee:['e','f','g','x']}, expected), false);
  assert.equal(verifyMembershipBinding({oldCommittee:expected.nextCommittee,nextCommittee:expected.oldCommittee}, expected), false);
});
test('committee binding rejects duplicate and malformed identities', () => {
  for (const bad of [['a','b','c','c'], ['a','b','c',' d'], ['a','b','c','d\n'], ['a','b','c',null]]) {
    assert.equal(verifyMembershipBinding({oldCommittee:bad,nextCommittee:expected.nextCommittee},expected),false);
  }
  assert.equal(verifyMembershipBinding(null, expected), false);
  assert.equal(verifyMembershipBinding(expected, null), false);
});
