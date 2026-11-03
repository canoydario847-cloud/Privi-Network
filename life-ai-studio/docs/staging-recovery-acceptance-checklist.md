# LIFE staging backup recovery gate (operator checklist)

This document is a **test plan, not evidence of a completed restore**. Keep all real-money payment switches off and use synthetic staging data only.

## Repeatable acceptance check

1. Confirm the SQLite database is on a durable volume by recording a synthetic row, restarting and redeploying staging, and verifying that exact row persists.
2. Take an application-consistent SQLite snapshot using the supported backup API, not a raw copy of a live database. Encrypt it before off-host transfer; restrict read/restore permissions and keep encryption keys separate.
3. Record a SHA-256 digest and UTC snapshot time in a restricted operations log. Never commit snapshot bytes, keys, credentials, member records or storage URLs.
4. Restore into a *new* isolated staging instance with `LIFE_STAGING_ONLY=1`, `PRVI_MAINNET_PAYMENTS_ENABLED=0`, and `BNB_PRIV_PAYMENTS_ENABLED=0`. Keep any other real-payment integrations disabled.
5. From repository root, run `python -m pytest life-ai-studio/tests/test_backup_verify.py` with test dependencies installed. On an isolated staging host, verify the *restored, private* SQLite copy using `python life-ai-studio/tools/backup_verify.py --verify-copy /private-vault/restored.sqlite3 --expected-sha256 <trusted-64-character-digest>` (replace placeholders locally; never commit the digest or data). Confirm the JSON reports `restore_drill: passed` and `encrypted_off_host_copy: NOT_VERIFIED`; the latter requires separate infrastructure evidence.
6. Compare synthetic row counts and ownership relationships to the source. Corrupt a *separate synthetic* snapshot, confirm restore verification fails closed, and check that monitoring detects the failure.
7. Document actual recovery time and recovery point; have an independent reviewer approve RTO/RPO, retention, encryption, access controls and deletion procedures.

## Failure-injection acceptance (synthetic data only)

Use a separate copy of the restored staging snapshot, not the source or the valid recovery artifact. Change one byte in that copy, retain the original trusted SHA-256 digest outside the repository, and run the same `--verify-copy` command against the corrupted copy. **Expected:** nonzero exit status, no `restore_drill: passed` result, and an operator-visible alert. Do not print snapshot contents or private identifiers in logs. Then rerun verification against the untouched restored copy to demonstrate recovery still succeeds. Record both exit statuses, UTC times, and alert evidence in the private operations record. Never weaken the checksum or turn off the verifier to make a drill pass.

**Pass condition:** All seven steps have dated, redacted evidence and independent sign-off. A passing CI suite alone does not meet this gate. Until then, no production customer data, live payments, token deposits, or launch.
