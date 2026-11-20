# Copyright (c) 2026 Privi World Corp.
# Made by Dario Canoy.
"""Quantum Evidence Lab tests: exact independent QASM equivalence, tamper detection."""
import hashlib
import numpy as np
import pytest

from privi_quantum.qaoa import Qubo, ProblemError
from privi_quantum.evidence_lab import evaluate, validate_counts, canonical_sha256


def qubo():
    return Qubo(np.array([[-1., 0.25, 0.], [0.25, -1.1, 0.35],
                          [0., 0.35, -0.8]]), offset=1.2)


@pytest.mark.parametrize("gam,bet", [
    ([0.1], [0.3]),
    ([0.7, 1.2], [0.5, 0.9]),
    ([1.9, -0.4, 2.0], [0.2, 1.1, 0.6]),
    ([0., 0.5, 1., 2.], [0., 0.2, 0.4, 0.6]),
])
def test_generated_qasm_and_analytical_state_agree(gam, bet):
    report = evaluate(qubo(), gam, bet)
    assert report["verification"]["passed"]
    assert report["verification"]["total_variation_distance"] < 1e-12
    assert report["physical_qpu"] is False
    assert report["quantum_advantage_claimed"] is False
    assert report["quality"]["exact_optimal_cost"] <= 10
    digest = report.pop("content_sha256")
    assert digest == canonical_sha256(report)
    assert len(digest) == 64


def test_repeatable_and_input_sensitive_hashes():
    a = evaluate(qubo(), [0.5], [0.3])
    b = evaluate(qubo(), [0.5], [0.3])
    c = evaluate(qubo(), [0.6], [0.3])
    assert a == b
    assert a["content_sha256"] != c["content_sha256"]


def test_tampered_circuit_fails_and_does_not_claim_advantage():
    q = qubo()
    a = evaluate(q, [0.5], [0.3])
    # A valid QASM program with all physics removed is NOT equivalent.
    tampered = ("OPENQASM 2.0;\ninclude \"qelib1.inc\";\nqreg q[3];\n"
                "creg c[3];\n")
    b = evaluate(q, [0.5], [0.3], qasm=tampered)
    assert a["verification"]["passed"]
    assert not b["verification"]["passed"]
    assert b["verification"]["total_variation_distance"] > 1e-8
    assert not b["quantum_advantage_claimed"]


def test_counts_validate_qiskit_bit_order_and_never_claim_hardware():
    report = evaluate(qubo(), [0.3], [0.7],
                      counts={"000":3, "001":7, "111":5})
    assert report["samples"]["total_shots"] == 15
    assert report["samples"]["source"] == "user_supplied_unverified"
    assert report["physical_qpu"] is False
    probs = validate_counts({"001":1, "100":3}, 3)
    assert probs[1] == pytest.approx(0.25)
    assert probs[4] == pytest.approx(0.75)


@pytest.mark.parametrize("bad", [
    {"000":-1}, {"00":1}, {"002":1}, {"111":1.2},
    {"000":True}, {"000":0},
])
def test_invalid_counts_fail_closed(bad):
    with pytest.raises(ProblemError):
        validate_counts(bad, 3)


def test_invalid_angles_and_size_fail_closed():
    with pytest.raises(ProblemError):
        evaluate(qubo(), [float("nan")], [0.1])
    with pytest.raises(ProblemError):
        evaluate(qubo(), [0.5], [])
    with pytest.raises(ProblemError):
        evaluate(qubo(), [0.5], [0.2], tolerance=1.0)
    with pytest.raises(ProblemError):
        evaluate(Qubo(np.eye(11)), [0.2], [0.2])
