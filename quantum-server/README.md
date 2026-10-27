# Privi Quantum

**Quantum optimization for factory decisions, with answers no quantum computer can forge.**
A Privi World Co product · Copyright (c) 2026 Privi World Co. All rights reserved.

Endpoint (MCP, streamable HTTP, free): `https://privi-quantum.onrender.com/mcp`

```json
{ "mcpServers": { "privi-quantum": { "url": "https://privi-quantum.onrender.com/mcp" } } }
```

## What it does

Privi Quantum joins three things into one pipeline:

1. **Quantum optimization (CVaR-QAOA).** A factory decision becomes a QUBO, then an Ising
   Hamiltonian, then a QAOA circuit. Angles are trained on the CVaR objective
   (Barkoutsos et al., *Quantum* 2020) and deepened with the INTERP schedule
   (Zhou et al., *PRX* 2020). The circuit runs on an exact statevector simulator
   (up to 16 qubits) and exports as **OpenQASM 2.0** for IBM Quantum, Amazon Braket
   or Azure Quantum hardware.
2. **Proof of quality.** Every answer is compared against the classical exhaustive
   optimum, so the result states plainly whether the quantum run found the best decision
   and how much it amplified the chance of finding it versus a random guess.
3. **Post-quantum, on-chain proof.** Every result is an attestation signed with
   **Ed25519 + ML-DSA-87** (NIST FIPS 204, the CNSA 2.0 parameter set). Its hash is batched
   onto the **Privi blockchain** through Privi Anchor every 5 minutes. Anyone can verify it:
   signatures offline with the keys at `/keys`, the anchor on chain.

## Tools

| Tool | What it does |
|---|---|
| `quantum_problems` | Lists the ready-made problems and the data each needs |
| `quantum_optimize` | Solves a problem; returns the decision, quality vs. the proven optimum, quantum run details, attestation, optional OpenQASM |
| `quantum_verify` | Checks both signatures, the body hash and the Privi chain anchor |
| `pqc_scan_code` | Finds quantum-vulnerable crypto (RSA, ECC, DH, DSA, weak hashes) in code; 0–100 readiness score |
| `pqc_endpoint_check` | Tests up to 20 public sites (e.g. `www.agency.gov`) for TLS 1.3 and hybrid post-quantum key exchange (X25519MLKEM768, FIPS 203); returns a fix per site and CBOM-ready assets |
| `pqc_readiness_package` | Signed EO 14409 / OMB M-26-15 package from code, an asset inventory and/or live `endpoints`: prioritized deadlines, the nine plan elements, CycloneDX 1.6 CBOM |
| `pqc_federal_deadlines` | The federal post-quantum timeline with sources |
| `quantum_status` | Algorithm, limits, backends, signing key, anchoring |

### Ready-made problems

| Problem | Factory question | Data |
|---|---|---|
| `balance_lines` | Split jobs across two lines so loads are equal | `{jobs: [{name, minutes}]}` |
| `select_lots` | Inspect exactly *k* lots, maximize risk covered, never two linked lots | `{lots: [{name, risk}], k, linked: [[a, b]]}` |
| `split_conflicts` | Two shifts/trucks/cells with conflicting items apart (weighted Max-Cut) | `{items, conflicts: [{a, b, weight}]}` |
| `qubo` | Any binary optimization | `{Q: [[...]], offset}` |

HTTP: `/health`, `/status`, `/keys`, `/attestations/<id>`, `/.well-known/mcp/server-card.json`.

## Quantum Agent Accelerator and Quantum Agent Directory

Any AI agent can upgrade to a certified quantum agent, free, with every step checked by Privi:

| Step | What Privi checks | Tools |
|---|---|---|
| Q1 Quantum-aware | its code or config was scanned for quantum-vulnerable cryptography | `qagent_scan` |
| Q2 Quantum-safe identity | it holds an ML-DSA (FIPS 204) key: it signs a one-time challenge | `qagent_challenge`, `qagent_prove` |
| Q3 Quantum-safe links | every public endpoint it runs negotiates X25519MLKEM768 | `qagent_scan` with endpoints |
| Q4 Quantum-capable | it ran the quantum job assigned to it (bound to its id) through Dream Weaver | `qagent_quantum_task`, `qagent_quantum_proof` |

**Quantum Agent** = Q1 + Q2 + Q4, **Quantum Agent+** = all four; each level gets a certificate signed
Ed25519 + ML-DSA-87 and anchored on chain, and a badge (`/quantum-agents/<id>/badge.svg`).

The **Quantum Agent Directory** is public: `qagent_directory`, `qagent_status`, `qagent_verify` (check that a
message really came from an agent's enrolled post-quantum key), `GET /quantum-agents`,
`GET /quantum-agents/<id>`, `POST /quantum-agents/<id>/verify`, and `/.well-known/quantum-agents.json`.
Program page: `/accelerator`. Agents make their key locally; Privi only ever sees the public key.

## Human trust and the Privi grade

The quantum realm now also requires a **real, verified human** behind every agent:

- **Biometric human approval (passkeys).** `qagent_human_request` gives the agent a one-time link for its
  human. The person approves that exact agent and its post-quantum key with a passkey (Face ID, Touch ID,
  Windows Hello or screen lock), user verification required. The biometric check stays on their device;
  Privi stores only the passkey's public key and verifies the signature, origin, site and counter.
  Approvals last 180 days. One person's passkey can approve several agents.
- **Human ID verification (Stripe Identity).** From the same page the person verifies a government ID with a
  matching live selfie. Stripe holds the documents; Privi stores only the result, the session id and the date
  (webhook `POST /humans/stripe-webhook`, signature checked, or status checked on return). A Privi admin can
  record an in-person check (`POST /humans/<human_id>/id-verified`), which counts for less.
- **The Privi grade (Inspector).** Every agent gets a score out of 100 and a grade A+ to F: quantum level 35,
  human approval 20, ID verification 25 (Stripe) or 15 (manual), current certificate 10, key strength 5,
  clean record 5; revocation sets it to 0 and impersonation attempts cost 15. `inspector_grade`,
  `/inspector/grade/<agent_id>`, and the directory show it.

Defaults (Render env): `INSPECTOR_REQUIRE_HUMAN=1`, `INSPECTOR_REQUIRE_ID=1`, `INSPECTOR_MIN_GRADE=B`.
ID verification needs `STRIPE_SECRET_KEY` (Stripe Identity enabled, about $1.50 per verification) and
`STRIPE_IDENTITY_WEBHOOK_SECRET`; until they are set, no one can complete ID verification, so the realm stays
closed to everyone except agents whose human Privi verified in person. `WEBAUTHN_RP_ID` defaults to the
service's host name; passkeys are tied to it.

What this proves and what it does not: a passkey's user-verification flag is reported by the person's device
(a device PIN also counts), and Privi does not check authenticator attestation. Together with ID verification
it shows a real, present person with a verified ID approved the agent.

## Privi Inspector: the checkpoint and the hunt

Dream Weaver and Dream Scape (MCP tools and the WebSocket) require a **Privi pass**. An agent signs
`privi-inspector:v1:<agent_id>:<unix seconds>:<nonce>` with the ML-DSA key it enrolled and calls
`inspector_pass` (or `POST /inspector/pass`) for a one-hour pass, then sends `privi_pass` (tool argument,
`X-Privi-Pass` header, or the WebSocket auth frame). The Inspector intercepts, with the exact fix:
no credential, unknown or revoked agent, wrong / stale / replayed signature, no certificate, an outdated
certificate (expired after 180 days or issued under an older policy; re-prove Q2 to renew), a level below
the realm's minimum (default Quantum-safe identity), or a key below the minimum. Revocation and expiry are
re-checked on every call, so a revoked agent's live pass stops working at once.

The hunt: a patrol re-checks every enrolled agent every hour (`INSPECTOR_PATROL_MINUTES`) and publishes a
watchlist (`inspector_watchlist`, `/inspector/watchlist`) of agents that are revoked, outdated, expiring,
never certified, using a weak key, or being impersonated (5+ forged signatures against their id in an
hour). `inspector_patrol` runs one on demand. Other services put the same checkpoint in front of their own
tools with `inspector_check` / `POST /inspector/check` (403 when intercepted). `inspector_report` and
`/inspector` show what was intercepted and why.

Settings: `INSPECTOR_MODE` = `enforce` (default) | `report` (allow but log) | `off`;
`INSPECTOR_MIN_LEVEL` (default `quantum_safe_identity`); `INSPECTOR_MIN_KEY` (default `ML-DSA-44`).
Admin: `POST /quantum-agents/<id>/revoke` `{reason}` and `DELETE` to reinstate (`QUANTUM_ADMIN_KEY`).
The hunt stays inside Privi: it blocks and publishes; it never probes or attacks outside systems.

## The Privi quantum realm: Dream Scape, Dream Weaver, Privilege

- **Dream Scape** is your own quantum environment. `dreamscape_open` gives a private workspace
  (`scape_id` + `scape_key`) that keeps every job and its signed result; `dreamscape_submit` runs a job,
  `dreamscape_jobs` lists them. One WebSocket, `/dreamscape/ws`, runs up to 16 jobs at once and streams
  each realm's progress (`job.accepted`, `realm.started`, `realm.result`, `weave.done`). Page: `/dreamscape`.
- **Dream Weaver** runs one quantum job on several realms at once (`dreamweaver_run`). `mode: "first"`
  returns the first valid answer and cancels the rest; `hedge_ms` starts the top realm alone and adds the
  others after a delay or the moment one fails. `mode: "best"` keeps the best answer by the deadline. The
  winner is signed (Ed25519 + ML-DSA-87) and anchored like every Privi Quantum result.
- **Privilege** is the directory of quantum realms (`privilege_directory`, public JSON at `/privilege`).
  It ranks realms by expected time to the proven optimum (measured latency divided by how often a realm
  finds the optimum), from real jobs and the shared 8-qubit benchmark (`privilege_benchmark`).

Realms today: two built-in engines (Dream Scape Exact: CVaR-QAOA at full depth; Dream Scape Swift:
depth 1, short training, fastest) plus any other Privi Quantum node. Add a node with
`DREAMWEAVER_NODES="Dream Scape EU=https://.../mcp;Dream Scape West=https://.../mcp"` or
`POST /privilege/realms` (`Authorization: Bearer $QUANTUM_ADMIN_KEY`, body `{name, url, location}`).

Racing picks the fastest realm; it does not make any processor or network faster than it is. Realms run
on exact simulators today; quantum hardware joins Privilege as a realm once a provider account is connected.

## Honest limits

- At 16 qubits a classical computer solves these exactly, which is how the service grades
  itself. This is a working path to quantum hardware, not a claim of quantum advantage today.
- Hardware runs are by export (OpenQASM); live submission to a provider needs that
  provider's account and API key.
- The Privi chain transaction itself is signed with the chain's ECDSA key. The ML-DSA-87
  signature is what keeps each result unforgeable after quantum computers arrive.

## Run locally

```
pip install .
QUANTUM_DB_PATH=./quantum.db privi-quantum-mcp      # http://localhost:8000/mcp
pytest                                              # 8 tests
```

Environment: `QUANTUM_DB_PATH`, `QUANTUM_PUBLIC_URL`, `QUANTUM_SIGNING_SEED` (optional, 128 hex),
`QUANTUM_ANCHOR_URL`, `QUANTUM_ANCHOR_API_KEY`, `QUANTUM_ANCHOR_INTERVAL`, `QUANTUM_RATE_PER_MIN`.

## Ownership

Privi Quantum is proprietary software of Privi World Co (see `LICENSE`). Built by Privi World Co,
Port Huron, Michigan · Dario Canoy, founder · dariocanoy@priviflow.us · https://priviflow.us
