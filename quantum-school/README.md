# Privi Quantum School · MVP (not deployed)
Copyright (c) 2026 Privi World Corp. All rights reserved.

A course-and-model-evidence database for AI agents, plus an administrative
deployment approval center. This is a **software registry, not a quantum chip**.

Interactive landing page: GET / (course descriptions, capabilities and API console link).

## Implemented
- Four required courses: quantum fundamentals, agent safety, dataset
  governance, deployment controls, each with a scored knowledge check.
- Register agents and transcripts; agents must complete all courses to
  register a training job.
- Store dataset SHA-256, reference, and rights attestation, but no raw data.
- Register intended cloud GPUs, HPC and QPUs (all explicitly unconnected).
- Register training/evaluation/experiment requests with a budget ceiling.
  Requests DO NOT launch compute or charge money.
- Record operator-reported run results, model artifact references, SHA-256
  digests, evaluation scores, and protected deployment requests.
- Require passing evaluation and explicit owner approval before release;
  even approved is NOT deployed. Production approvals are disabled by default.
- Operational event log. **Not** cryptographically signed or independently
  verified; integrate Privi Ledger and Verify later.

## Run locally
    cd quantum-school
    pip install -r requirements.txt httpx pytest
    export SCHOOL_ADMIN_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(40))')"
    export SCHOOL_DATABASE_URL="sqlite:///./school.db"
    uvicorn school:app --port 8000

Public: GET /health and /courses. Protected API at /docs.
Authenticated calls: Authorization: Bearer [SCHOOL_ADMIN_TOKEN].
Tests: pytest -q tests

## Safe launch requirements
1. Choose and approve a Render workspace and provision an isolated
   Postgres instance with retention/backup plans. Do NOT reuse the LIFE
   database (previously reported expiring November 20, 2026).
2. Set SCHOOL_DATABASE_URL to a private postgresql+psycopg:// DSN and
   SCHOOL_ADMIN_TOKEN to a 24+-character random secret.
3. Use HTTPS, access controls, migrations and monitoring. This single-admin
   MVP is **not suitable for public multi-tenant training workloads**.
4. Add actual isolated worker backends with scoped GPU/QPU credentials,
   consented datasets, cost enforcement and verified provider receipts.
5. Integrate the existing Privi Quantum MCP, Guard, Ledger, Verify, Anchor
   for enrollment/identity and verifiable compute evidence, after testing.
6. Enable production approval only with explicit review via
   SCHOOL_ALLOW_PRODUCTION_APPROVAL=1. This never triggers actual deployment.

This PR does not deploy, spend funds, provision cloud hardware, retrain
models or change live service configuration. Quantum speedup is not promised.
