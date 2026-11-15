# Privi Master Ledger: one authoritative audit history, minimal local state

**Owner:** Privi World Corp
**Status:** master collection exists; application data migration and production verification are incremental.
**Never delete a service's production database or Privi financial chain state solely to save disk.**

## Master-of-record architecture

- **Canonical audit ledger:** Privi Ledger / its Quantum Ledger and Fortress proof layers, at `https://privi-ledger-aqe5.onrender.com` (the public URL is not independently proof of availability).
- **Service event gateway:** `POST /quantum-ledger/report` with shared reporter credentials. Verify, Anchor, Quantum, Call, and Wallet each report tool calls and state-changing routes. Events include service, event ID, outcome, timestamp, and keyed SHA-256 request fingerprint. **No raw customer prompts, code, transaction secrets or vehicle identifiers.**
- **One service stream per source** in the master ledger, not a separate financial blockchain. Privi Ledger's signed blocks are proof and search layers over its own records, not additional independent customer databases.
- **Source of truth for business operations stays where needed:** Wallet balances and any custodial secrets, customer identities, access keys, payment entitlements, ongoing jobs and pending authorized transactions must stay in secure service databases until deliberately migrated to an equivalent operational datastore. The audit ledger is NOT a substitute for a transactional database.
- Deep Think (within Privi Call) reports its request activity to the master via Call's reporter. Its per-task revision and anti-replay state remains local operational state.
- Offline Privi Car/Chem prototypes and separately deployed apps are **not automatically integrated** just because they share the Privi name. Enroll each actual service, verify a test receipt and mark it Reporting before claiming complete coverage.

## Safe storage reduction already implemented

Each service reporter keeps a short-lived local SQLite outbox for resilience during Ledger outages. `flush()` now removes an event **only after** the master returns a matching ID and valid 64-character entry-hash receipt. Mixed accepted/rejected replies remove only acknowledged events; an HTTP 200 or count by itself removes nothing. Retries are idempotent on the master by (service, event ID). If outbox capacity is reached, do **not** silently delete oldest unconfirmed events: preserve them, raise an overflow status, and repair the central service promptly.

When all outbox rows are acknowledged, `compact_if_idle()` can reclaim SQLite freelist pages with `VACUUM` on file-backed outboxes. Automatic compaction is conservative (8 MiB and at least half pages free; at most once per hour). It does not delete account, payment, key or historical ledger records.

## Safe deletion / migration gates

Before deleting **any** old hash-log/history store:
1. Inventory exact database paths, table rows, byte sizes, ownership, live dependencies and retention requirements. Include testnet and financial mainnet **separately**.
2. Take an independently restorable, encrypted, access-controlled snapshot. Verify the backup and a restore drill.
3. Export historical records in an agreed format, recompute the source chain and its end hash, and import/integrate into the master ledger in a test environment.
4. Verify count, unique IDs, hash commitments, query behavior, service API compatibility and audit retention; record receipt IDs and proof links. Account for records the central audit reporter never captured before this migration.
5. Run dual-write for a defined interval; ensure a crash/restart does not lose, reorder or double-charge customer state.
6. Only then consider removal of **verified redundant copies**, with a rollback plan, explicit operational approval and recorded deletion manifest. Never delete the only copy of an unreplicated event.

**Do not blindly delete:** Ledger's own database, persistent service state, wallet keys/ledgers, signed records, on-chain history, validator storage, user records, payment records or unacknowledged outboxes. Do not reset or VACUUM an active ledger primary as a substitute for backup/retention policy.

## Live verification checklist

- Master: `GET /quantum-ledger/services` lists every expected service as reporting.
- Submit a non-sensitive test record via each reporter; verify the master entry hash receipt and a valid inclusion proof once a block seals.
- Run `ledger-server/tests/test_network.py` and `mcp-server/tests/test_master_ledger_cleanup.py`.
- Verify the service volume actually shrinks after the outbox is empty and SQLite compaction runs.
- Verify Stripe/USDC billing and entitlement records remain intact and there is no change to payment routing.

## Storage accounting

Track per service: outbox_pending, acknowledged, overflow, last_error, local SQLite size, logical database pages, freelist pages, main Ledger entry count, last accepted receipt and snapshot age. Target zero **unacknowledged** outbox rows during healthy operation, not zero local databases. Space reclaimed depends on historical volume and page fragmentation and has not been measured on production volumes.

## What's not done by this change

- Production database deletion or migration.
- Disabling all local tamper-evident chains (many clients still depend on their verification APIs).
- Connecting every Privi prototype or unsupported service.
- Proving every historical event was received by the master before this improvement.
