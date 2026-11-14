# Privi Quantum Cloud — bounded web API

**Reality check:** This release runs qubit circuits on a **classical statevector simulator**, **not** a physical quantum processor. No claims of quantum advantage, quantum speed, paid QPU access, or deployed multi-region consensus are made.

## API endpoints

- `GET /v1/quantum/cloud`: public service capabilities (simulator only, 12 qubits maximum).
- `POST /v1/quantum/cloud/jobs`: submit OpenQASM 2/3 circuit, authenticated.
- `GET /v1/quantum/cloud/jobs/{job_id}`: retrieve private job status and output, authenticated.

**Limits**: 12 simulated qubits, 500 basis gates, 4096 shots/job, 24 KB request, 32 pending/running jobs per service instance, two local worker threads.

Set `QUANTUM_CLOUD_API_KEYS` to one or more strong independently generated bearer keys (comma-separated) using the Render secret/environment controls. Without it, job endpoints return 503. Never put keys in Git, logs or browser-side client code. Rotate keys and place a reverse proxy with rate limiting in front of the endpoint before offering it to untrusted clients.

Set `QUANTUM_CLOUD_DB_PATH=/data/quantum-cloud.sqlite3` on a Render service with a durable attached disk. This is a **single-instance queue and SQLite store**; it is not a distributed quantum cloud yet. Queued/running work at process restart is marked failed. Scaling to several regions/instances requires a shared durable queue (Postgres/Redis), external worker coordination, per-tenant quotas and observability. Do not scale this current SQLite design horizontally.

Example local authenticated request (replace host and key with your actual service and secret):

```bash
curl -X POST "https://YOUR-QUANTUM-HOST/v1/quantum/cloud/jobs" \
  -H "Authorization: Bearer YOUR_PRIVATE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"qasm":"OPENQASM 2.0;\ninclude \"qelib1.inc\";\nqreg q[2];\nh q[0];\ncx q[0],q[1];","shots":1000}'
```

The response includes a `job_id`. Query `/v1/quantum/cloud/jobs/{job_id}` with the same bearer key. Completed jobs return bitstring counts and explicitly label results as a simulator.

## Hardware and payment safety

This cloud API cannot spend on third-party quantum providers. Existing Privi hardware tools are **separate**; configure no provider credentials or budgets for this job service. The cloud endpoint does not implement billing, does not issue paid API credits and must not be advertised as a paid hardware network. Customer access is manual until a verified entitlement gate exists.

## Build and verification

```bash
cd quantum-server
python -m pip install -e ".[dev]"
python -m pytest -q tests/test_cloud.py
```

Render service `privi-quantum` is configured to auto-deploy tracked changes under `quantum-server/**` when merged to main. Wait for a successful deploy and test the actual live endpoint before advertising availability. No paid hardware jobs should be triggered during validation.
