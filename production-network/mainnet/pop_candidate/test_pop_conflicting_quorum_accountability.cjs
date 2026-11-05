'use strict';
// Research-only static committee arithmetic. Not a signature verifier or POP implementation.
const test = require('node:test');
const assert = require('node:assert/strict');

function quorum(n) { return Math.floor((2 * n) / 3) + 1; }
function faultBound(n) { return Math.floor((n - 1) / 3); }
function overlap(a, b) { return a.filter(x => b.includes(x)); }

test('conflicting same-round certificates require more than f overlapping signers', () => {
  for (let n = 4; n <= 31; n++) {
    const q = quorum(n);
    const first = Array.from({length:q}, (_,i) => i);
    // Choose the second quorum to minimize intersection with the first.
    const second = Array.from({length:q}, (_,i) => n - q + i);
    const shared = overlap(first, second);
    assert.equal(shared.length, 2*q-n, `N=${n} exact minimum intersection`);
    assert.ok(shared.length > faultBound(n), `N=${n} conflicting certificates imply >f equivocations`);
    assert.equal(new Set([...first,...second]).size,n,`N=${n} complete union`);
  }
});

test('context separation: different rounds do not by themselves prove equivocation', () => {
  const voteA = {chainId:'privi-mainnet', epoch:'1', height:'9', round:'2', blockId:'A', signer:'v1'};
  const voteB = {...voteA, round:'3', blockId:'B'};
  const sameSlot = (a,b) => ['chainId','epoch','height','round'].every(k => a[k] === b[k]);
  assert.equal(sameSlot(voteA,voteB),false);
  assert.equal(sameSlot(voteA,{...voteA,blockId:'B'}),true);
});
