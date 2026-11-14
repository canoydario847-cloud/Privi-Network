import test from 'node:test';
import assert from 'node:assert/strict';
import { createMcpOAuthHandler } from './mcp-gateway-adapter.mjs';

function reply() {
  return {
    status: 0, headers: {}, body: '',
    writeHead(code, headers) { this.status = code; this.headers = headers; },
    end(body = '') { this.body = body; }
  };
}
const config = {
  issuer: 'https://id.example.test',
  jwksUri: 'https://id.example.test/jwks',
  downstream(req, res) { res.writeHead(200, {}); res.end('downstream'); },
  fetcher: async () => { throw new Error('unauthorized request must not query JWKS'); }
};
test('resource discovery is public', async () => {
  const handler = createMcpOAuthHandler(config);
  const res = reply();
  await handler({ method: 'GET', url: '/.well-known/oauth-protected-resource/mcp', headers: {} }, res);
  assert.equal(res.status, 200);
  const payload = JSON.parse(res.body);
  assert.equal(payload.resource, 'https://privi-ai-21-gateway.onrender.com/mcp');
  assert.deepEqual(payload.authorization_servers, ['https://id.example.test']);
});
test('MCP denies anonymous requests with discovery challenge', async () => {
  const res = reply();
  await createMcpOAuthHandler(config)({ method: 'POST', url: '/mcp', headers: {} }, res);
  assert.equal(res.status, 401);
  assert.match(res.headers['WWW-Authenticate'], /resource_metadata=/);
});
test('unrelated paths retain original downstream handler', async () => {
  const res = reply();
  await createMcpOAuthHandler(config)({ method: 'GET', url: '/health', headers: {} }, res);
  assert.equal(res.status, 200);
});
test('rejects missing downstream handler', () => {
  assert.throws(() => createMcpOAuthHandler({ ...config, downstream: null }));
});
