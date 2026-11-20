# Copyright (c) 2026 Privi World Corp. All rights reserved.
"""Privi Quantum enterprise workload triage: offline, no execution or spending.

A conservative, deterministic gateway for comparing classical and quantum
research paths. This is NOT a quantum-advantage benchmark, procurement quote,
QPU scheduler, production access control, or hardware capability assertion.
"""
from __future__ import annotations

import hashlib
import json
import math

POLICY_VERSION = "privi-quantum-triage-v1"
MAX_VARIABLES = 16
MAX_SIMULATOR_QUBITS = 12
MAX_SHOTS = 4096
MAX_GATES = 500


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def triage_workload(request: dict) -> dict:
    """Produce a reviewable workload plan without executing or spending.

    Allowed workloads are *only* binary optimization and OpenQASM simulation.
    Physical quantum hardware is always disallowed in this module.
    No customer data is retained: the receipt hashes the normalized request.
    """
    if not isinstance(request, dict):
        raise ValueError("workload must be an object")
    allowed = {"kind", "variables", "qubits", "gates", "shots",
               "max_budget_usd", "hardware_requested"}
    if set(request) - allowed:
        raise ValueError("unexpected workload fields")
    kind = request.get("kind")
    if kind not in ("binary_optimization", "circuit_simulation"):
        raise ValueError("unsupported workload kind")
    requested_hardware = request.get("hardware_requested", False)
    if type(requested_hardware) is not bool:
        raise ValueError("hardware_requested must be boolean")
    budget = request.get("max_budget_usd", 0)
    if not _number(budget) or not 0 <= budget <= 1_000_000:
        raise ValueError("invalid budget")
    if kind == "binary_optimization":
        if set(request) & {"qubits", "gates", "shots"}:
            raise ValueError("circuit fields do not apply to optimization")
        n = request.get("variables")
        if type(n) is not int or not 1 <= n <= MAX_VARIABLES:
            raise ValueError("variables must be an integer 1-16")
        route = "classical_exact_baseline" if n <= 12 else "classical_first_research"
        reason = ("Enumerate a bounded exact classical baseline before comparing QAOA"
                  if n <= 12 else
                  "Use a classical solver first; exhaustive search may be costly")
        complexity = {"binary_variables": n, "search_space_size": 2 ** n}
    else:
        if "variables" in request:
            raise ValueError("variables does not apply to circuits")
        n, gates, shots = (request.get("qubits"), request.get("gates"),
                           request.get("shots", 1024))
        if any(type(v) is not int for v in (n, gates, shots)):
            raise ValueError("circuit sizes and shots must be integers")
        if not 1 <= n <= MAX_SIMULATOR_QUBITS:
            raise ValueError("simulator limit is 1-12 qubits")
        if not 0 <= gates <= MAX_GATES or not 1 <= shots <= MAX_SHOTS:
            raise ValueError("circuit gate or shot limit exceeded")
        route = "local_statevector_simulator"
        reason = "Bounded local simulation only; no physical quantum hardware"
        complexity = {"qubits": n, "statevector_amplitudes": 2 ** n,
                      "gates": gates, "shots": shots}
    normalized = {"kind": kind, **complexity,
                  "hardware_requested": requested_hardware,
                  "max_budget_usd": float(budget)}
    digest = hashlib.sha256(json.dumps(
        {"policy": POLICY_VERSION, "request": normalized},
        sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")).hexdigest()
    return {
        "policy": POLICY_VERSION,
        "receipt_sha256": digest,
        "recommended_path": route,
        "reason": reason,
        "estimated_cost_usd": None,
        "execution_performed": False,
        "physical_qpu_used": False,
        "paid_hardware_authorized": False,
        "financial_commitment_usd": 0,
        "hardware_requested": requested_hardware,
        "hardware_review_required": requested_hardware,
        "proven_quantum_advantage": False,
        "limitations": (
            "No provider pricing, performance claim, QPU access, entitlement, "
            "spending approval, or quantum speedup is verified by this report."
        ),
        "complexity": complexity,
    }
