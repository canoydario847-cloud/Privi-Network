# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Quantum - https://priviflow.us - dariocanoy@priviflow.us
"""Bring-your-own Qiskit / OpenQASM circuits, and the Privi Quantum Leaderboard."""
import math

import anyio
import numpy as np
import pytest
from mcp import Client

from privi_quantum import circuits
from privi_quantum.attest import Attestor
from privi_quantum.hardware import HardwareRouter, IonQBackend, LocalBackend, parse_qasm, simulate
from privi_quantum.server import Settings, build_server, http_app
from test_mandates import FakeIonQCloud

BELL2 = """OPENQASM 2.0;
include "qelib1.inc";
qreg q[2];
creg c[2];
h q[0];
cx q[0],q[1];
measure q[0] -> c[0];
measure q[1] -> c[1];
"""
# what qiskit.qasm3.dumps writes for a GHZ circuit with measure_all()
GHZ3 = """OPENQASM 3.0;
include "stdgates.inc";
bit[3] meas;
qubit[3] q;
h q[0];
cx q[0], q[1];
cx q[1], q[2];
barrier q[0], q[1], q[2];
meas[0] = measure q[0];
meas[1] = measure q[1];
meas[2] = measure q[2];
"""

# reference matrices (Qiskit conventions); control is the first listed qubit
X = np.array([[0, 1], [1, 0]]); Y = np.array([[0, -1j], [1j, 0]]); Z = np.diag([1, -1])
H = np.array([[1, 1], [1, -1]]) / math.sqrt(2)
rx = lambda t: np.array([[math.cos(t / 2), -1j * math.sin(t / 2)], [-1j * math.sin(t / 2), math.cos(t / 2)]])
ry = lambda t: np.array([[math.cos(t / 2), -math.sin(t / 2)], [math.sin(t / 2), math.cos(t / 2)]])
rz = lambda t: np.diag([np.exp(-1j * t / 2), np.exp(1j * t / 2)])
ph = lambda l: np.diag([1, np.exp(1j * l)])
u3 = lambda t, p, l: np.array([[math.cos(t / 2), -np.exp(1j * l) * math.sin(t / 2)],
                               [np.exp(1j * p) * math.sin(t / 2), np.exp(1j * (p + l)) * math.cos(t / 2)]])
SX = np.array([[1 + 1j, 1 - 1j], [1 - 1j, 1 + 1j]]) / 2


def ctrl(U):
    M = np.eye(4, dtype=complex)
    M[2:, 2:] = U
    return M


CCX = np.eye(8, dtype=complex)
CCX[6:, 6:] = X
REF = {"x": X, "y": Y, "z": Z, "h": H, "s": ph(math.pi / 2), "sdg": ph(-math.pi / 2), "t": ph(math.pi / 4),
       "tdg": ph(-math.pi / 4), "sx": SX, "sxdg": SX.conj().T, "rx": rx, "ry": ry, "rz": rz, "p": ph, "u1": ph,
       "u2": lambda p, l: u3(math.pi / 2, p, l), "u3": u3, "u": u3, "cx": ctrl(X), "cy": ctrl(Y), "cz": ctrl(Z),
       "ch": ctrl(H), "swap": np.array([[1, 0, 0, 0], [0, 0, 1, 0], [0, 1, 0, 0], [0, 0, 0, 1]]),
       "crx": lambda t: ctrl(rx(t)), "cry": lambda t: ctrl(ry(t)), "crz": lambda t: ctrl(rz(t)), "cp": lambda l: ctrl(ph(l)),
       "rzz": lambda t: np.diag(np.exp(1j * t / 2 * np.array([-1, 1, 1, -1]))),
       "rxx": lambda t: math.cos(t / 2) * np.eye(4) - 1j * math.sin(t / 2) * np.kron(X, X),
       "ryy": lambda t: math.cos(t / 2) * np.eye(4) - 1j * math.sin(t / 2) * np.kron(Y, Y), "ccx": CCX}


def apply(st, U, qs, n):
    k, axes = len(qs), [n - 1 - q for q in qs]
    psi = np.moveaxis(st.reshape([2] * n), axes, list(range(k)))
    shape = psi.shape
    psi = (U @ psi.reshape(2 ** k, -1)).reshape(shape)
    return np.moveaxis(psi, list(range(k)), axes).reshape(-1)


def run_basis(gates, n, st=None):
    if st is None:
        st = np.zeros(2 ** n, complex)
        st[0] = 1
    for g in gates:
        U = H if g[0] == "h" else rz(g[2]) if g[0] == "rz" else rx(g[2]) if g[0] == "rx" else ctrl(X)
        st = apply(st, U, list(g[1:3]) if g[0] == "cx" else [g[1]], n)
    return st


@pytest.mark.parametrize("name", sorted(REF))
def test_every_gate_rewrite_is_exact_up_to_global_phase(name):
    rng = np.random.default_rng(abs(hash(name)) % 2 ** 32)
    n_par, n_q, expand = circuits.GATES[name]
    for _ in range(3):
        qs = [int(q) for q in rng.permutation(3)[:n_q]]
        ang = [float(a) for a in rng.uniform(-3, 3, n_par)]
        prep = [("h", q) for q in range(3)] + [("rx", q, float(rng.uniform(-3, 3))) for q in range(3)] + \
               [("rz", q, float(rng.uniform(-3, 3))) for q in range(3)]
        start = run_basis(prep, 3)
        U = REF[name](*ang) if n_par else REF[name]
        assert abs(abs(np.vdot(apply(start, U, qs, 3), run_basis(expand(*ang, *qs), 3, start))) - 1) < 1e-9


def test_parse_qiskit_qasm2_and_qasm3():
    b = circuits.parse(BELL2)
    assert b["qubits"] == 2 and b["version"] == "2.0" and b["source_gates"] == 2
    g = circuits.parse(GHZ3)
    assert g["qubits"] == 3 and g["version"] == "3.0" and len(g["gates"]) == 3
    # register broadcast, two registers, comments, angle expressions, qasm3 single qubits
    c = circuits.parse("OPENQASM 2.0; qreg a[2]; qreg b[1]; creg c[3]; // note\n h a; u3(pi/2, -pi/4, 2*pi) b[0];"
                       " rzz(0.5) a[1], b[0]; /* block */ measure a -> c;")
    assert c["qubits"] == 3 and c["registers"] == {"a": 2, "b": 1} and c["source_gates"] == 4
    q3 = circuits.parse("OPENQASM 3.0; qubit x; qubit y; cx x, y; bit[2] r; r = measure {x, y};".replace("{x, y}", "x"))
    assert q3["qubits"] == 2
    p = circuits.parse("OPENQASM 2.0; qreg q[1]; rz(-3*pi/4 + 0.25) q[0];")
    assert p["gates"][0][2] == pytest.approx(-3 * math.pi / 4 + 0.25)
    # the rewritten text is what every Privi backend reads
    n, gates = parse_qasm(circuits.to_basis_qasm(c["qubits"], c["gates"]))
    assert n == 3 and len(gates) == len(c["gates"])


@pytest.mark.parametrize("src,msg", [
    ("OPENQASM 2.0; qreg q[1]; reset q[0];", "reset"),
    ("OPENQASM 2.0; gate foo a { h a; } qreg q[1]; foo q[0];", "custom gate"),
    ("OPENQASM 2.0; qreg q[2]; mystery q[0];", "not supported"),
    ("OPENQASM 2.0; qreg q[1]; rx(__import__) q[0];", "cannot read angle"),
    ("OPENQASM 2.0; qreg q[1]; h q[3];", "outside register"),
    ("OPENQASM 2.0; qreg q[2]; cx q[0], q[0];", "same qubit"),
    ("OPENQASM 2.0; qreg q[40];", "more than"),
    ("OPENQASM 3.0; qubit[2] q; ctrl @ x q[0], q[1];", "modifiers"),
    ("OPENQASM 2.0; creg c[1];", "no qubits"),
    ("", "OpenQASM text"),
])
def test_parse_refusals(src, msg):
    with pytest.raises(circuits.CircuitError, match=msg):
        circuits.parse(src)


def test_run_circuits_seal_and_leaderboard(tmp_path):
    from starlette.testclient import TestClient
    db = str(tmp_path / "c.db")
    cloud = FakeIonQCloud()
    router = HardwareRouter(db, [LocalBackend(), IonQBackend("k123", "simulator", None, opener=cloud),
                                 IonQBackend("k123", "qpu.forte-1", {"per_task": 0.3, "per_shot": 0.01}, opener=cloud)],
                            daily_budget_usd=50)
    srv = build_server(Settings(db_path=db, rate_per_min=1000), Attestor(db), None, None, router)

    async def go():
        async with Client(srv) as c:
            bell = (await c.call_tool("quantum_run_circuit", {"qasm": BELL2, "backend": "local", "shots": 400, "label": "bell"})).structured_content
            assert bell["status"] == "done" and set(bell["counts"]) <= {"00", "11"} and sum(bell["counts"].values()) == 400
            assert bell["circuit"]["qubits"] == 2 and bell["attestation"]["id"].startswith("qa_")
            # X on qubit 0 only: Qiskit prints qubit 0 on the right
            one = (await c.call_tool("quantum_run_circuit", {"qasm": "OPENQASM 2.0; qreg q[3]; x q[0];", "backend": "local"})).structured_content
            assert one["counts"] == {"001": 1000}
            # free provider simulator (IonQ cloud) runs without a mandate and is sealed once done
            ghz = (await c.call_tool("quantum_run_circuit", {"qasm": GHZ3, "backend": "ionq:simulator", "shots": 100})).structured_content
            assert ghz["status"] == "queued"
            for _ in range(2):
                ghz = (await c.call_tool("quantum_hardware_job", {"job_id": ghz["job_id"]})).structured_content
            assert ghz["status"] == "done" and set(ghz["counts"]) == {"000", "111"}
            # a paid QPU needs a Quantum Mandate
            paid = await c.call_tool("quantum_run_circuit", {"qasm": BELL2, "backend": "ionq:qpu.forte-1", "shots": 100})
            assert paid.is_error and "Quantum Mandate" in paid.structured_content["error"]
            bad = await c.call_tool("quantum_run_circuit", {"qasm": "OPENQASM 2.0; qreg q[1]; reset q[0];"})
            assert bad.is_error and "reset" in bad.structured_content["error"]
            big = await c.call_tool("quantum_run_circuit", {"qasm": "OPENQASM 2.0; qreg q[25]; h q;", "backend": "local"})
            assert big.is_error and "local simulator runs up to" in big.structured_content["error"]
            for _ in range(3):
                await c.call_tool("quantum_advantage_receipt", {"problem": "balance_lines",
                                                                "data": {"jobs": [{"name": n, "minutes": m} for n, m in zip("ABCD", [3, 5, 7, 2])]}})
            lb = (await c.call_tool("quantum_leaderboard", {})).structured_content
            return bell, lb
    bell, lb = anyio.run(go)
    sealed = Attestor(db).get(bell["attestation"]["id"])
    assert sealed["body"]["kind"] == "quantum_circuit_run" and sealed["body"]["label"] == "bell"
    assert sealed["body"]["bit_order"].startswith("Qiskit order")

    rows = {r["backend"]: r for r in lb["backends"]}
    assert rows["local"]["ranked"] and rows["local"]["rank"] == 1 and rows["local"]["receipts"] == 3
    assert rows["local"]["circuit_runs"] == 2 and rows["local"]["optimum_rate"] is not None
    assert rows["ionq:simulator"]["completed"] == 1 and not rows["ionq:simulator"]["ranked"]
    assert rows["ionq:qpu.forte-1"]["measured_runs"] == 0 and rows["ionq:qpu.forte-1"]["rank"] is None
    assert sum(lb["quantum_vs_classical"].values()) == 3
    with TestClient(http_app(srv)) as http:
        j = http.get("/leaderboard.json")
        assert j.headers["access-control-allow-origin"] == "*" and j.json()["backends"][0]["backend"] == "local"
        page = http.get("/leaderboard").text
        assert "Which quantum computer actually delivers?" in page and "IonQ" in page and "not connected" not in page
        assert "<script" not in page
