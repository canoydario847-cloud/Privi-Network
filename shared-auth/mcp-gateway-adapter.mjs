// Optional gateway integration adapter. Requires a configured external issuer.
// Do not enable on deployed gateways until end-to-end auth tests pass.
import { createTokenVerifier, bearerToken } from './oauth21.mjs';
import { protectedResourceMetadata, oauthChallenge, sendProtectedResourceMetadata } from './mcp-metadata.mjs';
import { servicePolicy } from './service-policy.mjs';

export function createMcpOAuthHandler({
  issuer, jwksUri, resource = servicePolicy('gateway').resource,
  audience = servicePolicy('gateway').audience,
  downstream,
  metadataPath = '/.well-known/oauth-protected-resource/mcp',
  fetcher
}) {
  if (typeof downstream !== 'function') throw new Error('Downstream MCP handler required');
  const metadata = protectedResourceMetadata({
    resource, authorizationServers: [issuer],
    scopesSupported: servicePolicy('gateway').scopes
  });
  const verify = createTokenVerifier({ issuer, jwksUri, audience, ...(fetcher ? { fetcher } : {}) });
  const challenge = oauthChallenge({ resourceMetadataUrl: new URL(metadataPath, new URL(resource).origin).href });
  return async function handle(req, res) {
    const url = new URL(req.url, new URL(resource).origin);
    if (req.method === 'GET' && url.pathname === metadataPath) {
      return sendProtectedResourceMetadata(res, metadata);
    }
    if (url.pathname !== new URL(resource).pathname) return downstream(req, res);
    // Authentication for MCP execution. Keep catalog discovery behavior governed
    // by the downstream gateway; this adapter deliberately authenticates all /mcp
    // requests if enabled, rather than accidentally leaking tool execution.
    const token = bearerToken(req.headers.authorization);
    if (!token) {
      res.writeHead(401, { 'WWW-Authenticate': challenge, 'Cache-Control': 'no-store' });
      res.end();
      return;
    }
    try {
      req.oauth = await verify(token, { scopes: ['privi:tools:execute'] });
      return downstream(req, res);
    } catch {
      res.writeHead(401, { 'WWW-Authenticate': challenge + ', error="invalid_token"', 'Cache-Control': 'no-store' });
      res.end();
    }
  };
}
