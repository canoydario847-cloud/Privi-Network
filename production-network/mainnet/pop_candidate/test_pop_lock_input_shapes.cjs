'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');

// Research-only candidate model. This is not production consensus or a signature verifier.
function mayVote(lock, proposal) {
  if (!lock || !proposal || typeof lock !== 'object' || typeof proposal !== 'object' ||
      Array.isArray(lock) || Array.isArray(proposal)) return false;
  const uint = x => Number.isSafeInteger(x) && x >= 0;
  if (!uint(lock.round) || !uint(proposal.round) || !uint(proposal.justifyRound)) return false;
  if (typeof lock.blockId !== 'string' || !lock.blockId.trim() ||
      typeof proposal.blockId !== 'string' || !proposal.blockId.trim()) return false;
  if (proposal.round <= lock.round) return false;
  if (proposal.blockId === lock.blockId) return true;
  return proposal.justifyRound > lock.round && proposal.justifyRound < proposal.round &&
    proposal.justificationVerified === true;
}

test('candidate POP voting rejects array-shaped records and blank block identifiers', () => {
  const lock = {round: 4, blockId: 'A'};
  const proposal = {round: 5, blockId: 'A', justifyRound: 0};
  assert.equal(mayVote(lock, proposal), true);
  assert.equal(mayVote(Object.assign([], lock), proposal), false);
  assert.equal(mayVote(lock, Object.assign([], proposal)), false);
  for (const blank of ['', ' ', '\t\n']) {
    assert.equal(mayVote({...lock, blockId: blank}, proposal), false);
    assert.equal(mayVote(lock, {...proposal, blockId: blank}), false);
  }
});
