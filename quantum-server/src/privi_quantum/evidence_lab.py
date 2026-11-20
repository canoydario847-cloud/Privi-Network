# Copyright (c) 2026 Privi World Corp. All rights reserved.
# Made by Dario Canoy.
"""Privi Quantum Evidence Lab: reproducible, fail-closed QAOA/QASM equivalence.

The *algorithmic* QAOA statevector and an independently gate-by-gate simulated
OpenQASM circuit must agree, with explicit bit ordering, before a benchmark
receipt can report a verified circuit. This is simulator evidence only: NOT IBM
QPU execution, not a quantum advantage or a cryptographic signature.

Outputs include SHA256 content identifiers so independent reviewers can
recompute exact claims from the published QUBO, angles, QASM and metrics.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Mapping

import numpy as np

from .qaoa import Qubo, ProblemError, qaoa_state, to_qasm
from .hardware import parse_qasm, simulate

MAX_EVIDENCE_QUBITS = 10
MAX_RECEIPT_COUNTS = 1_000_000
EQUIVALENCE_TOLERANCE = 1e-8


def canonical_sha256(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=True, allow_nan=False).encode("ascii")
    ).hexdigest()


def _bits(k: int, n: int) -> list[int]:
    return [(k >> i) & 1 for i in range(n)]


def _validate_angles(gammas, betas):
    if (not isinstance(gammas, (list, tuple)) or
            not isinstance(betas, (list, tuple)) or
            not 1 <= len(gammas) == len(betas) <= 4):
        raise ProblemError("Provide matching gamma/beta arrays with 1-4 layers")
    angles = []
    for value in list(gammas) + list(betas):
        if isinstance(value, bool) or not isinstance(value, (float, int)):
            raise ProblemError("Angles must be finite numbers")
        if not math.isfinite(value) or abs(value) > 1000:
            raise ProblemError("Angles must be finite and bounded")
        angles.append(float(value))
    p = len(gammas)
    return angles[:p], angles[p:]


def validate_counts(counts: Mapping[str, int], n: int) -> np.ndarray:
    """IBM/Qiskit bitstring order: q[n-1] ... q[0], qubit zero on right."""
    if not isinstance(counts, dict) or len(counts) > 2**n:
        raise ProblemError("Counts must be a bounded bitstring dictionary")
    out = np.zeros(2**n, dtype=float)
    total = 0
    for bitstring, count in counts.items():
        if (not isinstance(bitstring, str) or len(bitstring) != n
                or any(bit not in "01" for bit in bitstring)):
            raise ProblemError("Count keys must be fixed-width binary strings")
        if type(count) is not int or count < 0:
            raise ProblemError("Counts must be nonnegative integers")
        total += count
        if total > MAX_RECEIPT_COUNTS:
            raise ProblemError("Maximum receipt sample count exceeded")
        out[int(bitstring, 2)] += count
    if total <= 0:
        raise ProblemError("At least one shot is required")
    return out / total


def evaluate(qubo: Qubo, gammas, betas, *, qasm: str | None = None,
             counts: dict[str, int] | None = None,
             tolerance: float = EQUIVALENCE_TOLERANCE) -> dict:
    """Verify candidate circuit against algorithmic QAOA; no QPU calls.

    If counts supplied, reports observed sampling discrepancy, not an
    assertion that finite-shot samples must equal the ideal distribution.
    """
    if not isinstance(qubo, Qubo):
        raise ProblemError("A Qubo instance is required")
    if qubo.n > MAX_EVIDENCE_QUBITS:
        raise ProblemError("Evidence Lab has a conservative 10-qubit limit")
    if not isinstance(tolerance, (int, float)) or isinstance(tolerance, bool) or (
            not math.isfinite(tolerance) or not 0 < tolerance <= EQUIVALENCE_TOLERANCE):
        raise ProblemError("Tolerance must be finite and at most 1e-8")
    gam, bet = _validate_angles(gammas, betas)
    costs = qubo.all_costs()
    cmin, cmax = float(costs.min()), float(costs.max())
    span = cmax - cmin
    if span <= 0:
        raise ProblemError("Constant-objective problem is not benchmarkable")
    cn = (costs - cmin) / span
    expected_qasm = to_qasm(qubo, gam, bet, cmin, span)
    source = expected_qasm if qasm is None else qasm
    if not isinstance(source, str) or len(source) > 200_000:
        raise ProblemError("QASM source must be a bounded string")
    nq, gates = parse_qasm(source)
    if nq != qubo.n or len(gates) > 20000:
        raise ProblemError("QASM qubits or gate count do not match")
    algorithm_probs = np.abs(qaoa_state(cn, gam, bet, qubo.n))**2
    algorithm_probs /= algorithm_probs.sum()
    gate_probs = simulate(gates, nq)
    tvd = float(np.abs(algorithm_probs - gate_probs).sum()/2)
    max_delta = float(np.max(np.abs(algorithm_probs - gate_probs)))
    verified = tvd <= tolerance
    opt_mask = costs <= cmin + 1e-9 * max(1.0, abs(cmin))
    optimal_probability = float(gate_probs[opt_mask].sum())
    random_probability = float(np.count_nonzero(opt_mask) / len(costs))

    # Public evidence commits to inputs and every recomputable summary field.
    payload = {
        "schema":"privi.quantum.evidence.v1",
        "run_type":"classical_exact_statevector_simulation",
        "physical_qpu":False,
        "quantum_advantage_claimed":False,
        "qubits":qubo.n, "layers":len(gam), "bit_order":"q[n-1]...q[0]",
        "qubo":{"Q":qubo.Q.tolist(),"offset":float(qubo.offset)},
        "angles":{"gamma":gam,"beta":bet},
        "source_qasm_sha256":hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "expected_qasm_sha256":hashlib.sha256(expected_qasm.encode("utf-8")).hexdigest(),
        "gate_count":len(gates),
        "verification":{
            "passed":bool(verified),
            "total_variation_distance":tvd,
            "maximum_probability_delta":max_delta,
            "tolerance":float(tolerance),
        },
        "quality":{
            "exact_optimal_cost":cmin,
            "exact_optimal_assignment":_bits(int(np.argmin(costs)),qubo.n),
            "ideal_probability_of_optimum":optimal_probability,
            "random_assignment_probability_of_optimum":random_probability,
            "method":"classical enumeration of all 2^n bitstrings",
        },
    }
    if counts is not None:
        sampled = validate_counts(counts, qubo.n)
        payload["samples"] = {
            "total_shots":sum(counts.values()),
            "distribution_tvd_from_ideal":float(np.abs(sampled - gate_probs).sum()/2),
            "empirical_probability_of_optimum":float(sampled[opt_mask].sum()),
            "counts":dict(sorted(counts.items())),
            "source":"user_supplied_unverified",
        }
    payload["content_sha256"] = canonical_sha256(payload)
    return payload
