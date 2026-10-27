# LIFE staging backup recovery gate (operator checklist)

This document is a **test plan, not evidence of a completed restore**. Keep all real-money payment switches off and use synthetic staging data only.

## Repeatable acceptance check

1. Confirm the SQLite database is on a durable volume by recording a synthetic row, restarting and redeploying staging, and verifying that exact row persists.
2. Take an application-consistent SQLite snapshot using the supported backup API, not a raw copy of a live database. Encrypt it before off-host transfer; restrict read/restore permissions and keep encryption keys separate.
3. Record a SHA-256 digest and UTC snapshot time in a restricted operations log. Never commit snapshot bytes, keys, credentials, member records or storage URLs.
4. Restore into a *new* isolated staging instance with `LIFE_STAGING_ONLY=1`, `PRVI_MAINNET_PAYMENTS_ENABLED=0`, and `BNB_PRIV_PAYMENTS_ENABLED=0`. Keep any other real-payment integrations disabled.
5. Run `python -m pytest life-ai-studio/tests/test_backup_verify.py` from repository root (with test dependencies installed) and execute the application's backup verifier against the restored synthetic database.
6. Compare synthetic row counts and ownership relationships to the source. Corrupt a *separate synthetic* snapshot, confirm restore verification fails closed, and check that monitoring detects the failure.
7. Document actual recovery time and recovery point; have an independent reviewer approve RTO/RPO, retention, encryption, access controls and deletion procedures.

**Pass condition:** All seven steps have dated, redacted evidence and independent sign-off. A passing CI suite alone does not meet this gate. Until then, no production customer data, live payments, token deposits, or launch.
