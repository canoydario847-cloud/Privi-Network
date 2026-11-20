# Copyright (c) 2026 Privi World Corp. All rights reserved.
# Made by Dario Canoy.
"""Privi Quantum Hardware Evidence v1: fail-closed, vendor-neutral receipt.

Ties a QAOA model to two exact circuit sources (exported and compiled),
provider-supplied job metadata and sampled counts WITHOUT trusting any claim
that hardware ran. All fields are user supplied. This is *not* an IBM
attestation, provider job verification, signature, or quantum advantage proof.
"""
from __future__ import annotations

import hashlib
import math
import re
from datetime import datetime, timezone

import numpy as np

from .evidence_lab import canonical_sha256, evaluate, validate_counts
from .hardware import parse_qasm, simulate
from .qaoa import ProblemError, Qubo

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,159}$")
MAX_SHOTS = 1_000_000
MAX_QASM = 200_000


def _identifier(value, field):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ProblemError(f"{field} must be a bounded identifier")
    return value


def _utc(value, field):
    if not isinstance(value, str) or len(value) > 40:
        raise ProblemError(f"{field} must be an ISO UTC timestamp")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProblemError(f"{field} is not a valid timestamp") from exc
    if stamp.tzinfo is None or stamp.utcoffset().total_seconds() != 0:
        raise ProblemError(f"{field} must specify UTC")
    return stamp


def wilson_interval(successes: int, shots: int, z: float = 1.959963984540054) -> dict:
    """Wilson score 95% binomial interval, descriptive for independent shots.

    Correlated shots / drift invalidate the nominal confidence coverage.
    """
    if type(successes) is not int or type(shots) is not int or not 0 <= successes <= shots <= MAX_SHOTS or shots < 1:
        raise ProblemError("Invalid success count or shot count")
    p = successes / shots
    d = 1 + z*z/shots
    center = (p + z*z/(2*shots))/d
    half = z*math.sqrt(p*(1-p)/shots + z*z/(4*shots*shots))/d
    return {"method":"wilson_score_95_percent",
            "lower":max(0.0,center-half), "upper":min(1.0,center+half),
            "independence_assumption":"shots_are_independent",
            "caveat":"Drift and correlated hardware errors can invalidate this interval"}


def make_hardware_evidence(*, qubo: Qubo, gammas, betas, source_qasm: str,
                           compiled_qasm: str, counts: dict[str, int],
                           provider: str, backend: str, provider_job_id: str,
                           submitted_utc: str, completed_utc: str,
                           shots: int, compilation: dict | None = None) -> dict:
    """Offline local verification only; never contacts hardware providers."""
    for field, value in (("provider",provider),("backend",backend),("provider_job_id",provider_job_id)):
        _identifier(value,field)
    start, finish = _utc(submitted_utc,"submitted_utc"), _utc(completed_utc,"completed_utc")
    if start > finish:
        raise ProblemError("Completion precedes submission")
    if type(shots) is not int or not 1 <= shots <= MAX_SHOTS:
        raise ProblemError("Shots must be 1-1000000")
    if not isinstance(source_qasm,str) or not isinstance(compiled_qasm,str) or (
        not 1 <= len(source_qasm) <= MAX_QASM or not 1 <= len(compiled_qasm) <= MAX_QASM
    ):
        raise ProblemError("Both QASM sources must be bounded")
    if not isinstance(compilation,(type(None),dict)) or (
        compilation is not None and (len(compilation)>16 or len(str(compilation))>2000)
    ):
        raise ProblemError("Compilation metadata is too large")
    original = evaluate(qubo,gammas,betas,qasm=source_qasm)
    if not original["verification"]["passed"]:
        raise ProblemError("Original QAOA circuit failed mathematical equivalence")
    n, basis = parse_qasm(compiled_qasm)
    if n != qubo.n or len(basis)>20000:
        raise ProblemError("Compiled QASM qubit/gate limit exceeded")
    # This only supports QASM in h/rx/rz/cx basis; an actual backend's ISA
    # may need separate transpilation metadata and native-gate simulator.
    ideal = simulate(basis,n)
    expected_n, expected_gates = parse_qasm(source_qasm)
    original_ideal = simulate(expected_gates,expected_n)
    compilation_tvd = float(np.abs(ideal-original_ideal).sum()/2)
    if compilation_tvd > 1e-8:
        raise ProblemError("Compiled circuit is not distribution-equivalent to original")
    sampled = validate_counts(counts,n)
    if sum(counts.values()) != shots:
        raise ProblemError("Reported shots disagree with supplied counts")
    costs = qubo.all_costs()
    optimum = float(costs.min())
    opt_mask = costs <= optimum + 1e-9*max(1.0,abs(optimum))
    successes = sum(c for bitstring,c in counts.items() if opt_mask[int(bitstring,2)])
    sample_tvd = float(np.abs(sampled-ideal).sum()/2)
    metadata = compilation or {}
    # Keep constrained JSON values, never store arbitrary Python objects.
    for k,v in metadata.items():
        if not isinstance(k,str) or not _ID.fullmatch(k) or (
            not isinstance(v,(str,int,float,bool,type(None))) or
            (isinstance(v,float) and not math.isfinite(v)) or
            (isinstance(v,str) and len(v)>200)
        ):
            raise ProblemError("Compilation metadata must use bounded primitive values")
    receipt = {
        "schema":"privi.quantum.hardware_evidence.v1",
        "evidence_class":"self_reported_unverified",
        "provider_provenance_verified":False,
        "physical_qpu_execution_verified":False,
        "quantum_advantage_claimed":False,
        "source_evidence_sha256":original["content_sha256"],
        "original_qasm_sha256":hashlib.sha256(source_qasm.encode()).hexdigest(),
        "compiled_qasm_sha256":hashlib.sha256(compiled_qasm.encode()).hexdigest(),
        "provider":provider,"backend":backend,
        "provider_job_id":provider_job_id,
        "submitted_utc":start.isoformat(),"completed_utc":finish.isoformat(),
        "compilation":dict(sorted(metadata.items())),
        "qubits":n,"bit_order":"q[n-1]...q[0]",
        "shots":shots,"counts":dict(sorted(counts.items())),
        "checks":{
            "original_qaoa_equivalent":True,
            "compiled_distribution_equivalent":True,
            "compiled_distribution_tvd":compilation_tvd,
            "sample_distribution_tvd_from_ideal":sample_tvd,
            "counts_match_shots":True,
        },
        "quality":{
            "exact_optimum_cost":optimum,
            "observed_optimum_count":successes,
            "empirical_optimum_probability":successes/shots,
            "ideal_optimum_probability":float(ideal[opt_mask].sum()),
            "empirical_95_percent_interval":wilson_interval(successes,shots),
        },
        "verification_limitations":[
            "Provider job ID and backend label are self-reported, not independently authenticated",
            "No IBM Quantum / third-party provider API call was made",
            "Local simulation does not establish noisy hardware fidelity or speedup",
            "Reported sample statistics assume independent shots",
        ],
    }
    receipt["content_sha256"]=canonical_sha256(receipt)
    return receipt
