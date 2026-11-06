'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { ResearchVoteLock } = require('./engine.cjs');

// Research-only: in-memory safety within one epoch. Does not protect restarts
// or cross-epoch signing; never treat this as production POP finality.
const A = '0x' + 'a'.repeat(64);
const B = '0x' + 'b'.repeat(64);
const C = '0x' + 'c'.repeat(64);
const X = '0x' + '1'.repeat(64);
const Y = '0x' + '2'.repeat(64);

test('research lock: round changes cannot override a signed height', () => {
  const lock = new ResearchVoteLock();
  lock.accept(1, 100, 0, A, X);
  lock.accept(1, 100, 0, A, X); // identical retry
  lock.accept(1, 100, 900, A, X); // same block, later round
  assert.throws(() => lock.accept(1, 100, 901, A, Y), /conflicting-height/);
  assert.throws(() => lock.accept(1, 100, 0, A, Y), /conflicting-height/);
  // A rejected attempt must not mutate the existing lock.
  lock.accept(1, 100, 902, A, X);
});

test('research lock: distinct validator identities and heights remain independent', () => {
  const lock = new ResearchVoteLock();
  lock.accept(1, 100, 0, A, X);
  lock.accept(1, 100, 0, B, Y);
  lock.accept(1, 101, 0, A, Y);
  lock.accept(1, 100, 0, C, Y);
  assert.throws(() => lock.accept(1, 100, 1, B, X), /conflicting-height/);
  lock.accept(1, 101, 1, A, Y);
});
