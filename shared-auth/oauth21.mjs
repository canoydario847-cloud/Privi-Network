import { createPublicKey, verify as verifySignature } from 'node:crypto';

const ALGORITHMS = { RS256: 'RSA-SHA256', ES256: 'sha256' };
const decode = (part) => JSON.parse(Buffer.from(part, 'base64url').toString('utf8'));
const fail = (reason) => { throw new Error('OAuth access denied: ' + reason); };

export function createTokenVerifier({ issuer, audience, jwksUri, fetcher = fetch, now = () => Date.now(), cacheMs = 300000 }) {
  if (!issuer || !audience || !jwksUri || !issuer.startsWith('https://') || !jwksUri.startsWith('https://')) {
    throw new Error('HTTPS issuer, audience, and JWKS URI required');
  }
  let keys = null, expiry = 0;
  async function getKeys(force = false) {
    if (!force && keys && now() < expiry) return keys;
    const response = await fetcher(jwksUri, { headers: { Accept: 'application/json' }, signal: AbortSignal.timeout(5000) });
    if (!response.ok) fail('JWKS unavailable');
    const body = await response.json();
    if (!Array.isArray(body.keys) || body.keys.length > 100) fail('invalid JWKS');
    keys = body.keys; expiry = now() + cacheMs;
    return keys;
  }
  return async function verifyAccessToken(token, { scopes = [] } = {}) {
    if (typeof token !== 'string' || token.length > 16384) fail('invalid token');
    const parts = token.split('.');
    if (parts.length !== 3) fail('JWT required');
    let header, claims;
    try { header = decode(parts[0]); claims = decode(parts[1]); } catch { fail('malformed JWT'); }
    if (!Object.hasOwn(ALGORITHMS, header.alg) || !header.kid || !['at+jwt','application/at+jwt'].includes(header.typ)) fail('unsupported JWT header');
    let jwks = await getKeys();
    let key = jwks.find(k => k.kid === header.kid && k.kty === (header.alg === 'RS256' ? 'RSA' : 'EC') && (!k.use || k.use === 'sig') && (!k.alg || k.alg === header.alg) && (header.alg !== 'ES256' || k.crv === 'P-256'));
    if (!key) {
      jwks = await getKeys(true);
      key = jwks.find(k => k.kid === header.kid && k.kty === (header.alg === 'RS256' ? 'RSA' : 'EC') && (!k.use || k.use === 'sig') && (!k.alg || k.alg === header.alg) && (header.alg !== 'ES256' || k.crv === 'P-256'));
    }
    if (!key) fail('unknown signing key');
    let publicKey;
    try { publicKey = createPublicKey({ key, format: 'jwk' }); } catch { fail('invalid signing key'); }
    const signature = Buffer.from(parts[2], 'base64url');
    // ES256 JWT signatures use IEEE P1363, not ASN.1 DER.
    const valid = verifySignature(ALGORITHMS[header.alg], Buffer.from(parts[0] + '.' + parts[1]), { key: publicKey, ...(header.alg === 'ES256' ? { dsaEncoding: 'ieee-p1363' } : {}) }, signature);
    if (!valid) fail('invalid signature');
    const seconds = Math.floor(now() / 1000);
    if (claims.iss !== issuer || !(Array.isArray(claims.aud) ? claims.aud.includes(audience) : claims.aud === audience)) fail('issuer or audience mismatch');
    if (!Number.isFinite(claims.exp) || claims.exp <= seconds || !Number.isFinite(claims.iat) || claims.iat > seconds + 60 || (claims.nbf !== undefined && (!Number.isFinite(claims.nbf) || claims.nbf > seconds + 60))) fail('invalid token lifetime');
    if (typeof claims.sub !== 'string' || !claims.sub) fail('missing subject');
    if (typeof claims.client_id !== 'string' || !claims.client_id || typeof claims.jti !== 'string' || !claims.jti) fail('missing access token identifiers');
    const granted = new Set(typeof claims.scope === 'string' ? claims.scope.split(/\s+/) : []);
    if (scopes.some(s => !granted.has(s))) fail('insufficient scope');
    return claims;
  };
}

export function bearerToken(header) {
  if (typeof header !== 'string') return null;
  const match = /^Bearer ([A-Za-z0-9._~+/-]+=*)$/i.exec(header);
  return match ? match[1] : null;
}

export function requireOAuth(verifier, scopes = []) {
  return async (req, res, next) => {
    const token = bearerToken(req.headers.authorization);
    if (!token) {
      res.writeHead(401, { 'WWW-Authenticate': 'Bearer error="invalid_token"' }); res.end(); return;
    }
    try { req.oauth = await verifier(token, { scopes }); next(); }
    catch (error) {
      const insufficient = error.message.includes('insufficient scope');
      res.writeHead(insufficient ? 403 : 401, { 'WWW-Authenticate': insufficient ? 'Bearer error="insufficient_scope"' : 'Bearer error="invalid_token"' }); res.end();
    }
  };
}
