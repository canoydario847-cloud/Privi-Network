# Privi Render reliability: reviewed, not applied

This runbook is deliberately safe to review before any production change. Do not redeploy, remove disks, rotate secrets, change pricing, or migrate databases merely by merging this document.

## What caused the October 25 502 errors

Privi Ledger, Verify, and Call each have one Starter instance and a 1 GB persistent disk mounted at /data. Render does not support zero-downtime deploys for disk-attached services; it stops the old instance before starting the replacement. The HTTP 502 responses overlapping their October 25 deployments are consistent with this documented behavior.

The latest Ledger, Verify, and Call deploys were successful, but they were explicitly API-triggered at roughly 18:06 UTC after earlier successful code deployments. Stop triggering unnecessary API deploys. Keeping the existing /health checks is good, but cannot solve disk-backed deployment downtime.

Sources: https://render.com/docs/disks and https://render.com/docs/deploys

## Safe fixes that need existing-service settings edits

Discovery and Jose Backend already implement GET /health in the source repository, but Render currently has no configured HTTP health-check path for either service.

| Existing service | Render Dashboard | Set HTTP health path | Include-path filter recommendation |
|---|---|---|---|
| privi-discovery | https://dashboard.render.com/web/srv-dbbsp2d9fdbs73a4phvg | /health | discovery/** |
| jose-backend | https://dashboard.render.com/web/srv-db8mrgu7bikc73empuu0 | /health | jose-backend/** |
| privi-life-ai-staging | https://dashboard.render.com/web/srv-dbd6je3ncjis73bab2g0 | Not until a working health route is confirmed | life-ai-studio/** plus its shared dependencies |

For Discovery and Jose, use Render Dashboard > Service > Settings > Health Check Path > Edit > /health. Use Settings > Build & Deploy > Build Filters to limit incidental main-branch deploys. Review *shared code, configs, and manifest dependencies* before applying an include-path filter so genuine updates still deploy. The current render.yaml Blueprint excludes Discovery and Jose, so do not add duplicate services to render.yaml.

Limit static-site auto-deploy triggers to their actual publish directories (e.g. sites/guard/**, sites/hub/**, sites/home/**, and jose-site/**), plus required shared dependencies. Confirm each publishPath before changing its filters.

Render documentation: https://render.com/docs/health-checks and https://render.com/docs/monorepo-support

## Read-only smoke check prepared

Use Python 3, from the repository root:

    python3 ops/render_health_audit.py
    python3 ops/render_health_audit.py --include-free --all-sites

This tool performs GET only. By default it checks the five paid APIs and does not wake free-tier services. Optional flags check Discovery, Jose, Life staging, and the twelve static sites. It uses no secrets, and it must not be mistaken for a complete assessment of restarts, resource metrics, deploy status, or PostgreSQL availability.

## Plan to eliminate downtime safely (not executed)

1. Inventory SQLite writers and actual database paths for Ledger (/data/ledger.db), Verify (/data/privi.db), Call (/data/call.db), and optionally Anchor (/data/anchor.db) and Quantum (/data/quantum.db). Verify each path against the production environment first.
2. Make consistent online backups via SQLite's backup API while writers remain active. Store encrypted copies outside the mounted disk, not only on /data. Retain disk snapshots separately; their short retention does not replace independent logical backups.
3. Restore each database into an isolated test environment. Run integrity checks, row-count comparisons, and API smoke tests without touching production.
4. Implement Postgres-backed persistence in each service and test the new code in staging. Merely changing an environment variable to a Postgres URL does not make an SQLite-based application support Postgres.
5. Obtain explicit approval for any database spending and plan a controlled data cutover with freeze or verified dual-write, rollback, and a maintenance window. Only remove a persistent disk after completed migration and tested restore.
6. Re-test zero-downtime deploys and live health checks in staging, then production.

Removing a disk early can permanently destroy user data. No disk or production DB has been changed by this pull request.

## Life PostgreSQL expiry (separate from SQLite)

The Render Life database (life_0gs7, Free tier) last reported status=available and expiration=2026-11-20T21:26:26.095069Z. Establish an off-platform backup and restore drill well before that deadline; map all apps using the database and obtain approval before changing its pricing plan or provisioning a paid replacement.

## Verify any subsequent authorized changes

Check every affected service's Events for suspended, failed, and restart events; verify latest live deployment; check /health while warm; inspect HTTP 5xx after deployments; and check instance count/memory/CPU. If the new HTTP health probe causes restarts because it is not implemented correctly, revert the probe configuration while investigating. Free-plan idle sleeping remains an unresolved availability risk even with an HTTP health check.
