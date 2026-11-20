# Copyright (c) 2026 Privi World Corp. All rights reserved.
# Made by Dario Canoy.
"""Offline tests for honest provenance, compiled circuit integrity and statistics."""
import numpy as np
import pytest

from privi_quantum.evidence_lab import canonical_sha256
from privi_quantum.hardware_evidence import make_hardware_evidence, wilson_interval
from privi_quantum.qaoa import Qubo, ProblemError, to_qasm


def fixture():
    q = Qubo(np.array([[1., -0.3],[-0.3, -0.8]]))
    gam, bet = [0.6], [0.2]
    costs = q.all_costs()
    qasm = to_qasm(q,gam,bet,float(costs.min()),float(costs.max()-costs.min()))
    args = dict(qubo=q,gammas=gam,betas=bet,
                source_qasm=qasm,compiled_qasm=qasm,
                counts={"00":20,"01":30,"10":40,"11":10},
                provider="IBM-Quantum",backend="ibm_test_backend",
                provider_job_id="synthetic-job-001",
                submitted_utc="2026-11-20T12:00:00Z",
                completed_utc="2026-11-20T12:00:35Z",shots=100,
                compilation={"optimization_level":1})
    return args


def test_hardware_evidence_is_unverified_and_deterministic():
    a=make_hardware_evidence(**fixture())
    b=make_hardware_evidence(**fixture())
    assert a==b
    assert not a["provider_provenance_verified"]
    assert not a["physical_qpu_execution_verified"]
    assert not a["quantum_advantage_claimed"]
    assert a["checks"]["compiled_distribution_equivalent"]
    assert a["shots"]==100
    assert a["content_sha256"]==canonical_sha256({k:v for k,v in a.items() if k!="content_sha256"})
    assert 0<=a["quality"]["empirical_95_percent_interval"]["lower"]<=1
    assert 0<=a["quality"]["empirical_95_percent_interval"]["upper"]<=1


def test_compiled_circuit_mismatch_rejected():
    args=fixture()
    args["compiled_qasm"]="OPENQASM 2.0;\nqreg q[2];\ncreg c[2];\n"
    with pytest.raises(ProblemError,match="distribution-equivalent"):
        make_hardware_evidence(**args)


def test_original_circuit_mismatch_rejected():
    args=fixture()
    args["source_qasm"]="OPENQASM 2.0;\nqreg q[2];\ncreg c[2];\n"
    with pytest.raises(ProblemError,match="mathematical equivalence"):
        make_hardware_evidence(**args)


@pytest.mark.parametrize("changes",[
    {"shots":99}, {"shots":True}, {"provider":"IBM Quantum <script>"},
    {"backend":"bad backend"}, {"provider_job_id":""},
    {"submitted_utc":"2026-11-20T12:02:00Z"},
    {"completed_utc":"2026-11-20T11:59:00Z"},
    {"compilation":{"weird":{"nested":"object"}}},
    {"counts":{"0":100}},
    {"counts":{"00":101}},
    {"counts":{"00":-1}},
])
def test_reject_bad_metadata_shots_and_bitstrings(changes):
    args=fixture()
    args.update(changes)
    with pytest.raises(ProblemError):
        make_hardware_evidence(**args)


def test_wilson_interval_handles_boundaries():
    none=wilson_interval(0,100)
    all_=wilson_interval(100,100)
    assert none["lower"]==0
    assert none["upper"]<0.05
    assert all_["upper"]==1
    assert all_["lower"]>0.95
    assert wilson_interval(50,100)["lower"]<0.5<wilson_interval(50,100)["upper"]
    with pytest.raises(ProblemError):
        wilson_interval(101,100)
