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

## MCP gateway integration (opt-in, not deployed)

The repository's `privi-agent-survival` directory currently contains public catalog metadata, not the hosted gateway's application source. Integration therefore requires a change to the **actual deployed gateway repository** and Render service; placing files here does not protect its endpoint.

`mcp-gateway-adapter.mjs` is a Node HTTP wrapper that returns RFC 9728 metadata at `/.well-known/oauth-protected-resource/mcp`, challenges unauthorized `/mcp` traffic, validates signed access tokens with the `privi-mcp-gateway` audience and `privi:tools:execute` scope, and forwards non-MCP traffic unchanged. This adapter **denies anonymous MCP discovery** when enabled; adjust to preserve public `initialize` / `tools/list` only after inspecting the actual gateway routing and ensuring tool execution is always gated.

Before connecting production:
1. Provision a trusted OAuth provider and verify its authorization-code + PKCE S256, refresh rotation, client registration, consent, and OIDC/AS discovery capabilities; do not use an unverified issuer.
2. Configure `PRIVI_OAUTH_ISSUER`, `PRIVI_OAUTH_JWKS_URI`, audience `privi-mcp-gateway`, and least-privilege scopes as environment settings.
3. Wire the adapter into the real gateway entrypoint, including transport-specific MCP session checks, RFC 9728 metadata paths, and correct 401/403 challenges.
4. Validate Claude/ChatGPT compatible clients, valid/expired/wrong-audience/wrong-scope tokens, rotation, logout/revocation design, rate limits, logs, and legacy API-key compatibility.
5. Keep behind a disabled feature flag until tests and rollback plan are verified.

No automatic API credit checkout is enabled by these changes.
