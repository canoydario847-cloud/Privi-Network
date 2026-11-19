# Privi Universe — Space-age navigation portal

**Prelaunch navigation only.** This is an independent, responsive web portal presenting Privi World Corp's AI infrastructure. No user accounts, pricing checkout, agent execution, wallets, models, or PRVI mainnet operations.

## Links and availability claims

- **Privi ONE:** known Render synthetic demonstration at https://privi-one-demo.onrender.com/
- **OutcomeGrid:** known Render synthetic demonstration at https://privi-outcomegrid-demo.onrender.com/
- **CallProof:** GitHub enterprise pilot scope document. **Not labeled as a verified live service.**
- **Privi Guard:** original GitHub implementation source. **Not labeled as a verified live service.**
- **Privi Ledger:** original GitHub implementation directory. **Not labeled as a verified live scanner/mainnet.**

There are no invented marketing links or fictitious online services. The portal's design is self-contained, dependency-free HTML/CSS in a standard-library Python HTTP server. It deliberately sends no tracking data to third parties.

## Local run and tests

From the repository root:

```bash
python -m unittest discover -s privi-universe -p 'test_*.py' -v
PORT=10000 python privi-universe/server.py
```

Open http://localhost:10000/ or query `/health`. Everything is read-only, with fail-closed unknown routes, CSP, and explicit product availability labels. Deploy on a separate **free** Render Python service with autoDeploy disabled, the same test build command, and `python privi-universe/server.py` as start command.

Visual style: CSS starfield, glowing orbital illustration, dark navy/cyan/violet mission control, responsive cards, reduced-motion support. Original Privi World Corp materials © 2026; "Made by Dario Canoy."

Next steps, after confirming published production endpoints: authenticate and test services independently, then promote reference links to live service cards only when verified. Do not connect real financial flows without separate authorization and security checks.

## Mission Status and Access Roadmap (November 19, 2026)

The portal now has a read-only **Mission Status** section that calls `GET /api/status`, backed by `status_monitor.py`. It observes only the fixed HTTPS `/health` URLs of the Privi ONE and OutcomeGrid Render sandbox demos. URL allowlisting, redirect blocking, bounded responses, strict expected-mode checks, timeouts, and a 90-second cache protect the public status interface. The response does **not** prove service uptime over time, security compliance, billing or payment availability, PRVI mainnet condition, or production readiness. It labels the other three modules source references (not monitored).

**Account Access** shows a transparent roadmap: Guests can open public demos, but real unified customer logins and Privi Pro entitlements are **not configured**. This is not an SSO implementation, and the website never collects passwords or grants paid privileges. Protected access must be enforced server-side after connecting a trusted OIDC provider and payment entitlement service, including verified revocation and tenant scope.

Tests mock health endpoints rather than relying on the internet and check that statuses never imply live production services. No paid infrastructure, production database connections, customer data storage, new accounts, Stripe actions, or PRVI operations were added.

## Server-side OAuth resource gate and separate paid entitlement (November 19, 2026)

The portal now includes a **fail-closed account authorization foundation** in `account_access.py`. The public `GET /api/access/config` exposes only configuration readiness booleans, never environment values or secrets. `GET /api/account/me` requires a valid signed, issuer- and audience-bound OAuth access token with `privi:account` scope. `GET /api/pro/verify` additionally requires a separately signed, same-subject *paid, unrevoked* entitlement JWT from the configured billing issuer. A customer OAuth token that claims `pro` on its own will never grant access.

**Current status: not enabled.** No identity provider, JWKS addresses, callback URLs, approved browser login flow, or trusted billing proof issuer has been configured for Privi Universe; missing settings return a closed error. This is a *read-only resource-server foundation*, **not** browser sign-in, account registration, or Stripe entitlement integration. Do not imply any customer has activated Privi Pro on this portal. Protected endpoints do not themselves grant access to other Privi services. Each protected downstream service must independently validate tokens and entitlements.

The optional Python `cryptography` package is necessary to verify RS256 access tokens; if absent verification fails closed. The existing Render build installs standard-library dependencies only and therefore does **not** enable real account access. A separate GitHub Actions workflow `.github/workflows/privi-universe-auth.yml` installs `cryptography>=43,<47` and executes generated-key signature, wrong issuer/audience, expiry, scope, forged token, billing subject, unpaid, and revoked entitlement tests. Confirm that CI passes before configuring a trusted IdP.

Required environment variables, when a verified provider is selected:

```text
PRIVI_UNIVERSE_OAUTH_ISSUER
PRIVI_UNIVERSE_OAUTH_AUDIENCE
PRIVI_UNIVERSE_OAUTH_JWKS
PRIVI_UNIVERSE_BILLING_ISSUER
PRIVI_UNIVERSE_BILLING_AUDIENCE
PRIVI_UNIVERSE_BILLING_JWKS
```

Do not configure billing issuer using unverified, user-controlled payment claims. A future production design must use short-lived, independently signed billing attestations, real subscription/one-time purchase reconciliation, revocation/replay controls, caching/rate limits, protected signing keys, and tests against authentic provider responses. No billing database or wallet was touched by this prototype.

## OAuth PKCE transaction protection and account readiness (November 19, 2026)

The portal's Account Access section now displays server-reported identity-provider and billing-verifier readiness by reading `GET /api/access/config`; it never displays a sign-in option that cannot work. Both account registration and browser login remain **disabled**.

`login_protocol.py` adds an isolated OAuth 2.1 authorization-code PKCE S256 transaction helper for the later verified login rollout. It generates cryptographically random one-time state, PKCE verifier/challenge, and nonce, binds the transaction to a specific HTTPS issuer and registered HTTPS redirect URI, refuses replay, expires state after five minutes, and enforces a cap of 128 pending requests. Tests cover expiration, state mismatch/replay, concurrent consumption, and resource limits.

**Security/rollout boundary:** This library is not wired to public login routes. It does not contact any identity provider, exchange OAuth codes, create browser sessions, set cookies, or authenticate customers. Its state storage is in-memory and unsuitable for distributed production without durable shared state and production rate limits. A real login must configure a verified IdP, registered exact redirect URI, issuer-specific endpoints, HTTPS server-side code exchange, state and nonce validation, secure HttpOnly/SameSite session cookies, CSRF controls and logout/revocation. A browser display is never proof of paid Privi Pro entitlement. All production entitlements remain off.

## OIDC provider metadata preflight and honest readiness (November 19, 2026)

The optional `oidc_preflight.py` module validates administrator-pinned issuer, client ID, redirect URL, and JWKS URL against trusted OIDC discovery metadata. It rejects changed/unapproved authorization and token endpoints, non-HTTPS or credential-containing URLs, missing `authorization_code` grant support, missing PKCE S256, and missing RS256 signed-ID-token support. It prepares **only the public authorization parameters** for a future registered login client, never the PKCE private verifier or a client secret. Run tests using `python -m unittest discover -s privi-universe -p 'test_*.py' -v`.

**No provider has yet been configured or independently verified.** This module deliberately does not fetch arbitrary URLs, initiate user redirects, handle callbacks, exchange tokens, issue sessions, or enable customer login. The server's public configuration report now calls settings present `settings_present_unverified` rather than falsely reporting a configured identity or billing system as verified. Full OIDC discovery and client registration must be performed by an authorized administrator; only then can production login be carefully enabled with callback, nonce, PKCE, session and logout verification. Privi Pro still requires a separate trusted billing verification integration.

## Authorization-code exchange (prelaunch library, November 19, 2026)

`oauth_flow.py` now prepares a **configured HTTPS OAuth authorization-code + PKCE S256** authorization URL, consumes single-use state tied to exact issuer and redirect URI, exchanges a callback code with the provider token endpoint using `application/x-www-form-urlencoded`, and **requires a separately verified signed OAuth access token** before returning a minimal subject-only internal result.

The collector rejects non-HTTPS or mismatched issuer-host endpoints, malformed/long codes, invalid bearer token replies, untrusted redirects, and replayed states. Test fixtures use mocked providers; no real credentials, customer tokens, or payments are sent.

**Not a working login:** `/oauth/start`, `/oauth/callback` and any other browser-login endpoints intentionally remain unavailable. The library does not issue sessions, set cookies, run refresh/logout, or validate a provider ID token nonce. Existing `login_protocol.py` creates a nonce but this exchange validates **access tokens only**, not ID-token authentication. An actual browser login must add verified provider discovery, a registered client and redirect, secure server-side sessions/cookies/CSRF, a proper OIDC ID-token and nonce check if using OpenID Connect, durable state, rate limits, revocation, and integration tests. Do not expose this flow until these are complete. Billing and Privi Pro access remain disabled until an independently verified entitlement service is connected.
