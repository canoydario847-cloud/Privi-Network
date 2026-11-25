# Hey Jose Quantum Optimization + Quantum Cloud bridge

## Live, free classical optimization
The Hey Jose server contains a free **exact classical** optimizer aligned with the
Privi Quantum QAOA source convention \`x^T Q x + offset\`.
It enumerates up to 2^16 = 65,536 binary configurations, so it can certify the
mathematical minimum for small QUBO problems. **This is not QAOA, a quantum
advantage claim, or real QPU execution.**

In Jose's chat, use either:

\`\`\`text
/quantum optimize {"Q":[[1,-2],[-2,1]],"names":["a","b"]}
/quantum balance {"jobs":[{"name":"A","minutes":42},{"name":"B","minutes":17},{"name":"C","minutes":33}]}
/quantum cloud
\`\`\`

The "QUBO optimizer" and "Balance work" sidebar shortcuts prefill editable
examples. Results can be downloaded as JSON.

HTTP endpoints:
- \`GET /api/quantum/optimization-info\` — public algorithm and limits.
- \`POST /api/quantum/optimize\` — same-origin, rate-limited exact classical optimization.
  Supply either \`{"Q":[...],"names":[...],"offset":0}\` or \`{"jobs":[{"name":"A","minutes":15},{"name":"B","minutes":19}]}\`.

## Staged Privi Quantum Cloud job bridge — disabled by default
This is an optional **operator-only simulator-to-simulator** bridge, not a paid
hardware gateway. It reaches only:
\`https://privi-quantum-vvmj.onrender.com/v1/quantum/cloud/jobs\`

No arbitrary URLs, hardware backend choices, wallet fees, signing, or MCP
side effects are accepted. It supports only 1–12-qubit restricted OpenQASM
2.0 circuits, up to 80 gates and 4096 shots. Accounts need a server-side
allowlist; a guest cannot use it.

The bridge will *not* submit jobs unless all of the following are configured
by the operator in private Render environment settings:

- On Privi Quantum service: \`QUANTUM_CLOUD_API_KEYS=<strong randomly generated secret>\`
- On Hey Jose backend: \`JOSE_QUANTUM_CLOUD_API_KEY=<the same secret>\`
- On Hey Jose backend: \`JOSE_QUANTUM_CLOUD_OPERATOR_EMAILS=<explicit authorized Jose account email(s)>\`
- On Hey Jose backend: \`JOSE_QUANTUM_CLOUD_ENABLED=true\`

Do **not** put actual keys into GitHub, frontend code, social posts or chat.
Before enabling, first ensure the Privi Quantum Cloud uses a persistent disk
\`QUANTUM_CLOUD_DB_PATH=/data/quantum-cloud.sqlite3\` and complete
an operations/security review. If those credentials are not available,
leave the remote bridge disabled; the free Jose features still work.

Operator-only HTTP endpoints (same-origin for POST):
- \`GET /api/quantum/cloud/info\`: public readiness flag, never a secret.
- \`POST /api/quantum/cloud/jobs\`: Jose session cookie, allowlisted operator, JSON
  \`{"qasm":"OPENQASM 2.0; qreg q[2]; h q[0]; cx q[0],q[1];", "shots":1024}\`.
- \`GET /api/quantum/cloud/jobs/<job_id>\`: only the same Jose user who submitted
  it; restricted cloud states and simulator results.

**Limitations**: Jose's job ownership map is process-local: a restart loses
polling eligibility, even if Privi Quantum retained the job on disk.
This is explicitly a staging/controlled-operator bridge, not a public multi-tenant
production job service. To offer it to end users, first add durable per-account
job mappings, strong quotas, monitoring and an entitlement policy. Do not
enable automatic hardware spending or confuse this with the independent
Privi Quantum CVaR-QAOA paid MCP tool.

All results indicate whether they are classical exact QUBO, classical statevector,
or separately self-reported project status. "Qubit-equivalent decision variables"
does **not** mean 16 physical qubits were used.
