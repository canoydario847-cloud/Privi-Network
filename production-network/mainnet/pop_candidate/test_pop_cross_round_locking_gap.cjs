'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');

// Research-only counterexample: quorum intersection alone does not guarantee
// safety across rounds unless honest validators enforce a persistent lock.
const quorum = n => Math.floor(2 * n / 3) + 1;
const faults = n => Math.floor((n - 1) / 3);

test('cross-round conflicting quorums require honest lock enforcement (N=4..31)', () => {
  for (let n = 4; n <= 31; n++) {
    const q = quorum(n);
    const f = faults(n);
    const first = new Set(Array.from({length: q}, (_, i) => i));
    const second = new Set(Array.from({length: q}, (_, i) => n - q + i));
    const overlap = [...first].filter(i => second.has(i));
    assert.equal(overlap.length, 2 * q - n, `N=${n}: minimal intersection`);
    assert.ok(overlap.length > f, `N=${n}: overlap contains honest signers`);
    // If honest members in the overlap sign conflicting blocks at a new round,
    // both certificates pass static quorum arithmetic. This is NOT a valid
    // protocol trace; it is a negative specification for the missing lock rule.
    const blockA = {height: 100, round: 1, block: 'A', signers: first};
    const blockB = {height: 100, round: 2, block: 'B', signers: second};
    assert.equal(blockA.signers.size, q);
    assert.equal(blockB.signers.size, q);
    assert.notEqual(blockA.block, blockB.block);
    assert.notEqual(blockA.round, blockB.round);
  }
});
