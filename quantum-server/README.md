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
| `quantum_status` | Algorithm, limits, backends, signing key, anchoring |

### Ready-made problems

| Problem | Factory question | Data |
|---|---|---|
| `balance_lines` | Split jobs across two lines so loads are equal | `{jobs: [{name, minutes}]}` |
| `select_lots` | Inspect exactly *k* lots, maximize risk covered, never two linked lots | `{lots: [{name, risk}], k, linked: [[a, b]]}` |
| `split_conflicts` | Two shifts/trucks/cells with conflicting items apart (weighted Max-Cut) | `{items, conflicts: [{a, b, weight}]}` |
| `qubo` | Any binary optimization | `{Q: [[...]], offset}` |

HTTP: `/health`, `/status`, `/keys`, `/attestations/<id>`, `/.well-known/mcp/server-card.json`.

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
