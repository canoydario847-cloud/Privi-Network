# Privi Bites — v0.1 proof of concept

Privi Bites are short-lived, audience-bound, explicitly scoped cryptographic capabilities. Applications issue them after their **own** authentication and consent checks. The app presents them in an Authorization header (not automatically to every site like cookies), and the target service verifies the capability.

**Not a browser standard or drop-in replacement for cookies.** Secure, HttpOnly, SameSite cookies remain appropriate for many browser sessions. Bites are an experimental complement for delegated agent permissions and API access.

## Endpoints
- `GET /health` availability
- `POST /v1/issue` mint Bite, requires `Authorization: Bearer $BITES_ADMIN_KEY`
- `POST /v1/verify` verify `{ "bite":"pb1....", "audience":"app-name", "scope":"read" }`
- `POST /v1/revoke` revoke minted Bite, requires admin authorization
- `POST /mcp` MCP JSON-RPC tools/list and bites_verify

Issue example:
```bash
curl -X POST "$BASE/v1/issue" -H "Authorization: Bearer $BITES_ADMIN_KEY" -H "Content-Type: application/json" -d '{"subject":"agent-123","audience":"my-api","scopes":["read"],"ttl_seconds":300}'
```
Production warnings: In-memory revocation is lost on restart and does not propagate to replicas; deploy durable shared revocation storage before sensitive use. Admin key is a demo-only issuer gate, not user authentication, and needs rotation, rate limiting, audit logs, and tenant isolation. Tokens are bearer credentials; protect them from XSS, logs, URLs and untrusted third parties. Use TLS. The built-in signing key must be configured via BITES_SECRET for stable signature verification across restarts. No cross-origin access is enabled by default.

Copyright Privi World Corp.
