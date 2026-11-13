'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {createTrustedExecutionContextGate} = require('./create_trusted_execution_context_gate.cjs');

// Ensure identities resolved from separate authenticated connections never leak
// across simultaneous requests, even if the requests contain forged identities.
test('concurrent connections retain independent trusted execution identities', async () => {
  const contexts = new Map([
    ['conn-a', {tenantId:'tenant-a',agentId:'agent-a',actionId:'read',sessionId:'session-a'}],
    ['conn-b', {tenantId:'tenant-b',agentId:'agent-b',actionId:'write',sessionId:'session-b'}],
  ]);
  const seen = new Map();
  const gate = createTrustedExecutionContextGate({
    resolveTrustedContext: async connection => contexts.get(connection),
    authorize: async ({session, request}) => {
      seen.set(request.requestId, {...session});
      assert.equal(Object.isFrozen(session), true);
      return true;
    },
    executeAuthorized: async () => ({ok:true}),
  });
  const [a,b] = await Promise.all([
    gate.execute({connection:'conn-a',request:{requestId:'a',tenantId:'tenant-b',agentId:'agent-b'}}),
    gate.execute({connection:'conn-b',request:{requestId:'b',tenantId:'tenant-a',agentId:'agent-a'}}),
  ]);
  assert.deepEqual(a,{ok:true});
  assert.deepEqual(b,{ok:true});
  assert.deepEqual(seen.get('a'),contexts.get('conn-a'));
  assert.deepEqual(seen.get('b'),contexts.get('conn-b'));
});

test('authorization receives an immutable snapshot, not a mutable resolver object', async () => {
  const source={tenantId:'tenant-a',agentId:'agent-a',actionId:'read',sessionId:'session-a'};
  let observed;
  const gate=createTrustedExecutionContextGate({
    resolveTrustedContext: async () => source,
    authorize: async ({session}) => {
      source.tenantId='tenant-b';
      observed=session;
      return true;
    },
    executeAuthorized: async ({session}) => {
      assert.equal(session,observed);
      assert.equal(session.tenantId,'tenant-a');
      return {ok:true};
    },
  });
  assert.deepEqual(await gate.execute({request:{tenantId:'tenant-b'}}),{ok:true});
  assert.equal(observed.tenantId,'tenant-a');
  assert.equal(Object.isFrozen(observed),true);
});
