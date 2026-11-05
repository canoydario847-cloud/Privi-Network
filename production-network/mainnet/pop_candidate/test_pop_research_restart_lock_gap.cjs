"use strict";
// Research-only: proves an in-memory lock is lost on process restart.
// This is a known NO-GO gap, not a production safety implementation.
const test = require("node:test");
const assert = require("node:assert/strict");
const { ResearchVoteLock } = require("./engine.cjs");
const voter = "0x" + "a".repeat(64);
const blockA = "0x" + "b".repeat(64);
const blockB = "0x" + "c".repeat(64);

test("research lock rejects conflicting same-epoch height vote while process survives", () => {
  const lock = new ResearchVoteLock();
  lock.accept(1, 7, 0, voter, blockA);
  assert.throws(() => lock.accept(1, 7, 1, voter, blockB), /conflicting-height double-sign/);
});

test("restart discards research lock: unsafe conflicting vote becomes accepted", () => {
  const beforeRestart = new ResearchVoteLock();
  beforeRestart.accept(1, 7, 0, voter, blockA);
  const afterRestart = new ResearchVoteLock();
  assert.doesNotThrow(() => afterRestart.accept(1, 7, 1, voter, blockB));
  assert.throws(() => afterRestart.accept(1, 7, 2, voter, blockA), /conflicting-height double-sign/);
});
