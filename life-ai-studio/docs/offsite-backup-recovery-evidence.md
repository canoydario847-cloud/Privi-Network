# LIFE off-host backup and recovery evidence (staging-only)

**Status: NOT VERIFIED — production release blocked.** This is an operator evidence template, not proof that backups exist. Do not enter customer data, database contents, credentials, private keys, or unredacted storage URLs here.

## Required independent recovery drill

1. Identify the staging database volume and verify that it is persistent across restart and redeploy. Record only non-secret infrastructure identifiers in the private operations record.
2. Configure encrypted, versioned, access-restricted off-host backups with a documented retention policy. Keep encryption keys separate from backup storage and restrict restore privileges.
3. Take a snapshot using the application's supported consistent-backup procedure; do **not** copy a live SQLite file without snapshot coordination. Record UTC timestamp, sanitized snapshot ID, size and SHA-256 in a restricted evidence record.
4. Restore into a fresh isolated staging instance with payment switches **off** (`LIFE_STAGING_ONLY=1`, `PRVI_MAINNET_PAYMENTS_ENABLED=0`, `BNB_PRIV_PAYMENTS_ENABLED=0`). Never overwrite the source instance.
5. Run the existing LIFE backup-integrity verifier and regression suite against the restored data. Confirm member/project ownership and payment-audit relationships are preserved; fail the drill on any missing or orphaned record.
6. Measure restore duration (RTO) and oldest recoverable data (RPO), compare to separately approved targets, and obtain sign-off from an independent reviewer.
7. Repeat with a deliberately corrupted **synthetic** snapshot to verify rejection and alerting. Do not put real user data into this exercise.

## Evidence to collect (private, redacted)

- [ ] Durable source volume verified across restart/redeploy
- [ ] Encryption at rest and in transit verified; key access independently reviewed
- [ ] Off-host retention, immutability/versioning and deletion policy approved
- [ ] Consistent backup snapshot SHA-256 and UTC time recorded
- [ ] Clean-room restore completed without modifying source
- [ ] Restore integrity and application regression tests passed
- [ ] Corrupt synthetic snapshot rejected; monitoring alerted
- [ ] RPO/RTO targets approved and measured
- [ ] Independent reviewer and date recorded

**Gate:** Until every item is evidenced and security/authorization/financial reviews also pass, LIFE stays disposable staging; no real deposits, production payment gates or customer onboarding with personal data.
