'use strict';
const assert = require('node:assert/strict');
const { test } = require('node:test');
const { createHash } = require('node:crypto');

// Research-only commitment; not a signature or production consensus verifier.
function transitionDigest({ chainId, fromEpoch, toEpoch, oldCommittee, newCommittee }) {
  if (typeof chainId !== 'string' || !/^[a-z0-9][a-z0-9-]{0,63}$/.test(chainId)) throw Error('chainId');
  if (!Number.isSafeInteger(fromEpoch) || fromEpoch < 0 || !Number.isSafeInteger(toEpoch) || toEpoch !== fromEpoch + 1) throw Error('epoch');
  const committee = (members) => {
    if (!Array.isArray(members) || members.length < 4 || members.length > 31) throw Error('committee size');
    if (members.some(x => typeof x !== 'string' || !/^[a-zA-Z0-9_-]{1,64}$/.test(x)) || new Set(members).size !== members.length) throw Error('committee member');
    return [...members].sort();
  };
  const oldMembers = committee(oldCommittee);
  const newMembers = committee(newCommittee);
  // Explicit counts prevent a validator named "new" from moving the committee boundary.
  const fields = ['PRVI-POP-TRANSITION-V1', chainId, String(fromEpoch), String(toEpoch),
    'old', String(oldMembers.length), ...oldMembers, 'new', String(newMembers.length), ...newMembers];
  const bytes = fields.map(x => `${Buffer.byteLength(x, 'utf8')}:${x}`).join('');
  return createHash('sha256').update(bytes).digest('hex');
}
const base = {chainId:'privi-mainnet-1',fromEpoch:10,toEpoch:11,oldCommittee:['a','b','c','d'],newCommittee:['e','f','g','h']};
test('transition commitment binds chain, both epochs, and both committees', () => {
  const original = transitionDigest(base);
  assert.equal(original, transitionDigest({...base,oldCommittee:['d','c','b','a'],newCommittee:['h','g','f','e']}));
  assert.notEqual(original,transitionDigest({...base,chainId:'privi-test-1'}));
  assert.notEqual(original,transitionDigest({...base,fromEpoch:11,toEpoch:12}));
  assert.notEqual(original,transitionDigest({...base,oldCommittee:['a','b','c','x']}));
  assert.notEqual(original,transitionDigest({...base,newCommittee:['e','f','g','x']}));
  assert.notEqual(original,transitionDigest({...base,oldCommittee:base.newCommittee,newCommittee:base.oldCommittee}));
});
test('malformed or replay-shaped transitions fail closed', () => {
  for (const change of [{toEpoch:10},{toEpoch:12},{fromEpoch:-1},{fromEpoch:1.5},{chainId:''},{oldCommittee:['a','a','b','c']},{newCommittee:['e','f','g','!']}]) {
    assert.throws(() => transitionDigest({...base,...change}));
  }
});
test('committee lengths prevent delimiter-name boundary ambiguity', () => {
  const left = {...base,oldCommittee:['a','b','c','d','new'],newCommittee:['x','y','z','zz']};
  const right = {...base,oldCommittee:['a','b','c','d'],newCommittee:['new','x','y','z','zz']};
  assert.notEqual(transitionDigest(left),transitionDigest(right));
});
