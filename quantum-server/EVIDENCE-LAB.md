# Privi Quantum Evidence Lab — independent evaluation package

**Made by Dario Canoy · Privi World Corp · 2026**

## The problem worth solving

Quantum optimization reports can mix a trained mathematical model, an exported circuit, sampled measurements and claimed performance without demonstrating they represent the same computation. Privi Evidence Lab provides a narrowly testable claim: **Does the exported OpenQASM circuit produce the same ideal probability distribution as the trained QAOA model for this precise QUBO and set of angles?**

This is a correctness and accountability tool. It is **not** evidence of quantum advantage, a breakthrough in quantum physics, IBM endorsement or physical IBM QPU execution.

## What exists today

1. Recomputes the exact classical optimum for QUBOs of up to 10 variables.
2. Computes algorithmic QAOA probabilities for the published angles.
3. Independently parses the exported OpenQASM 2 program and simulates its gates.
4. Compares those ideal distributions by total variation distance (TVD); equivalence requires TVD no more than 1e-8.
5. Optionally reports empirical measurement counts and deviations from the ideal distribution, identifying counts as unverified user-supplied data.
6. Outputs QUBO, angles, circuit hash, exact optimum, distribution consistency, and canonical SHA-256 evidence identifier.
7. Adds an independent Qiskit Statevector cross-check in GitHub Actions.

SHA-256 content identifiers are integrity checks, **not** digital signatures or IBM QPU attestations. The standalone report does not yet use Privi's existing post-quantum signing service.

## Offline reproduction

From the repo root, with Python 3.11:

~~~bash
python -m pip install "numpy>=1.26,<3" "scipy>=1.11" "pytest>=8" "cryptography>=45"
PYTHONPATH=quantum-server/src python -m privi_quantum.evidence_cli quantum-server/examples/evidence-demo.json --output quantum-evidence.json
~~~

Review the output's verification.passed, TVD, exact-optimum proof and content_sha256. A different QASM program that produces a non-equivalent distribution must fail.

Independent Qiskit check (no IBM credentials):

~~~bash
python -m pip install "qiskit>=1.3,<3"
PYTHONPATH=quantum-server/src python -m pytest quantum-server/tests/test_evidence_lab.py quantum-server/tests/test_evidence_qiskit.py -v
~~~

GitHub Actions workflow: .github/workflows/privi-quantum-evidence.yml.

## Limits that an IBM reviewer should see

- Only small QUBOs and classical exact statevector simulation are supported. This cannot demonstrate a speedup over classical algorithms.
- Ideal simulation does not establish actual QPU noise, calibration, compiled gate fidelity, error mitigation or queue latency.
- Qiskit is an independent software reference; IBM has not verified or endorsed this work.
- Real IBM Runtime work needs registered credentials, ISA-aware transpilation, measured provider execution and explicit budget authorization. None occurs here.
- A future hardware receipt should bind provider job ID, selected backend, original and compiled circuit hashes, shots, counts, timing, calibration metadata, compilation settings, and verified provenance.
- Report signatures, provider provenance and statistically meaningful measurement confidence bounds remain future work.

## Proposed 30-minute IBM technical evaluation

Let IBM select a three-to-ten-qubit QUBO and independent Qiskit circuit. Have IBM and Privi rerun the same inputs, compare the distributions, verify the report's content hash and deliberately tamper with the QASM to confirm the verifier fails. Then discuss a vendor-neutral evidence format for binding compiled ISA circuits to observed Sampler counts.

The technical review is a proposal, not a claimed IBM collaboration, sponsorship or procurement decision.
