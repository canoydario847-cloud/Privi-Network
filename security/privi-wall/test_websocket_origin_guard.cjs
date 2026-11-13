'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {assertWebSocketOrigin} = require('./websocket_origin_guard.cjs');
const policy = {allowedOrigins:['https://app.privi.example','http://localhost:3000']};
test('accepts exact trusted origins', () => {
  assert.equal(assertWebSocketOrigin({...policy,origin:'https://app.privi.example'}),true);
  assert.equal(assertWebSocketOrigin({...policy,origin:'http://localhost:3000'}),true);
});
test('rejects attacker-controlled subdomain and suffix', () => {
  for(const origin of ['https://app.privi.example.evil.test','https://evil-app.privi.example','https://privi.example'])
    assert.throws(()=>assertWebSocketOrigin({...policy,origin}),/origin rejected/);
});
test('rejects missing, null, and malformed origins', () => {
  for(const origin of [undefined,null,'null','', 'https://app.privi.example/', 'https://app.privi.example/path', 'https://app.privi.example?x=1', 'https://app.privi.example,https://evil.test','file://host','https://user@app.privi.example'])
    assert.throws(()=>assertWebSocketOrigin({...policy,origin}),/invalid origin/);
});
test('rejects empty or wildcard allowlists', () => {
  for(const allowedOrigins of [[],['*'],['https://*.privi.example'],null])
    assert.throws(()=>assertWebSocketOrigin({origin:'https://app.privi.example',allowedOrigins}),/invalid origin/);
});
test('rejects non-canonical policy origins', () => {
  assert.throws(()=>assertWebSocketOrigin({origin:'https://app.privi.example',allowedOrigins:['https://app.privi.example/']}),/invalid origin/);
});
