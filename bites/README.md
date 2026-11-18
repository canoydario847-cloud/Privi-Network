# Privi Bites

Shared consent/profile and salted hash receipt foundation. The former hosted preview is being moved to Privi-controlled branding; no replacement public URL is verified yet.

The hosted app uses a durable D1 database, platform sign-in, identity-scoped reads/writes, same-origin mutation checks, opt-in profile storage, export and deletion. Profiles and private salts remain off-ledger. The receipt table durably records external delivery status. Profile and receipt inserts are atomic.

`commitments.mjs` validates allowlisted service preferences and generates salted SHA-256 commitments. `ledger.mjs` sends only event ID, digest, timestamp and schema to the existing Ledger MCP tool. No name, email, user identity or private salt is sent. A successful HTTP response alone never counts as delivery: the adapter requires recorded=true and an entry_hash. Ambiguous failures are delivery_unknown, not confirmed; do not blindly retry without reconciling event_id to avoid duplicate append records.

Configure BITES_LEDGER_URL, BITES_LEDGER_API_KEY and BITES_LEDGER_DURABLE=true in hosted runtime secrets only after verifying a durable Ledger deployment. The recovery Ledger is temporary storage and is not configured as a production audit sink. Until then receipts remain pending_configuration. No native blockchain anchoring is claimed.

The public Bites navigation entry is temporarily removed until a verified Privi-branded address is available. This is NOT a claim that every deployed backend is integrated: cross-service profile access still requires the shared OAuth identity-provider rollout, explicit scopes/consent, per-service authorization, deployment and verification. Site identity is site-scoped and must not be equated with an external issuer/subject or user email. Existing logins remain intact.

Bites does not replace browser security cookies, OAuth or authentication. No third-party cookies, fingerprinting or advertising trackers are introduced. Service preferences do not grant service access or trigger data sharing.
