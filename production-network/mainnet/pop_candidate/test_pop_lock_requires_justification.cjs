'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');

// Research-only candidate POP voting rule. This is NOT a deployed consensus
// implementation: certificates/signatures, persistence and network timing are
// not verified here. A validator must never unlock solely because a round rises.
function mayVote(lock, proposal) {
  if (!lock || !proposal || typeof lock !== 'object' || typeof proposal !== 'object') return false;
  const uint = x => Number.isSafeInteger(x) && x >= 0;
  if (!uint(lock.round) || !uint(proposal.round) || !uint(proposal.justifyRound)) return false;
  if (typeof lock.blockId !== 'string' || !lock.blockId ||
      typeof proposal.blockId !== 'string' || !proposal.blockId) return false;
  if (proposal.round <= lock.round) return false;
  if (proposal.blockId === lock.blockId) return true;
  // Justification must strictly supersede the existing lock and precede vote.
  // A production implementation must verify a quorum certificate for it.
  return proposal.justifyRound > lock.round && proposal.justifyRound < proposal.round &&
    proposal.justificationVerified === true;
}

test('candidate POP lock refuses conflicting proposals without newer verified justification', () => {
  const lock = {round: 4, blockId: 'A'};
  assert.equal(mayVote(lock, {round: 5, blockId: 'A', justifyRound: 0}), true);
  for (const proposal of [
    {round: 5, blockId: 'B', justifyRound: 4, justificationVerified: true},
    {round: 5, blockId: 'B', justifyRound: 5, justificationVerified: true},
    {round: 6, blockId: 'B', justifyRound: 5, justificationVerified: false},
    {round: 6, blockId: 'B', justifyRound: 5},
    {round: 4, blockId: 'B', justifyRound: 3, justificationVerified: true},
    {round: 3, blockId: 'A', justifyRound: 0},
    {round: 6, blockId: 'B', justifyRound: -1, justificationVerified: true},
    {round: 6.5, blockId: 'B', justifyRound: 5, justificationVerified: true},
    {round: Number.MAX_SAFE_INTEGER + 1, blockId: 'B', justifyRound: 5, justificationVerified: true}
  ]) assert.equal(mayVote(lock, proposal), false, JSON.stringify(proposal));
  assert.equal(mayVote(lock, {round: 6, blockId: 'B', justifyRound: 5, justificationVerified: true}), true);
});
