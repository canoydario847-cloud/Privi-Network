# Privi shared OAuth 2.1 resource-server foundation

This module provides a fail-closed JWT access-token verifier and Node HTTP middleware for services using **one external, standards-compliant identity provider**. It is **not** an OAuth authorization server and does not create accounts, authorize users, issue tokens, or configure production services.

## Required deployment configuration
- Select and provision one OIDC/OAuth provider supporting authorization-code + PKCE S256, HTTPS issuer, signed JWT access tokens, refresh-token rotation, and revocation.
- Configure issuer URL, audience per service, and HTTPS JWKS URL as environment variables; never commit secrets.
- Register each Privi service as an API/resource with its own audience and least-privilege scopes.
- MCP protected resources must expose RFC 9728 protected-resource metadata and use RFC 8414 authorization-server metadata; return a WWW-Authenticate resource_metadata URL on 401. The identity provider must support OAuth 2.1-compatible authorization-code + PKCE flows.
- Do not accept ID tokens as API access tokens; configure the provider to issue signed audience-bound JWT access tokens.
- Do not expose administrative endpoints without auth. Preserve public health/catalog discovery explicitly.
- Existing API-key consumers must be migrated deliberately; do not remove keys until verified.
- Keep billing/credits disabled until independent payment tests pass.

## Node usage
```js
import { createTokenVerifier, requireOAuth } from './shared-auth/oauth21.mjs';
const verifier = createTokenVerifier({
  issuer: process.env.PRIVI_OAUTH_ISSUER,
  audience: process.env.PRIVI_OAUTH_AUDIENCE,
  jwksUri: process.env.PRIVI_OAUTH_JWKS_URI
});
// Express: app.use('/private', requireOAuth(verifier, ['privi:read']));
// Plain HTTP: requireOAuth(verifier, ['privi:read'])(req, res, handler);
```

## Rollout
1. Inventory Privi services, existing login methods, API audiences, and callback URLs.
2. Configure shared IdP, redirect allowlists, PKCE and user-consent policies.
3. Integrate and test each resource server and MCP metadata separately.
4. Verify positive and negative integration tests, key rotation, replay/revocation policy, logging redaction and deployment health.
5. Roll out behind feature flags; do not claim full-service OAuth support before deployment verification.

Run `node --test shared-auth/oauth21.test.mjs` on Node 20+.
