'use strict';
// Regression coverage for the current fail-closed offline audit API.
// Tests exact account+denom reconciliation; no financial mainnet authorization.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { auditGenesisAllocations } = require('./audit_genesis_allocations.cjs');

const genesis = () => ({ app_state: { bank: {
  balances: [
    { address: 'wallet1', coins: [{ denom: 'aprvi', amount: '900719925474099300000' }] },
    { address: 'wallet2', coins: [{ denom: 'aprvi', amount: '100' }] },
  ],
  supply: [{ denom: 'aprvi', amount: '900719925474099300100' }],
} } });
const manifest = () => ({ allocations: [
  { address: 'wallet1', denom: 'aprvi', amount: '900719925474099300000' },
  { address: 'wallet2', denom: 'aprvi', amount: '100' },
] });

test('exact allocations match with BigInt precision', () =>
  assert.deepEqual(auditGenesisAllocations(genesis(), manifest()), []));

test('wrong amount fails', () => {
  const m = manifest(); m.allocations[0].amount = '900719925474099300001';
  assert.ok(auditGenesisAllocations(genesis(), m).some(x => x.includes('differs')));
});

test('missing bank account fails', () => {
  const g = genesis(); g.app_state.bank.balances.pop();
  assert.ok(auditGenesisAllocations(g, manifest()).length);
});

test('undeclared bank account fails even without an exact-mode flag', () => {
  const m = manifest(); m.allocations.pop();
  assert.ok(auditGenesisAllocations(genesis(), m).some(x => x.includes('missing from allocation manifest')));
});

test('duplicate manifest account+denom fails', () => {
  const m = manifest(); m.allocations.push({ ...m.allocations[0] });
  assert.ok(auditGenesisAllocations(genesis(), m).some(x => x.includes('duplicate allocation')));
});

test('malformed amount fails', () => {
  const m = manifest(); m.allocations[0].amount = '01';
  assert.ok(auditGenesisAllocations(genesis(), m).some(x => x.includes('invalid allocation')));
});

test('missing manifest fails closed', () =>
  assert.ok(auditGenesisAllocations(genesis(), {}).some(x => x.includes('missing allocation manifest'))));

test('no optional exact-account flag is needed for strict reconciliation', () => {
  assert.deepEqual(auditGenesisAllocations(genesis(), manifest()), []);
  const m = manifest(); m.allocations.pop();
  assert.ok(auditGenesisAllocations(genesis(), m).length);
});

test('legacy disabled flag cannot weaken reconciliation', () => {
  const m = manifest(); m.requireExactAccounts = false; m.allocations.pop();
  assert.ok(auditGenesisAllocations(genesis(), m).some(x => x.includes('missing from allocation manifest')));
});

test('missing allocation and conflicting legacy flag remain rejected', () => {
  const m = manifest(); m.allocations.pop(); m.requireExactAccounts = true;
  assert.ok(auditGenesisAllocations(genesis(), m).length);
});
