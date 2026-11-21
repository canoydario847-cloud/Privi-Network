# Privi Quantum | Engineering evaluation
Made by Dario Canoy • Privi World Corp • November 21, 2026

## Purpose
Evaluate a provider-neutral quantum evidence workflow without submitting a QPU job. This is a proposed technical evaluation, not an IBM partnership, endorsement, or certification.

## Reproduce locally
Use Python 3.11+ (the hosted build uses 3.13), a permitted checkout of this repository, and a fresh virtual environment. Installing dependencies requires network access; generation and audit themselves are offline.

```sh
cd quantum-server
python -m pip install . 'qiskit>=1.3,<3' 'pytest>=8'
python -m privi_quantum.audit_demo review-demo
python -m privi_quantum.audit_cli --synthetic-demo \
  --bundle review-demo/certificate.json --pins review-demo/test_pins.json \
  --hardware review-demo/hardware_receipt.json --readback review-demo/readback.json \
  --binding review-demo/binding.json --qasm review-demo/compiled.qasm
```

The demo directory must not already exist. The disposable keys and fake job are not real provider credentials or production trust roots. Successful demo verification means signature and evidence-chain consistency only.

## Acceptance criteria
- Explicit synthetic mode: exit 0; synthetic_demo=true; issuer_key_independently_trusted=false.
- Repeat audit without --synthetic-demo: exit 1.
- Replace hardware_receipt.json in the command with tampered_receipt.json: exit 1.
- Alter compiled.qasm or a signed claim: exit 1.
- No physical QPU claim, IBM account contact, payment, or blockchain transaction.
- Production build uses the evidence tests, including independent Qiskit comparisons. On November 21, 2026 the prior verified production build passed 79 tests; consult the current build log for later revisions.

## Proposed pilot
1. Reviewer runs the synthetic demonstration and records results independently.
2. With explicit permission, select a previously completed, non-sensitive Sampler job. Use customer-owned credentials locally, not emailed to Privi. No new hardware job.
3. Determine whether the current Runtime SDK exposes sufficient input and result information. Unsupported native basis gates, circuit widths, layouts, or unavailable inputs must be reported as gaps, not silently accepted.
4. Compare job metadata, counts and retrieved inputs; agree on a bounded Privi certificate claim and independently distribute trusted issuer keys.
5. Produce a joint fit/gap report. A Privi signature does not constitute an IBM signature or physical execution proof.

## Boundaries
Current circuit binding supports a small h/rx/rz/cx subset, not general IBM native ISA or arbitrary physical layouts. Synthetic provider-shaped records simulate readback fields; only the signed demo classification and explicit demo mode permit their use. Production authentication and authorization integration, strict measurement semantics, native transpilation support and a real SDK integration test remain outstanding. No quantum advantage, QPU execution, or provider endorsement is claimed. No financial commitment is requested for this proposed pilot.

Product: https://privi-quantum-vvmj.onrender.com
