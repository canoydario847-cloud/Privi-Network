# Remaining Render state migration — November 14, 2026

The HTTP and endpoint cutover is complete; historical state reconciliation is blocked.

## Confirmed blockers

- Old workspace tea-db83bk8n74is73dklo00 contains a suspended Postgres database named life, ID dpg-dbcis0navr4c73d1b0ng-a, in Virginia. The destination billing staging Postgres is a different database, not a restored LIFE backup.
- The connected read-only query failed because LIFE blocks external database connections. Hosted MCP has no supported fixed egress IP to allowlist. Do not open the database to the internet or broaden access to bypass this limitation. Recover a consistent backup through an authorized operator's existing private/local connection or Render's supported backup/export path after access is restored.
- The original Ledger service is still suspended for billing. Its persistent 3-GB disk remains attached. Its public /log/sth returned HTTP 503, so original ledger history and signing identities could not be compared.
- Destination durable Ledger and temporary recovery Ledger expose different public-key fingerprints and different transparency-log sizes. At observation time the durable log reported 3587 entries and recovery reported 7. These are untrusted public observations, not authenticated migration evidence. Do not concatenate or overwrite these histories or silently reuse receipt IDs. Preserve both stores until receipts and identities are reconciled.
- Custom-domain ownership, DNS and certificates remain unverified. Old onrender.com origins are not transferred by replacing website links.

No database, disk, key or receipt was deleted or overwritten. No network allowlist was weakened. No source private keys or row data were retrieved.

## Offline SQLite comparison

Use separate consistent SQLite backups, made with SQLite's backup API or the application's supported export process. Do not copy an active .db file without its committed WAL content. Keep backups and reports outside the repository and in restricted storage.

```bash
python3 operations/compare_sqlite_snapshots.py /secure/source-backup.db /secure/destination-backup.db > /secure/comparison.json
python3 -m unittest discover -s operations -p 'test_compare_sqlite_snapshots.py'
```

The tool checks database integrity, schema, exact row counts and type-aware row multiset hashes. It refuses active WAL/journal files, identical input paths, concurrent file changes and over-limit tables. It opens files read-only and emits no row values, keys or credentials. The report itself is private operational metadata and must not be committed. Exit 0 means matching snapshot content only; 1 means mismatch; 2 means blocked. It does not restore a database, prove backups are authentic, compare Postgres, validate receipt signatures, reconcile external payment state, or authorize financial mainnet.

After source access is restored, authenticate the backup, reconcile org/user IDs and credits, validate ordered receipt chains and public key identities against independent pins, then plan an explicit maintenance window for restore. Verify before redirecting writes or retiring old resources.
