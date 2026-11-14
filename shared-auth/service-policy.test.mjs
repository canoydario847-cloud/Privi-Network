import test from 'node:test';
import assert from 'node:assert/strict';
import { SERVICES, servicePolicy, requiredScopes } from './service-policy.mjs';

test('every service has unique audience', () => {
  const audiences = Object.values(SERVICES).map(s => s.audience);
  assert.equal(new Set(audiences).size, audiences.length);
});
test('unknown services and scopes fail closed', () => {
  assert.throws(() => servicePolicy('unknown'));
  assert.throws(() => requiredScopes('gateway', ['privi:ledger:write']));
});
test('gateway execution scope accepted', () => {
  assert.deepEqual(requiredScopes('gateway', ['privi:tools:execute']), ['privi:tools:execute']);
});
