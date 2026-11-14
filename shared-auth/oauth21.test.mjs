import test from 'node:test';
import assert from 'node:assert/strict';
import { generateKeyPairSync, sign } from 'node:crypto';
import { createTokenVerifier, bearerToken } from './oauth21.mjs';

const { privateKey, publicKey } = generateKeyPairSync('rsa', { modulusLength: 2048 });
const jwk = { ...publicKey.export({ format: 'jwk' }), kid: 'test-key', alg: 'RS256', use: 'sig' };
const time = 1794682800;
const verifier = createTokenVerifier({
  issuer: 'https://identity.example.test',
  audience: 'privi-api',
  jwksUri: 'https://identity.example.test/jwks',
  now: () => time * 1000,
  fetcher: async () => ({ ok: true, json: async () => ({ keys: [jwk] }) })
});
function token(overrides = {}) {
  const header = Buffer.from(JSON.stringify({ alg: 'RS256', typ: 'at+jwt', kid: 'test-key' })).toString('base64url');
  const payload = Buffer.from(JSON.stringify({ iss: 'https://identity.example.test', aud: 'privi-api', sub: 'user-1', iat: time - 10, exp: time + 300, scope: 'privi:read', client_id: 'test-client', jti: 'token-1', ...overrides })).toString('base64url');
  const body = header + '.' + payload;
  return body + '.' + sign('RSA-SHA256', Buffer.from(body), privateKey).toString('base64url');
}
test('valid signed access token and scope', async () => {
  assert.equal((await verifier(token(), { scopes: ['privi:read'] })).sub, 'user-1');
});
test('rejects wrong audience', async () => { await assert.rejects(verifier(token({ aud: 'other' }))); });
test('rejects expired token', async () => { await assert.rejects(verifier(token({ exp: time - 1 }))); });
test('rejects missing scope', async () => { await assert.rejects(verifier(token(), { scopes: ['privi:write'] })); });
test('rejects tampered signature', async () => {
  const t = token(); const p = t.split('.'); p[1] = Buffer.from(JSON.stringify({ sub: 'attacker' })).toString('base64url');
  await assert.rejects(verifier(p.join('.')));
});
test('parses only Bearer scheme', () => {
  assert.equal(bearerToken('Bearer abc.def'), 'abc.def');
  assert.equal(bearerToken('Basic abc'), null);
});

test('rejects ID token claims without access-token identifiers', async () => { await assert.rejects(verifier(token({ client_id: null, jti: null }))); });
