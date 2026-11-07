'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');

// Research-only fixture gate, NOT wired to chain genesis or bank/mint modules.
// Inputs are whole native PRVI units as canonical decimal strings.
const CAP = 1000000000n;
function validAllocationPlan(entries) {
  if (!Array.isArray(entries) || entries.length === 0) return false;
  let total = 0n;
  const accounts = new Set();
  for (const entry of entries) {
    if (!entry || Array.isArray(entry) || typeof entry !== 'object' ||
        typeof entry.account !== 'string' || !entry.account.trim() ||
        entry.account !== entry.account.trim() || accounts.has(entry.account) ||
        typeof entry.amount !== 'string' || !/^(0|[1-9][0-9]*)$/.test(entry.amount)) return false;
    accounts.add(entry.account);
    const amount = BigInt(entry.amount);
    if (amount > CAP - total) return false;
    total += amount;
  }
  return total === CAP;
}

test('candidate native PRVI genesis allocations sum to exactly one billion', () => {
  assert.equal(validAllocationPlan([{account:'liquid',amount:'900000000'}, {account:'vesting',amount:'100000000'}]), true);
  assert.equal(validAllocationPlan([{account:'liquid',amount:'900000000'}, {account:'vesting',amount:'99999999'}]), false);
  assert.equal(validAllocationPlan([{account:'liquid',amount:'900000000'}, {account:'vesting',amount:'100000001'}]), false);
});

test('reject malformed, duplicated and noncanonical allocation entries', () => {
  const base = [{account:'liquid',amount:'900000000'}, {account:'vesting',amount:'100000000'}];
  for (const invalid of ['-1','1.0','1e8',' 100000000','0100000000', 'NaN']) {
    assert.equal(validAllocationPlan([base[0],{account:'vesting',amount:invalid}]), false, invalid);
  }
  assert.equal(validAllocationPlan([base[0],{account:'liquid',amount:'100000000'}]), false);
  assert.equal(validAllocationPlan([base[0],{account:' vesting',amount:'100000000'}]), false);
  assert.equal(validAllocationPlan([base[0],{account:'vesting',amount:100000000}]), false);
  assert.equal(validAllocationPlan([]), false);
});
