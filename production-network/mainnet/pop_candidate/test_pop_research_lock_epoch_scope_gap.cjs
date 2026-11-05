"use strict";
// Research-only regression: demonstrates that ResearchVoteLock is scoped by
// epoch and cannot itself enforce cross-epoch finality. NOT production POP.
const test = require("node:test");
const assert = require("node:assert/strict");
const { ResearchVoteLock } = require("./engine.cjs");

const V = "0x" + "a".repeat(64);
const A = "0x" + "b".repeat(64);
const B = "0x" + "c".repeat(64);

test("research vote lock rejects conflicting blocks across rounds in one epoch", () => {
  const lock = new ResearchVoteLock();
  lock.accept(1, 7, 0, V, A);
  lock.accept(1, 7, 1, V, A);
  assert.throws(() => lock.accept(1, 7, 2, V, B),
    /conflicting-height double-sign/);
});

test("epoch-scoped lock allows conflicting blocks across epochs: unresolved handoff gap", () => {
  const lock = new ResearchVoteLock();
  lock.accept(1, 7, 0, V, A);
  // This behavior is intentionally documented as a GAP, not a safety guarantee.
  assert.doesNotThrow(() => lock.accept(2, 7, 0, V, B));
  assert.throws(() => lock.accept(2, 7, 1, V, A),
    /conflicting-height double-sign/);
});

test("research lock rejects invalid numeric rounds and block identifiers", () => {
  const lock = new ResearchVoteLock();
  assert.throws(() => lock.accept(1, 7, -1, V, A), /Invalid positive safe integer/);
  assert.throws(() => lock.accept(1, 7, Number.MAX_SAFE_INTEGER + 1, V, A),
    /Invalid positive safe integer/);
  assert.throws(() => lock.accept(1, 7, 0, V, "0xdead"), /Invalid vote block hash/);
});
