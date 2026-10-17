# Mr. Lee — Privi AI private chat gateway

**STATUS: SOURCE ONLY — NOT DEPLOYED, NOT AUTHORIZED, NOT GOVERNMENT-CERTIFIED.**
**ACTIVATION IS DISABLED** until the actual official Privi website and
financial Privi network have independently verified infrastructure.

## Security goal

High-assurance architecture informed by **NIST SP 800-53 Rev. 5** and **OWASP
ASVS 5.0**, not a claim of NIST compliance, FedRAMP authorization, FIPS
certification, classified-information accreditation or an Authority to Operate.
Formal assessments require the *entire* deployed system, independent
penetration testing and organizational controls, not just source code.

### Controls implemented in this branch

- **Default deny**: disabled unless explicitly configured with verified
  non-demo Privi EVM chain ID, real on-chain block-zero fingerprint, HTTPS
  RPC URL, and official exact HTTPS site origin. Known TEST, BNB and
  synthetic chain IDs are rejected. No financial mainnet exists yet.
- **MFA session authorization**: the Privi **website backend** must inject
  independently audited session verification, returning an active account,
  MFA proof and recent authentication time (at most 12 hours), plus genuine
  per-session CSRF validation. No anonymous or single-factor chat calls.
  Client browser alone never validates session or asserts MFA.
- **Request integrity**: website server signs the exact POST path,
  body digest, user pseudonym, official origin, nonce and millisecond
  timestamp using HMAC-SHA256 with 32+ character server-only secret.
  Private Mr. Lee gateway validates it with constant-time comparison,
  +/- 60 second clock skew, and one-use nonce. Replay, tampered body,
  wrong identity, forwarded browser cookies, expired signatures and
  unauthorized origins are rejected. Shared HMAC secret is never sent
  as a bearer credential in traffic.
- **Isolation and transport**: Mr. Lee binds to localhost, has no public
  endpoint, must be placed behind a separately hardened private
  mTLS or equivalent authenticated network service proxy, and uses a
  trusted fixed HTTPS upstream for OpenAI and Privi chain RPC. The website
  adapter uses exactly configured HTTPS gateway URL (not URL chosen by user).
  TLS/mTLS issuance, certificate verification, rotation and termination
  are still **deployment responsibilities**, not provided by this source.
- **Minimal model rights**: assistant has no private key access, transaction
  signer, market order API, validator control or on-chain mutation tools.
  Trading is an unfunded, user-price paper-trade calculator only.
- **Privacy controls**: no chat database/history, no prompt/response logs,
  no tokens in browser code, message length limits, basic high-confidence
  credential detection to reject messages before they reach model service,
  \`store:false\` provider request, no-store/no-sniff response headers, and
  DOM text-only rendering (no innerHTML). **Basic filtering is not complete
  DLP and \`store:false\` does NOT guarantee zero provider retention.**
- **Availability controls**: short timeouts, 4 KiB request cap,
  pseudonymous per-user rate limiter (8/min), maximum eight concurrently
  handled API requests, bounded nonce cache, request/header timeouts.
  Current in-memory nonce and rate stores support **one gateway replica
  only**. Multi-instance production MUST use a shared atomic replay
  cache and distributed rate limiting; otherwise deployment is prohibited.
- **Testability**: Node 22 offline tests for auth/session, CSRF,
  HMAC tampering/replay/expiry, blocked demo networks, insecure URLs,
  message screening, server-side API call shape and nonexecuting trades.
  CI secret-pattern scan; no auto-deploy and no real API calls in tests.

### Privi website integration (NOT YET DONE)

1. Use a real first-party Privi website login/identity provider with
   **phishing-resistant MFA / WebAuthn**; verify signed sessions server-side,
   check revoke/logout and set \`Secure; HttpOnly; SameSite=Strict\` session
   cookies and strict session lifetime/idle timeout.
2. Supply \`getAuthenticatedSession(request)\` and
   \`verifyCsrf(request, session)\` to
   \`website-adapter.js\`. The site should bind CSRF tokens to the actual
   session and never mark MFA verified based on a request header.
   Session \`userId\` should be a stable **site-scoped pseudonym**, not PII.
   The real site must render the widget with its session-bound CSRF token
   in the \`csrf-token\` attribute (NOT with any OpenAI or gateway secret).
3. Configure only fixed HTTPS site and gateway origins. Run Mr. Lee in a
   private service behind identity-aware mTLS/service-mesh ingress; expose
   \`/api/mr-lee/chat\` ONLY through the trusted website server. Keep
   the gateway on 127.0.0.1 inside its authenticated reverse-proxy boundary.
   No public Railway/IONOS domain should point directly to this service.
4. Store **new, rotated** OpenAI key and independent random gateway HMAC
   secret in separate secret managers with minimal permissions and access
   logs. Restrict provider project spend and privileges; never use browser
   environment variables, query strings, source files or build logs.
5. Apply website-level CSP with nonces, HSTS, strict cookies, WAF,
   DDoS controls, OS/container hardening, egress allowlist and encrypted
   backups. Use a read-only filesystem where feasible and remove
   debug/error-body logging from surrounding proxies.
6. Adopt auditable **security-event metadata only** (no chat contents,
   API keys, request bodies, wallet seeds). Route authorized access
   decisions, privilege changes, unsuccessful attempts, admin changes
   and incidents to a protected retention-controlled SIEM with monitoring.
7. Complete vulnerability scanning, SBOM/source/dependency review,
   independent threat modeling and penetration test. Verify admin MFA,
   credential rotation/revocation, abuse-case testing, backup/DR,
   incident-response plan, change approval and **written deployment
   authorization**. Check any federal compliance requirements separately.
8. Independently register mainnet chain IDs, verify production genesis,
   approved validator operators, security audits, and explicit mainnet
   release signoff. A cloned TEST chain or JSON config cannot qualify.

### API key exposure warning

Any OpenAI API key pasted in a chat must be considered compromised.
Revoke it **immediately** in the OpenAI dashboard and create a replacement
in the private secret manager. This repository contains NO live key.
Never give keys or recovery phrases to Mr. Lee or to a model response.

### API

- Browser: POST \`/api/mr-lee/chat\` on the authenticated first-party website.
- Website private adapter: signed POST to \`/internal/mr-lee/chat\`.
- Paper trading: POST \`/api/mr-lee/paper-trade\` on website, signed/private.
- Internal health: GET \`/internal/health\`, no activation metadata.
- No public AI gateway, no wallet/contract executor, no trading bot.

### Offline tests

```sh
cd apps/mr-lee
npm run check
```

Do NOT set \`MR_LEE_ENABLED=true\` or deploy Mr. Lee to a public site
until independent security signoff, actual account/CSRF implementation,
private ingress, key rotation, distributed state architecture (if
replicated), and approved financial Privi network are all in place.
