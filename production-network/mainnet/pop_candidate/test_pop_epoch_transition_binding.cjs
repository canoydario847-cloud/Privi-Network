'use strict';
// Research-only model: membership arithmetic is not signature verification.
const { test } = require('node:test');
const assert = require('node:assert/strict');

function verifyTransition(t, expected) {
  if (!t || !expected || !Number.isSafeInteger(t.fromEpoch) || !Number.isSafeInteger(t.toEpoch) ||
      t.fromEpoch < 0 || t.toEpoch !== t.fromEpoch + 1 || t.fromEpoch !== expected.fromEpoch ||
      t.toEpoch !== expected.toEpoch || typeof t.chainId !== 'string' ||
      t.chainId !== expected.chainId || !/^[a-z0-9][a-z0-9-]{0,63}$/.test(t.chainId) ||
      !/^[a-f0-9]{64}$/.test(t.transitionHash ?? '') || t.transitionHash !== expected.transitionHash) return false;
  for (const side of ['old', 'next']) {
    const members = t[side + 'Committee'];
    const signers = t[side + 'Signers'];
    if (!Array.isArray(members) || members.length < 4 || members.length > 31 ||
        !Array.isArray(signers) || !members.every(x => typeof x === 'string' && /^[a-zA-Z0-9_-]{1,64}$/.test(x)) ||
        new Set(members).size !== members.length || new Set(signers).size !== signers.length ||
        !signers.every(x => members.includes(x)) || signers.length < Math.floor(2 * members.length / 3) + 1) return false;
  }
  return true;
}

const hash = 'a'.repeat(64);
const base = {chainId:'privi-mainnet', fromEpoch:7, toEpoch:8, transitionHash:hash,
  oldCommittee:['a','b','c','d'], nextCommittee:['e','f','g','h'],
  oldSigners:['a','b','c'], nextSigners:['e','f','g']};
const expected = {chainId:'privi-mainnet', fromEpoch:7, toEpoch:8, transitionHash:hash};

test('candidate transition requires separate quorums even with disjoint committees', () => {
  assert.equal(verifyTransition(base, expected), true);
  assert.equal(verifyTransition({...base, oldSigners:['a','b']}, expected), false);
  assert.equal(verifyTransition({...base, nextSigners:['e','f']}, expected), false);
  assert.equal(verifyTransition({...base, nextSigners:['e','e','f','g']}, expected), false);
  assert.equal(verifyTransition({...base, oldCommittee:['a','b','c','c']}, expected), false);
  assert.equal(verifyTransition({...base, nextSigners:['e','f','a']}, expected), false);
});

test('candidate transition rejects epoch, chain and digest replay', () => {
  for (const change of [
    {toEpoch:9}, {fromEpoch:6}, {fromEpoch:8, toEpoch:9},
    {chainId:'privi-test'}, {transitionHash:'b'.repeat(64)},
    {transitionHash:'A'.repeat(64)}, {transitionHash:'x'},
  ]) assert.equal(verifyTransition({...base,...change},expected),false,JSON.stringify(change));
  assert.equal(verifyTransition(base,{...expected, toEpoch:9}),false);
});
