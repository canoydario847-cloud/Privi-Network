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

SHA-256 content identifiers are integrity checks, **not** digital signatures or IBM QPU attestations. The evidence report does not yet use Privi's existing post-quantum signing service.

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

**MCP access:** Privi Quantum now registers a rate-limited, read-only `quantum_evidence_lab` tool accepting `Q`, `gammas`, `betas`, `offset`, optional `qasm`, and optional `counts`. This free evaluation tool is simulator-only and cannot call paid IBM hardware. Before recommending it for production use, verify the latest Render release and tool discovery, and require the independent Qiskit workflow to pass.

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

## v1 hardware-evidence extension — compiled circuits and confidence bounds

The new `hardware_evidence.py` and read-only MCP tool `quantum_hardware_evidence` bridge a critical accountability gap between an ideal, exported QAOA circuit and a supposedly executed backend circuit. The tool binds the original QASM, compiled QASM, reported backend/job ID, submission/completion timestamps, shot count and bitstring results to one canonical SHA-256 receipt. It rejects non-equivalent compiled circuits, malformed counts, inconsistent shot totals and unbounded metadata.

For the fraction of shots attaining the *classically proven optimum*, the receipt includes a **Wilson 95% binomial interval** with an explicit independence assumption. It never treats the finite-shot distribution as an exact simulation, and it never upgrades reported provider metadata into proof. Every receipt sets `provider_provenance_verified=false`, `physical_qpu_execution_verified=false` and `quantum_advantage_claimed=false`.

**This is not an IBM hardware validation.** The current verifier accepts only small OpenQASM programs in the Privi h/rx/rz/cx basis; it cannot verify arbitrary physical native-gate ISA circuits or establish that a provider ran a job. Future authenticated provenance requires a provider-signed job artifact or a trustworthy provider API read with independent job ownership verification and a compiled-circuit digest. The code does not spend on IBM or external QPU hardware.

For reviewers: `tests/test_hardware_evidence.py` checks the canonical receipt, tampering, strict job IDs, expected shot sums, count distributions, confidence bounds and no QPU claims. The Docker build also fails if the synthetic two-qubit hardware receipt cannot be generated. This is a software-quality gate, not scientific or provider accreditation.

## IBM Runtime readback v1 — authenticated observation, not execution attestation

`ibm_readback.py` provides an **optional server-side, read-only** verification step using a trusted, already-authenticated `QiskitRuntimeService` instance. When a customer has an existing **completed** SamplerV2 job and authorized account access, the module retrieves it by job ID and checks the job ID, backend name, status, single measurement register, shot total, and resulting counts against the content-hashed Privi hardware evidence receipt. It uses `service.job(job_id)` and `job.result()` for an existing job only—never `Sampler.run`, provider submission, cancellation, or billable execution.

The output is a **separate immutable readback record**, not an edit of the original receipt. It can report that job counts and metadata were retrieved through the customer's authenticated IBM client, but does **not** claim the original or compiled circuit was independently bound to the IBM job, that the backend was definitely a physical QPU, that IBM cryptographically signed the result, or that quantum advantage occurred. Those flags remain false. Some IBM client versions may not return the original job input circuit; do not infer it from a claimed circuit hash.

This is **not an externally accessible MCP operation** because customer IBM credentials, consented account isolation, log redaction, and authorization to retrieve jobs must be reviewed before a network-enabled endpoint can be safely offered. The test suite `tests/test_ibm_readback.py` uses only synthetic in-memory job objects and detects modified receipts, inconsistent results, incorrect backends/status, and unsupported Sampler formats. The production Docker build runs it before deployment.

IBM's public documentation describes retrieving existing jobs with QiskitRuntimeService and inspecting SamplerV2 bit-array measurement results. Integration against a real IBM account and real provider evidence is still pending; no IBM hardware request or charge was initiated.

## Read-only IBM input circuit binding — November 20, 2026

`ibm_input_binding.py` adds a stricter *opt-in* verification step for an authorized, **already completed** IBM Sampler job when its input PUB circuit is available through the connected Qiskit Runtime client. It compares the original receipt's content hash and compiled-circuit SHA-256, then verifies job readback before extracting the returned Qiskit `QuantumCircuit`. For a bounded h/rx/rz/cx circuit, it checks every gate's name, qubit/classical-bit indices, numerical parameters, and measurement instructions against the declared compiled OpenQASM 2. Missing input circuits, multiple PUBs, unsupported instructions, modified angles or tampered digests all fail closed.

This provides **account-authenticated job-input readback consistency**, not an IBM-signed artifact or independent proof that a physical QPU executed the circuit. The resulting record explicitly keeps `provider_signed_attestation=false`, `physical_qpu_execution_verified=false`, and `quantum_advantage_claimed=false`. The function uses `service.job` and the existing read-only job.result flow; it does not submit jobs or spend on IBM services. Real-world SDK support for recoverable input circuits varies, so this remains an optional offline library, **not a public MCP endpoint** or production identity integration.

`tests/test_ibm_input_binding.py` uses actual Qiskit circuits and a fake account-bound job client. The quantum Docker image requires its tests to pass before deployment.

## Dual-signature Privi evidence certificate (November 20, 2026)

The **offline, opt-in** `ibm_certificate.py` composes the existing IBM readback and recovered-input binding checks with Privi's existing `Attestor` to issue a limited-scope certificate signed using **Ed25519 and ML-DSA-87**. A valid certificate binds the original evidence receipt hash, authenticated-client input-binding hash, compiled circuit SHA-256 and existing job identifier. It carries explicit `false` statements for IBM-signed attestation, physical QPU execution verification, blockchain anchoring and quantum advantage. The private signing seeds are not embedded in the output.

The verifier checks both signatures and the restricted claim scope. **Public keys delivered inside the certificate bundle are not themselves trustworthy**: independent issuer trust is only reported when a reviewer supplies known-good pinned `key_id`, Ed25519 public key and ML-DSA-87 public key, which all match. No existing IBM account was contacted during development; the test suite uses fake jobs and temporary signing keys. No public endpoint was added, and no blockchain transaction or hardware run was initiated.

The Docker production build includes `tests/test_ibm_certificate.py` to reject tampered reports, unsigned trust promotion, mismatched job-input circuits, unsafe hardware claims and invalid signing keys. A certificate signed by Privi is **not a certificate from IBM**; real-world use requires customer-authorized read-only access to their existing job and independent Privi signer key distribution.

## Single-snapshot consistency hardening — November 20, 2026

The optional IBM job input binder now resolves the customer's already-completed job **once** and uses the same returned job object for the count readback and circuit-input comparison. This addresses a time-of-check/time-of-use failure mode in which independent job lookups could return inconsistent snapshots. Two regression scenarios deliberately implement an adapter that swaps job objects on a second lookup; the binder accepts or rejects the first retrieved snapshot as appropriate and never makes the second lookup. This check neither verifies provider signatures nor proves that backend hardware executed the recovered circuit. No live provider account is accessed or exposed through an MCP route.

## Independent third-party offline certificate audit

The `offline_audit.py` module and `audit_cli.py` command allow IBM researchers and other reviewers to inspect the **complete evidence chain without connecting to Privi, IBM, the blockchain, or paid hardware**. A reviewer must acquire the actual Privi certificate, source hardware receipt, IBM readback record and input-binding record from the consenting job owner, and must obtain **Privi's issuer public keys from a separate, independently trusted channel**. The tool checks Ed25519 plus ML-DSA-87 signatures, pinned key ID and public keys, every SHA-256 evidence record, reported job IDs, compiled QASM digest and the links among the records. It rejects mislinked, tampered, unauthenticated or overclaiming bundles. No private signing seed should ever be shared.

```bash
PYTHONPATH=quantum-server/src python -m privi_quantum.audit_cli \
  --bundle certificate.json --pins independently_verified_keys.json \
  --hardware hardware_receipt.json --readback ibm_readback.json \
  --binding ibm_input_binding.json --qasm compiled.qasm
```

Exit code **0** means only that the Privi-signed *local evidence chain and issuer pin* checked out. Exit **1** means the chain did not verify; exit **2** means the inputs were malformed. An offline tool cannot directly authenticate the claimed IBM Runtime service session, confirm physical quantum hardware executed a circuit, or prove quantum advantage. Those claims remain explicitly false. Published evidence files may contain proprietary algorithms, quantum job identifiers, or measurement data, so obtain consent and redact sensitive inputs before external sharing; redaction changes content hashes and requires fresh signed reports.

The new checks run in the Quantum Docker build as `tests/test_offline_audit.py`.
