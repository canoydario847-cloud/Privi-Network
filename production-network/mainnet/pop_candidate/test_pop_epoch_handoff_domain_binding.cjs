'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { createHash } = require('node:crypto');

// Research-only domain-binding specification. Not a signature verifier or POP implementation.
// Both outgoing and incoming quorum certificates must commit to all these fields.
function commitment(x) {
  if (!x || typeof x !== 'object' || Array.isArray(x)) throw new TypeError('handoff object required');
  const {chainId, fromEpoch, toEpoch, finalizedCheckpoint, oldMembers, newMembers} = x;
  if (typeof chainId !== 'string' || !/^privi-[a-z0-9-]+$/.test(chainId)) throw new TypeError('chain id');
  if (typeof fromEpoch !== 'string' || !/^(0|[1-9][0-9]*)$/.test(fromEpoch)) throw new TypeError('epoch');
  if (typeof toEpoch !== 'string' || !/^(0|[1-9][0-9]*)$/.test(toEpoch) || BigInt(toEpoch) !== BigInt(fromEpoch) + 1n) throw new TypeError('epoch transition');
  if (typeof finalizedCheckpoint !== 'string' || !/^[0-9a-f]{64}$/.test(finalizedCheckpoint)) throw new TypeError('checkpoint');
  for (const members of [oldMembers, newMembers]) {
    if (!Array.isArray(members) || members.length < 4 || members.some(v => typeof v !== 'string' || !/^[a-z0-9-]{1,64}$/.test(v)) || new Set(members).size !== members.length) throw new TypeError('committee');
  }
  const canonical = [chainId, fromEpoch, toEpoch, finalizedCheckpoint, [...oldMembers].sort(), [...newMembers].sort()];
  return createHash('sha256').update(JSON.stringify(['PRVI_POP_HANDOFF_RESEARCH_V1', ...canonical])).digest('hex');
}

test('research handoff commitment binds both epochs, both committees, chain and checkpoint', () => {
  const x = {chainId:'privi-mainnet-candidate', fromEpoch:'9', toEpoch:'10', finalizedCheckpoint:'a'.repeat(64), oldMembers:['a','b','c','d'], newMembers:['b','c','d','e']};
  const baseline = commitment(x);
  assert.equal(commitment({...x, oldMembers:[...x.oldMembers].reverse(), newMembers:[...x.newMembers].reverse()}), baseline);
  for (const altered of [
    {...x, chainId:'privi-other-chain'},
    {...x, fromEpoch:'8', toEpoch:'9'},
    {...x, fromEpoch:'10', toEpoch:'11'},
    {...x, finalizedCheckpoint:'b'.repeat(64)},
    {...x, oldMembers:['a','b','c','f']},
    {...x, newMembers:['b','c','d','f']},
  ]) assert.notEqual(commitment(altered), baseline);
  for (const invalid of [
    {...x, toEpoch:'11'},
    {...x, fromEpoch:'09'},
    {...x, oldMembers:['a','a','c','d']},
    {...x, newMembers:['b','c','d','d']},
    {...x, finalizedCheckpoint:'not-a-hash'},
  ]) assert.throws(() => commitment(invalid), TypeError);
});
