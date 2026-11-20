# Copyright (c) 2026 Privi World Corp. All rights reserved.
# Made by Dario Canoy.
"""Independent Qiskit reference suite for Privi Quantum Evidence Lab.

Uses Qiskit's OWN Statevector.from_instruction as an external software
reference to validate Privi's generated OpenQASM circuit, not QPU hardware.
"""
import numpy as np
import pytest

qiskit = pytest.importorskip("qiskit")
from qiskit import qasm2
from qiskit.quantum_info import Statevector
from privi_quantum.qaoa import Qubo, qaoa_state, to_qasm
from privi_quantum.hardware import parse_qasm, simulate
from privi_quantum.evidence_lab import evaluate


@pytest.mark.parametrize("seed,layers", [
    (1, 1), (2, 2), (3, 3), (4, 4), (7, 2), (11, 3),
])
def test_qiskit_independent_statevector_oracle(seed, layers):
    rng = np.random.default_rng(seed)
    n = 2 + seed % 4
    q = Qubo(rng.uniform(-1, 1, (n, n)), offset=0.5)
    gam = rng.uniform(-2.0, 2.0, layers).tolist()
    bet = rng.uniform(-1.0, 1.0, layers).tolist()
    costs = q.all_costs()
    cmin, span = float(costs.min()), float(costs.max()-costs.min())
    program = to_qasm(q, gam, bet, cmin, span)
    qc = qasm2.loads(program)
    reference = np.abs(Statevector.from_instruction(
        qc.remove_final_measurements(inplace=False)
    ).data)**2
    nq, gates = parse_qasm(program)
    internal = simulate(gates, nq)
    analytical = np.abs(qaoa_state((costs-cmin)/span, gam, bet, n))**2
    report = evaluate(q, gam, bet, qasm=program)
    np.testing.assert_allclose(reference, internal, atol=1e-10, rtol=0)
    np.testing.assert_allclose(reference, analytical, atol=1e-10, rtol=0)
    assert report["verification"]["passed"]


def test_qiskit_bitstring_convention():
    q = Qubo(np.array([[1., 0.], [0., -1.]]))
    report = evaluate(q, [0.5], [0.3], counts={"01":40, "10":60})
    assert report["samples"]["total_shots"] == 100
    assert report["bit_order"] == "q[n-1]...q[0]"
