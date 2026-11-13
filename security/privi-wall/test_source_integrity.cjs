'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const {bytesForCall} = require('./agent_call_auth.cjs');

test('authorization module loads and exports canonical signing encoder', () => {
  assert.equal(typeof bytesForCall, 'function');
});

test('signed envelope allowlist is an executable declaration, not a commented line', () => {
  const src = readFileSync(join(__dirname, 'agent_call_auth.cjs'), 'utf8');
  assert.match(src, /^  const allowed = \[/m);
  assert.doesNotMatch(src, /\\n\s+(?:const allowed|if \()/);
});
