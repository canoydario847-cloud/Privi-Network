# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Quantum - https://priviflow.us - dariocanoy@priviflow.us
import copy
import re

import anyio
import numpy as np
import pytest
from mcp import Client

from privi_quantum import qaoa
from privi_quantum.anchoring import anchor_pending
from privi_quantum.attest import Attestor
from privi_quantum.server import Settings, build_server

JOBS = {"jobs": [{"name": f"J{i}", "minutes": m} for i, m in enumerate([42, 17, 33, 8, 25, 61, 12, 29, 50, 21])]}


class FakeAnchor:
    def __init__(self):
        self.anchored = {}

    def anchor(self, hashes, label):
        self.anchored.update({h: "0x" + "ab" * 32 for h in hashes})
        return {"status": "confirmed", "tx_hash": "0x" + "ab" * 32, "merkle_root": "00" * 32, "chain_id": 262144,
                "network": "test", "block_number": 7, "block_time": 1,
                "receipts": [{"hash": h, "proof": []} for h in hashes]}

    def verify(self, hash_hex, tx_hash, proof):
        return {"verified": hash_hex in self.anchored, "block_number": 7, "chain_id": 262144}


def _sim_qasm(qasm, n):
    """Independent gate-by-gate simulator used to check the exported circuit."""
    t = np.zeros(2 ** n, complex); t[0] = 1; t = t.reshape([2] * n)
    ax = lambda q: n - 1 - q

    def one(U, q):
        nonlocal t
        t = np.moveaxis(np.tensordot(U, t, axes=([1], [ax(q)])), 0, ax(q))
    for line in qasm.splitlines():
        m = re.match(r"(h|rz|rx|cx)(?:\((.*)\))? q\[(\d+)\](?:,q\[(\d+)\])?;", line)
        if not m:
            continue
        g, a, q1, q2 = m.groups(); q1 = int(q1)
        if g == "h":
            one(np.array([[1, 1], [1, -1]]) / np.sqrt(2), q1)
        elif g == "rz":
            th = float(a); one(np.diag([np.exp(-1j * th / 2), np.exp(1j * th / 2)]), q1)
        elif g == "rx":
            th = float(a); c, s = np.cos(th / 2), -1j * np.sin(th / 2); one(np.array([[c, s], [s, c]]), q1)
        else:
            q2 = int(q2); idx = [slice(None)] * n; idx[ax(q1)] = 1
            rem = [k for k in range(n) if k != ax(q1)]
            t[tuple(idx)] = np.flip(t[tuple(idx)], axis=rem.index(ax(q2))).copy()
    return np.abs(t.reshape(-1)) ** 2


def test_ising_matches_qubo():
    rng = np.random.default_rng(0)
    for n in (1, 2, 5, 8):
        q = qaoa.Qubo(rng.normal(size=(n, n)), 1.5)
        h, J, c = q.ising()
        Z = 1 - 2 * q.bits()
        e = Z @ h + sum(w * Z[:, i] * Z[:, j] for (i, j), w in J.items()) + c
        assert np.allclose(e, q.all_costs())


def test_qasm_reproduces_statevector():
    rng = np.random.default_rng(1)
    q = qaoa.Qubo(rng.normal(size=(5, 5)))
    c = q.all_costs(); cmin, span = c.min(), c.max() - c.min()
    g, b = [0.7, 1.3], [0.4, 0.2]
    direct = np.abs(qaoa.qaoa_state((c - cmin) / span, g, b, 5)) ** 2
    assert np.allclose(direct, _sim_qasm(qaoa.to_qasm(q, g, b, cmin, span), 5), atol=1e-9)


@pytest.mark.parametrize("problem,data", [
    ("balance_lines", JOBS),
    ("select_lots", {"lots": [{"name": f"L{i}", "risk": r} for i, r in enumerate([0.9, 0.2, 0.75, 0.4, 0.85, 0.1])],
                     "k": 2, "linked": [["L0", "L4"]]}),
    ("split_conflicts", {"items": list("ABCDEF"), "conflicts": [
        {"a": "A", "b": "B", "weight": 3}, {"a": "B", "b": "C"}, {"a": "C", "b": "D", "weight": 2},
        {"a": "D", "b": "E"}, {"a": "E", "b": "F", "weight": 2}, {"a": "F", "b": "A"}]}),
])
def test_templates_reach_the_optimum(problem, data):
    qubo, decode = qaoa.build(problem, data)
    r = qaoa.solve(qubo, layers=2, seed=3)
    assert r["found_optimum"] and r["approximation_ratio"] == 1.0
    assert r["probability_of_optimum"] > r["random_guess_probability_of_optimum"]
    d = decode(r["solution"])
    if problem == "select_lots":
        assert d["meets_k"] and d["linked_pairs_both_chosen"] == [] and set(d["inspect"]) == {"L0", "L2"}
    if problem == "balance_lines":
        assert d["imbalance_minutes"] == 0.0


def test_bad_input_is_rejected():
    for problem, data in [("nope", {}), ("balance_lines", {"jobs": [{"minutes": 1}]}),
                          ("balance_lines", {"jobs": [{"minutes": 1}] * 17}),
                          ("qubo", {"Q": [[1, 2], [3]]}), ("qubo", {"Q": [[float("nan")]]}),
                          ("select_lots", {"lots": [{"risk": 1}, {"risk": 2}], "k": 5})]:
        with pytest.raises(qaoa.ProblemError):
            qaoa.build(problem, data)


def test_attestation_signatures_and_tamper(tmp_path):
    a = Attestor(str(tmp_path / "q.db"))
    k = a.public_keys()
    att = a.issue("t", {"x": 1})
    assert Attestor.verify(att, k["ed25519"], k["ml_dsa_87"])["valid"]
    bad = copy.deepcopy(att); bad["body"]["x"] = 2
    assert not Attestor.verify(bad, k["ed25519"], k["ml_dsa_87"])["valid"]
    half = copy.deepcopy(att); half["signatures"]["ml_dsa_87"] = att["signatures"]["ed25519"]
    v = Attestor.verify(half, k["ed25519"], k["ml_dsa_87"])
    assert v["ed25519_valid"] and not v["ml_dsa_87_valid"] and not v["valid"]
    assert Attestor(str(tmp_path / "q.db")).key_id == a.key_id  # key survives restart


def test_mcp_end_to_end(tmp_path):
    anchor = FakeAnchor()
    attestor = Attestor(str(tmp_path / "q.db"))

    async def go():
        async with Client(build_server(Settings(db_path=str(tmp_path / "q.db")), attestor, anchor)) as c:
            st = (await c.call_tool("quantum_status", {})).structured_content
            assert st["max_qubits"] == qaoa.MAX_QUBITS and st["anchoring"]["enabled"]
            pr = (await c.call_tool("quantum_problems", {})).structured_content
            assert "balance_lines" in pr["problems"]
            r = (await c.call_tool("quantum_optimize", {"problem": "balance_lines", "data": JOBS,
                                                        "include_qasm": True})).structured_content
            assert r["quality"]["found_optimum"] and r["openqasm"].startswith("OPENQASM 2.0;")
            aid = r["attestation"]["id"]
            v = (await c.call_tool("quantum_verify", {"attestation_id": aid})).structured_content
            assert v["valid"] and v["anchor"]["verified"] is False
            assert anchor_pending(attestor, anchor) == 1
            v = (await c.call_tool("quantum_verify", {"attestation_id": aid})).structured_content
            assert v["valid"] and v["anchor"]["verified"] is True
            forged = attestor.get(aid); forged["body"]["decision"]["imbalance_minutes"] = 99
            v = (await c.call_tool("quantum_verify", {"attestation": forged})).structured_content
            assert not v["valid"]
            s = (await c.call_tool("pqc_scan_code", {"code": "k = rsa.generate_private_key(public_exponent=65537, key_size=2048)"})).structured_content
            assert s["counts"]["HIGH"] == 1 and s["readiness_score"] < 100
            e = await c.call_tool("quantum_optimize", {"problem": "qubo", "data": {"Q": [[0] * 17] * 17}})
            assert e.is_error
    anyio.run(go)
