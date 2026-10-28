# Privi Quantum Compute Fabric — workload-placement prototype

A **small, offline prototype** of the software layer Privi could build between
LLM applications and opt-in CPU/GPU/NPU/quantum compute workers.

**This is not a quantum operating system, not model inference, not a networked
worker cluster, and not an installed service.** It does not make language-model
inference faster or cheaper on quantum computers.

## Core idea

```text
Jose / LIFE / 3rd-party applications
         |
         v
Privi unified job contract + identity/privacy policy
         |
         v
Privi Compute Fabric (this prototype: placement only)
      /       |         |          \
  CPU LLM   GPU LLM    NPU LLM     Quantum optimization only
     |          |         |            |
 llama.cpp   vLLM     ONNX Runtime   Existing Privi Quantum /
                                    CUDA-Q/Qiskit adapters (future)
         |
        (future) authenticated execution, status, meter, privacy-safe
        receipt -> Privi Ledger / Anchor / Verify
```

### Why build this?

- **Device abstraction:** applications submit model + workload requirements without
  hard-coding a particular vendor, computer, or AI API.
- **Scheduling:** select among **voluntarily registered** healthy workers with
  the correct model installed and sufficient memory/context.
- **Data protection:** enforce residency and trust requirements before routing.
  No fallback to an untrusted or wrong-region worker, even if faster.
- **Clear quantum separation:** QPUs are eligible only for specifically declared
  quantum optimization jobs; no fabricated QPU acceleration for LLM text generation.
- **Model interoperability:** use a model registry and standard inference adapters
  (OpenAI-compatible llama.cpp/vLLM, ONNX where supported) in later milestones.
- **Accountability:** digest placement metadata locally now; authenticated signing,
  cost settlement, per-node authorization, and Ledger/Anchor receipts require
  separate secure implementation and audit.

### Test locally (Python 3.10+)

```bash
cd compute-fabric
python3 -m unittest -v test_runtime.py
```

Import `Node`, `Workload` and `place` from `runtime.py`. A task only
receives a deterministic **placement decision**, never an executed output.
Use node heartbeat timestamps from a *trusted*, authenticated registry, not an
untrusted client's declaration. The `receipt_digest` is just SHA-256, **not a
cryptographic signature** or proof that anything ran.

### Sequence toward working software

1. Build authenticated opt-in node registry and audited capability probing,
   heartbeats, leases, concurrency reservation and idempotent retry handling.
2. Add local/offline model execution adapters (llama.cpp server, vLLM,
   ONNX Runtime) and trusted model IDs; never accept arbitrary backend URLs
   from users or expose model weights by default.
3. Expose a secured inference API (OpenAI-compatible where appropriate)
   with authorization, data-minimizing logs, streamed outputs, rate limits,
   privacy filters and predictable token/cost budgets.
4. Integrate Jose and LIFE, then Privi Call and Ledger signed run receipts.
5. Support optional quantum optimization jobs using existing Privi Quantum
   or vetted CUDA-Q/Qiskit backends; benchmark against classical alternatives.
6. Test on Windows, Linux, macOS and opt-in edge hosts. This is not permission
   to use or control every computer in the world; every worker must opt in.

No production deployment, native PRVI coin issuance, POP reward,
unverified performance guarantee or hardware allocation is performed here.

Copyright (c) 2026 Privi World Corp. License per repository.
