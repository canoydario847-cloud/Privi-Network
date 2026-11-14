import test from 'node:test';
import assert from 'node:assert/strict';
import { protectedResourceMetadata, oauthChallenge } from './mcp-metadata.mjs';

test('MCP resource metadata advertises identity provider', () => {
  const meta = protectedResourceMetadata({
    resource: 'https://privi-ai-21-gateway.onrender.com/mcp',
    authorizationServers: ['https://id.example.test'],
    scopesSupported: ['privi:tools:execute']
  });
  assert.deepEqual(meta.authorization_servers, ['https://id.example.test']);
  assert.equal(meta.resource, 'https://privi-ai-21-gateway.onrender.com/mcp');
});
test('rejects non-HTTPS issuer and resource', () => {
  assert.throws(() => protectedResourceMetadata({ resource: 'http://localhost/mcp', authorizationServers: ['https://id.example.test'] }));
  assert.throws(() => protectedResourceMetadata({ resource: 'https://example.test/mcp', authorizationServers: ['http://id.example.test'] }));
});
test('challenge contains discovery URL', () => {
  assert.match(oauthChallenge({ resourceMetadataUrl: 'https://example.test/.well-known/oauth-protected-resource/mcp' }), /resource_metadata=/);
});
