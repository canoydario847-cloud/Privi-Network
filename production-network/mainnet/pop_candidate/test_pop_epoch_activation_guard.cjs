'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');

// Research-only negative specification. This does NOT implement production POP.
// A proposed epoch change must be certified by BOTH the outgoing and incoming
// committees, and the previous finalized checkpoint must be bound exactly.
const quorum = n => Math.floor(2 * n / 3) + 1;
function acceptsHandoff({oldMembers, newMembers, oldVotes, newVotes, expectedCheckpoint, checkpoint}) {
  if (checkpoint !== expectedCheckpoint) return false;
  if (new Set(oldMembers).size !== oldMembers.length || new Set(newMembers).size !== newMembers.length) return false;
  if (oldMembers.length < 4 || newMembers.length < 4) return false;
  const counts = (members, votes) => Array.isArray(votes) &&
    votes.length === new Set(votes).size &&
    votes.every(v => members.includes(v)) && votes.length >= quorum(members.length);
  return counts(oldMembers, oldVotes) && counts(newMembers, newVotes);
}

test('candidate handoff rejects one-sided quorum, replayed checkpoint and duplicate votes', () => {
  for (let oldSize = 4; oldSize <= 31; oldSize++) {
    for (let newSize = 4; newSize <= 31; newSize++) {
      const oldMembers = Array.from({length: oldSize}, (_, i) => `old-${i}`);
      const newMembers = Array.from({length: newSize}, (_, i) => `new-${i}`);
      const oldVotes = oldMembers.slice(0, quorum(oldSize));
      const newVotes = newMembers.slice(0, quorum(newSize));
      const base = {oldMembers, newMembers, oldVotes, newVotes, expectedCheckpoint:'height100:blockA', checkpoint:'height100:blockA'};
      assert.equal(acceptsHandoff(base), true);
      assert.equal(acceptsHandoff({...base, oldVotes:oldVotes.slice(1)}), false);
      assert.equal(acceptsHandoff({...base, newVotes:newVotes.slice(1)}), false);
      assert.equal(acceptsHandoff({...base, checkpoint:'height100:blockB'}), false);
      assert.equal(acceptsHandoff({...base, oldVotes:[...oldVotes, oldVotes[0]]}), false);
      assert.equal(acceptsHandoff({...base, newVotes:[...newVotes, newVotes[0]]}), false);
      assert.equal(acceptsHandoff({...base, newVotes:[...newVotes.slice(1), 'old-0']}), false);
    }
  }
});
