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

## OIDC identity proof verification (November 19, 2026)

`oidc_identity.py` now validates a separately signed OpenID Connect **ID token** (RS256), using the configured trusted issuer's JWKS. In addition to signature, issuer, exact client audience and authorized-party checks, it binds the identity to the original unpredictable OAuth nonce and the token response's access token via OIDC `at_hash`; verifies expiry, issuance and `nbf`; and limits token lifetime to one hour. Its return value contains only an identity assertion and deliberately grants neither API access nor Privi Pro.

The `test_oidc_identity.py` suite uses locally generated RSA fixtures and checks forged signatures, replay/mismatched nonces, wrong audience/issuer/authorized party, access-token mismatch, and missing cryptographic dependencies. This optional suite is skipped in the stdlib-only Render build and runs in `.github/workflows/privi-universe-auth.yml` with `cryptography` installed. CI success must be independently verified.

**Still not a customer login:** this verifier is a standalone foundation and is not yet composed into an enabled browser login/session flow. The account routes remain disabled without a genuine provider. Production deployment still requires validated provider metadata and registered client, verified callback code exchange and nonce from its one-time state, secure HttpOnly session cookies, revocation/logout controls, identity lifecycle policy, key rotation, test coverage against real issuer responses, and separately authenticated billing entitlements.

## Server-side sessions, CSRF and revocation foundation (November 19, 2026)

`browser_sessions.py` provides an isolated, standard-library server-side session-store prototype for **future authenticated identity flows**, with 256-bit opaque session handles, SHA-256-only handle storage, short (30-minute) expiry, capped capacity, `__Host-` host-only Secure/HttpOnly/SameSite=Lax cookies, same-origin checks plus per-session anti-CSRF tokens, explicit logout, and trusted server-side subject-wide revocation. It never attaches a Privi Pro privilege to a login session.

The test suite `test_browser_sessions.py` covers cookie restrictions, duplicate cookies, expiration, same-origin CSRF rejection, logout replay and concurrent logout, provider-triggered revocation, memory limits, and lack of implicit Pro access. Portal tests verify no login, callback, cookie creation, or logout endpoint was enabled in the public demo.

**Not production-ready or enabled:** This in-memory store is not safe as a distributed session backend; a multi-instance deployment must use a shared, durable, access-controlled storage and revocation service with atomic operations, rotation, secure session regeneration, protections against fixation and stolen sessions, backend rate limits, session invalidation on credential changes, and carefully reviewed OIDC identity-to-session binding. The `issue` method must be called only internally after cryptographically verified OIDC and freshness checks. No public route calls it. Enabling authenticated customer login also requires a verified identity provider and end-to-end integration testing. Payment and PRVI systems are unchanged.

## Integrated OAuth + OIDC to session pipeline (November 19, 2026)

`login_pipeline.py` is a **server-only integration prototype** linking the prior PKCE one-time transaction, trusted HTTPS authorization-code exchange, independently validated OAuth access token, signed OIDC ID token, identity/nonce/issuer binding, and the account-only session store. It requires the ID-token subject to match the verified access-token subject before issuing any session and never conveys Privi Pro privileges.

`test_login_pipeline.py` uses an offline, synthetic identity provider and verifies that mismatched subjects/issuers, unpinned signing keys, forged tokens, malformed callback codes, missing ID tokens, replayed state, and unavailable session stores do not grant access. It makes no external provider requests.

**Still disabled on Render:** No public `/oauth/start`, `/oauth/callback`, or session creation endpoints invoke the pipeline. The in-memory session store, missing actual registered OIDC provider, provider-specific client authentication, missing production shared state and session storage, logout/revocation integration, cross-site CSRF and fixation review, and separately verified billing entitlements remain launch blockers. Authentication is not activated just because tests pass.

## Cryptographically signed end-to-end login checks — November 19, 2026

`test_signed_login_pipeline.py` now signs **real, throwaway RS256 test tokens** for both resource-server OAuth access and OIDC identity, and sends them through the actual `verify_account_token`, `verify_id_token`, `complete_verified_login`, and `SessionStore` implementations in one test sequence. Success yields only an account session, **never Privi Pro privileges**. Negative tests prove rejection of forged signatures, mismatched subjects, missing trusted keys, expired tokens, modified nonces, incorrect access-token binding, and reused authorization state without a resulting session.

The dedicated `.github/workflows/privi-universe-auth.yml` installs `cryptography` and runs these RSA-based tests. On Render's dependency-free free-tier build the cryptographic suites deliberately skip; therefore **the standard Render build alone cannot establish passing signature tests**. The GitHub Actions conclusion must be verified separately. This is still only synthetic provider verification: a production browser login remains disabled pending an independently registered trusted IdP, durable session storage, secure callback wiring, provider-specific tests, and verified payment entitlements.

## SQLite transactional session-store prototype (November 19, 2026)

`sqlite_sessions.py` adds a **file-backed local SQLite** prototype implementing the same account-only session interface as `browser_sessions.py`: issue, validate, require CSRF, revoke/logout, and revoke all sessions for one verified subject/issuer. It stores only SHA-256 hashes of opaque session and anti-CSRF tokens, sets the same Secure/HttpOnly/SameSite cookie, and uses transaction-guarded database mutations so concurrent logout attempts cannot both succeed. Expired sessions are invalidated and cleaned up. The test suite `test_sqlite_sessions.py` checks persistence across reopened database connections, revocation across independent store instances, concurrency, anti-CSRF origin checks, expiry, and no implicit Privi Pro access. No actual customer or personal account data was migrated or created.

**This does not activate customer login or solve production distributed storage.** SQLite on Render free ephemeral disks is NOT a durable session backend; tests use throwaway local files only. Before release, use an existing securely configured *persistent shared* database service with transactions, backups, at-rest encryption, least-privileged application credentials, verified logout and revocation across instances, rate limits and operational disaster recovery. A real identity provider, client registration and production callback/session adapter remain missing; no billing entitlement or payment integration was added.

## Dedicated database preflight (November 20, 2026)

Render inventory found an existing `privi-billing-staging` free database (listed expiration **December 13, 2026**) and a `privi-billing-production` database on the **basic_256mb** plan. **Neither billing database was accessed or changed.** The production billing database is a separate paid resource and must not be reused for customer session storage without an explicit architecture and privacy review.

`session_storage_config.py` adds a *configuration-only* preflight that refuses known billing database names, rejects names mentioning payment/Stripe/ledger, requires HTTPS-equivalent PostgreSQL TLS `sslmode=verify-full`, and demands an isolated `privi_sessions` schema, documented administrator review, and backups verification. Public `GET /api/access/config` shows only redacted readiness flags; it never exposes the connection URI or secrets. Passing this preflight **does not** establish that any database exists, is connected, durable, or operational. `test_session_storage_config.py` covers all failure cases without making a database connection.

Future environment keys: `PRIVI_UNIVERSE_SESSION_BACKEND=postgres`, `PRIVI_UNIVERSE_SESSION_DATABASE_URL` (a **dedicated** secret), `PRIVI_UNIVERSE_SESSION_SCHEMA=privi_sessions`, `PRIVI_UNIVERSE_SESSION_ADMIN_REVIEWED=true`, and `PRIVI_UNIVERSE_SESSION_BACKUPS_VERIFIED=true`. The last two must never be set without verified real-world evidence. This check neither installs a Postgres driver nor turns on login; no customer sessions were created and no charges were incurred.

## Dedicated PostgreSQL session adapter (November 20, 2026)

`postgres_sessions.py` provides an **optional, unconnected** PostgreSQL 16-compatible session adapter with the interface used by the earlier session proof of concept: `issue`, `validate`, `require_csrf`, `revoke`, and `revoke_subject`. It requires a dedicated Postgres database to pass `session_storage_config.py` preflight. It does not initialize itself from the live portal, open connections on import, install a database driver, or create any user account. `psycopg>=3` would need to be installed for an actual tested integration.

The operator-reviewed migration is `postgres_session_schema.sql`. It creates only the `privi_sessions.sessions` table in a separate schema (hashed opaque handles, issuer/subject identity, expiration and hashed CSRF tokens), with indices. An administrator must independently provision and verify a **dedicated** persistent database, TLS certificates, a least-privileged SQL role and backups before applying this migration; never run it against Privi billing or ledger databases.

The adapter uses fixed parameterized SQL, transaction-scoped advisory locking to serialize capacity checks, row locks for atomic logout, server-side subject revocation, CSRF and same-origin verification, and explicitly denies implicit Pro privileges. The 200-session cap is a prototype safety limit, not production capacity planning. `test_postgres_sessions.py` uses a fake connector with no database/network traffic to test the SQL contract and negative cases. **No actual PostgreSQL integration has been tested**; a dedicated ephemeral database CI test and durability/recovery exercise will be required before customer login. Production pooling, index/lock contention, revocation latency, backups and scale need further review.

**Current deployment boundary:** The public `server.py` does not import or invoke this adapter, and browser login stays disabled. Existing Render billing databases and payment services were not modified; no new paid infrastructure was created.
