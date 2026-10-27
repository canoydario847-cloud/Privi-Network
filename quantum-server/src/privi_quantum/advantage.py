# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Quantum - https://priviflow.us - dariocanoy@priviflow.us
"""Quantum Advantage Receipts: every quantum answer is raced against classical baselines,
and the result is signed and anchored, including when classical wins.

Baselines (run on this server, timed):
  exhaustive          checks all 2^n assignments; the proven optimum (n <= 16 here)
  simulated_annealing single-bit-flip Metropolis with a geometric schedule and restarts,
                      the standard classical heuristic for QUBO

Verdict, in order: the lower cost wins (quality first); on equal cost the faster wall-clock
time wins. The receipt says plainly what the times measure: a local simulator run includes
classical circuit training, a hardware run is submission-to-result turnaround (queue included).
At the sizes this service handles, classical methods are expected to win or tie; the receipt
exists so any future quantum win is provable and any claim of one can be checked.
"""
from __future__ import annotations

import math
import time

import numpy as np

from .qaoa import Qubo

VERDICTS = ("quantum_won", "classical_won", "tie")


def exhaustive(qubo: Qubo) -> dict:
    t0 = time.perf_counter()
    costs = qubo.all_costs()
    k = int(np.argmin(costs))
    ms = (time.perf_counter() - t0) * 1000
    return {"method": "exhaustive", "about": f"all {2 ** qubo.n} assignments checked: proven optimum",
            "solution": [int((k >> i) & 1) for i in range(qubo.n)], "cost": float(costs[k]), "runtime_ms": round(ms, 3)}


def simulated_annealing(qubo: Qubo, sweeps: int = 200, restarts: int = 8, seed: int | None = 7) -> dict:
    t0 = time.perf_counter()
    rng = np.random.default_rng(seed)
    S = (qubo.Q + qubo.Q.T) / 2
    n = qubo.n
    diag = np.diag(S).copy()
    scale = float(np.max(np.abs(S))) or 1.0
    t_hi, t_lo = 2.0 * scale, 1e-3 * scale
    best_x, best_c = None, math.inf
    for _ in range(restarts):
        x = rng.integers(0, 2, n).astype(float)
        field = S @ x
        c = float(x @ S @ x) + qubo.offset
        for s in range(sweeps):
            T = t_hi * (t_lo / t_hi) ** (s / max(1, sweeps - 1))
            for i in rng.permutation(n):
                d = 1 - 2 * x[i]                          # +1 flips 0->1, -1 flips 1->0
                delta = 2 * d * field[i] + diag[i]          # (x + d e_i)^T S (x + d e_i) - x^T S x, d^2 = 1
                if delta <= 0 or rng.random() < math.exp(-delta / T):
                    x[i] += d
                    field += d * S[:, i]
                    c += delta
                    if c < best_c - 1e-12:
                        best_c, best_x = c, x.copy()
        if best_x is None:
            best_c, best_x = c, x.copy()
    ms = (time.perf_counter() - t0) * 1000
    return {"method": "simulated_annealing", "about": f"{restarts} restarts x {sweeps} sweeps, Metropolis bit flips",
            "solution": [int(v) for v in best_x], "cost": float(qubo.cost(best_x)), "runtime_ms": round(ms, 3)}


def best_from_counts(qubo: Qubo, counts: dict[int, int]) -> dict:
    """The best measured outcome and how often the optimum showed up."""
    costs = qubo.all_costs()
    cmin = float(costs.min())
    tol = 1e-9 * max(1.0, abs(cmin))
    shots = sum(counts.values()) or 1
    k = min(counts, key=lambda kk: costs[kk])
    hits = sum(c for kk, c in counts.items() if costs[kk] <= cmin + tol)
    return {"solution": [int((k >> i) & 1) for i in range(qubo.n)], "cost": float(costs[k]),
            "found_optimum": bool(costs[k] <= cmin + tol), "optimum_frequency": round(hits / shots, 6),
            "shots": shots, "distinct_outcomes": len(counts)}


def verdict(quantum: dict, classical: list[dict], tol: float = 1e-9) -> dict:
    best_c = min(classical, key=lambda c: (c["cost"], c["runtime_ms"]))
    qc, cc = quantum["cost"], best_c["cost"]
    t = tol * max(1.0, abs(cc))
    if qc < cc - t:
        v, why = "quantum_won", "quantum found a lower-cost answer than every classical baseline"
    elif qc > cc + t:
        v, why = "classical_won", f"{best_c['method']} found a lower-cost answer"
    else:
        fastest = min(classical, key=lambda c: c["runtime_ms"])
        if quantum["runtime_ms"] < fastest["runtime_ms"]:
            v, why = "quantum_won", "same answer quality, quantum was faster"
        elif quantum["runtime_ms"] > fastest["runtime_ms"]:
            v, why = "classical_won", f"same answer quality, {fastest['method']} was faster"
        else:
            v, why = "tie", "same answer quality and time"
    return {"verdict": v, "why": why, "best_classical": best_c["method"],
            "quality_gap": round(qc - cc, 9), "speed_ratio_quantum_over_best_classical":
                round(quantum["runtime_ms"] / max(1e-6, min(c["runtime_ms"] for c in classical)), 3)}


def receipt_body(problem: str, problem_sha: str, qubo: Qubo, quantum: dict, classical: list[dict]) -> dict:
    v = verdict(quantum, classical)
    return {"problem": problem, "problem_sha256": problem_sha, "qubits": qubo.n,
            "quantum": quantum, "classical": classical, **v,
            "timing_note": ("local simulator time includes classical training of the circuit angles"
                            if quantum.get("backend_kind") != "qpu" else
                            "quantum time is submission-to-result turnaround on real hardware, queue included; "
                            "circuit angles were trained classically before submission"),
            "honesty": "Privi seals this receipt whichever side wins."}
