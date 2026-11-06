# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Quantum - https://priviflow.us - dariocanoy@priviflow.us
"""v0.11 Privi Kingston: calibration-pinned layouts, error suppression, readout mitigation, Open Plan guard on IBM."""
import sqlite3
import sys
import types
from types import SimpleNamespace as NS

import anyio
import numpy as np
import pytest
from mcp import Client

from privi_quantum import kingston
from privi_quantum.attest import Attestor
from privi_quantum.hardware import HardwareError, HardwareRouter, IBMBackend, LocalBackend, parse_qasm
from privi_quantum.server import Settings, build_server

# A 10-qubit heavy-hex-like patch: a line 0-1-2-3-4-5-6 with 7 on 3 and 8-9 on 5.
# Qubit 2 has terrible readout and coupler 4-5 is bad, so good layouts avoid them.
EDGES = {(0, 1): 0.004, (1, 2): 0.003, (2, 3): 0.003, (3, 4): 0.005, (4, 5): 0.09, (5, 6): 0.004,
         (3, 7): 0.002, (5, 8): 0.003, (8, 9): 0.002}
RO = [0.010, 0.012, 0.30, 0.008, 0.015, 0.009, 0.011, 0.006, 0.007, 0.005]


class FakeTarget:
    def __init__(self):
        self.num_qubits = len(RO)
        self.operation_names = ["measure", "cz", "sx", "x", "rz"]
        self.qubit_properties = [NS(t1=250e-6 + q * 1e-6, t2=150e-6) for q in range(len(RO))]

    def __getitem__(self, name):
        if name == "measure":
            return {(q,): NS(error=e, duration=1e-6) for q, e in enumerate(RO)}
        if name == "cz":
            out = {}
            for (a, b), e in EDGES.items():
                out[(a, b)] = NS(error=e)
                out[(b, a)] = NS(error=e)
            return out
        raise KeyError(name)


class FakeBackend:
    name = "ibm_kingston"

    def __init__(self):
        self.target = FakeTarget()

    def properties(self):
        raise RuntimeError("no BackendProperties on this SDK")

    def status(self):
        return NS(operational=True, pending_jobs=7, status_msg="active")


def snap():
    return kingston.snapshot_from_backend(FakeBackend())


# ------------------------------------------------------------------ calibration + layout

def test_snapshot_and_hash():
    s = snap()
    assert s["two_qubit_gate"] == "cz" and s["num_qubits"] == 10 and len(s["edges"]) == len(EDGES)
    assert s["qubits"]["2"]["readout_error"] == 0.30 and s["qubits"]["0"]["t1_us"] == 250.0
    assert s["qubits"]["0"]["p01"] == s["qubits"]["0"]["p10"] == 0.010  # symmetric when properties are missing
    s2 = snap()
    assert kingston.calibration_sha256(s) == kingston.calibration_sha256(s2)   # read time is not hashed
    s2["edges"][0][2] = 0.5
    assert kingston.calibration_sha256(s) != kingston.calibration_sha256(s2)
    sm = kingston.summary(s)
    assert sm["usable_qubits"] == 9 and 2 not in sm["best_qubits_by_readout"]


def test_best_layout_avoids_bad_qubits_and_couplers():
    s = snap()
    for n in (2, 3, 4):
        lay = kingston.best_layout(s, n)
        q = lay["physical_qubits"]
        assert len(q) == n == len(set(q)) and 2 not in q
        assert all(tuple(sorted(c)) in EDGES for c in lay["couplers"])    # connected on the chip
        assert [4, 5] not in [sorted(c) for c in lay["couplers"]]
        assert 0 < lay["estimated_fidelity"] < 1
    assert kingston.best_layout(s, 2)["physical_qubits"] in ([8, 9], [9, 8])
    assert kingston.best_layout(s, 11) is None
    assert kingston.best_layout(s, 1)["physical_qubits"] == [9]


# ------------------------------------------------------------------ readout mitigation

def _noisy(probs, readout, shots, rng):
    """Sample ideal outcomes, then flip each bit with the qubit's readout error."""
    n = len(readout)
    ks = rng.choice(len(probs), size=shots, p=probs)
    out = {}
    for k in ks:
        m = 0
        for i, r in enumerate(readout):
            b = (k >> i) & 1
            flip = rng.random() < (r["p01"] if b == 0 else r["p10"])
            m |= (b ^ flip) << i
        out[m] = out.get(m, 0) + 1
    return out


def test_mitigation_recovers_bell_and_ghz():
    rng = np.random.default_rng(7)
    ro = [{"physical": 0, "p01": 0.04, "p10": 0.08}, {"physical": 1, "p01": 0.03, "p10": 0.07},
          {"physical": 3, "p01": 0.05, "p10": 0.06}]
    ghz = np.zeros(8)
    ghz[0] = ghz[7] = 0.5
    raw = _noisy(ghz, ro, 40000, rng)
    raw_good = (raw.get(0, 0) + raw.get(7, 0)) / 40000
    m = kingston.mitigate_readout(raw, ro)
    good = m["probabilities"].get(0, 0) + m["probabilities"].get(7, 0)
    assert raw_good < 0.86 and good > 0.97 and abs(sum(m["probabilities"].values()) - 1) < 1e-6
    assert all(p >= 0 for p in m["probabilities"].values())
    c = kingston.as_counts(m["probabilities"], 1000)
    assert abs(sum(c.values()) - 1000) <= 8
    assert kingston.mitigate_readout(raw, [{"p01": None, "p10": 0.1}] * 3) is None
    assert kingston.mitigate_readout({}, ro) is None


# ------------------------------------------------------------------ Open Plan guard

def test_open_plan_meter():
    db = sqlite3.connect(":memory:", check_same_thread=False)
    m = kingston.OpenPlanMeter(db, budget_s=20, window_days=28, reserve_s=5)
    ok, why, est = m.check(1000)
    assert ok and est == 2.5
    m.reserve("j1", "ibm:ibm_kingston", est)
    m.settle("j1", 3.0, "done")                       # IBM's billed seconds replace the estimate
    m.reserve("j2", "ibm:ibm_kingston", 2.5)
    m.settle("j2", None, "failed")                    # failed with no usage: reservation freed
    assert m.used_s() == 3.0 and m.remaining_s() == 17.0
    ok, why, _ = m.check(30000)                       # 17s needed, 12s usable after the reserve
    assert not ok and "Open Plan guard" in why
    m.sync(6.0, 600, 594)                             # IBM says less is left than we think: trust IBM
    assert m.remaining_s() == 6.0 and not m.check(1000)[0]
    assert m.view()["ibm_reported"]["remaining_s"] == 6.0
    assert kingston.parse_service_usage({"usage_remaining_seconds": 412, "usage_limit_seconds": 600}) == \
        {"remaining_s": 412.0, "limit_s": 600.0, "consumed_s": None}


# ------------------------------------------------------------------ IBM backend end to end (fake qiskit)

class FakeRuntime:
    """Stands in for qiskit + qiskit_ibm_runtime: records what Privi sends and returns noisy counts."""

    def __init__(self, readout_flip=0.06):
        self.pm_kwargs, self.sampler_opts, self.runs, self.jobs = [], [], [], {}
        self.flip = readout_flip
        self.backend = FakeBackend()
        rt = self

        class QC:
            def __init__(self, qasm):
                self.n, self.gates = parse_qasm(qasm)

            @classmethod
            def from_qasm_str(cls, s):
                return cls(s)

        class ISA:
            def __init__(self, qc, layout):
                self.qc, self.layout_list = qc, layout
                self.layout = NS(final_index_layout=lambda: list(layout) if layout else list(range(qc.n)))
                self.data = []

            def depth(self):
                return 4 + len(self.qc.gates)

            def count_ops(self):
                return {"cz": sum(g[0] == "cx" for g in self.qc.gates), "sx": 3, "rz": 5, "measure": self.qc.n}

        def gppm(**kw):
            rt.pm_kwargs.append(kw)
            return NS(run=lambda qc: ISA(qc, kw.get("initial_layout")))

        class Sampler:
            def __init__(self, mode):
                self.options = NS(dynamical_decoupling=NS(enable=False, sequence_type=None),
                                  twirling=NS(enable_gates=False, enable_measure=False))
                rt.sampler_opts.append(self.options)

            def run(self, pubs, shots):
                isa = pubs[0]
                jid = f"ibmjob{len(rt.jobs)}"
                rt.jobs[jid] = (isa, shots)
                rt.runs.append({"shots": shots, "layout": isa.layout_list})
                return NS(job_id=lambda: jid)

        self.modules = {
            "qiskit": types.ModuleType("qiskit"),
            "qiskit.transpiler": types.ModuleType("qiskit.transpiler"),
            "qiskit.transpiler.preset_passmanagers": types.ModuleType("qiskit.transpiler.preset_passmanagers"),
            "qiskit_ibm_runtime": types.ModuleType("qiskit_ibm_runtime"),
        }
        self.modules["qiskit"].QuantumCircuit = QC
        self.modules["qiskit.transpiler.preset_passmanagers"].generate_preset_pass_manager = gppm
        self.modules["qiskit_ibm_runtime"].SamplerV2 = Sampler

    def service(self):
        rt = self

        class Job:
            def __init__(self, jid):
                self.jid = jid

            def status(self):
                return "JobStatus.DONE"

            def usage(self):
                return 2.0

            def error_message(self):
                return ""

            def result(self):
                from privi_quantum.hardware import simulate
                isa, shots = rt.jobs[self.jid]
                p = simulate(isa.qc.gates, isa.qc.n)
                rng = np.random.default_rng(3)
                ro = [{"p01": rt.flip, "p10": rt.flip}] * isa.qc.n
                counts = _noisy(p, ro, shots, rng)
                bits = {format(k, f"0{isa.qc.n}b"): c for k, c in counts.items()}   # IBM prints c[n-1]..c[0]
                return [NS(data=NS(c=NS(get_counts=lambda: bits)))]

        return NS(backend=lambda name: rt.backend, job=lambda jid: Job(jid),
                  usage=lambda: {"usage_remaining_seconds": 590.0, "usage_limit_seconds": 600.0})


BELL = """OPENQASM 2.0;
include "qelib1.inc";
qreg q[2];
creg c[2];
h q[0];
cx q[0],q[1];
measure q -> c;
"""


@pytest.fixture
def runtime(monkeypatch):
    rt = FakeRuntime()
    for k, v in rt.modules.items():
        monkeypatch.setitem(sys.modules, k, v)
    return rt


def ibm(rt, **kw):
    return IBMBackend("tok", "", "ibm_kingston", {"per_task": 0, "per_shot": 0}, service_factory=rt.service, **kw)


def test_ibm_submit_pins_layout_and_suppresses(runtime, tmp_path):
    b = ibm(runtime)
    router = HardwareRouter(str(tmp_path / "k.db"), [LocalBackend(), b])
    sub = router.submit("circuit", {}, BELL, 1000, 0, {}, "ibm:ibm_kingston")
    kw = runtime.pm_kwargs[-1]
    assert kw["optimization_level"] == 3 and sorted(kw["initial_layout"]) == [8, 9]
    o = runtime.sampler_opts[-1]
    assert o.dynamical_decoupling.enable and o.dynamical_decoupling.sequence_type == "XY4"
    assert o.twirling.enable_gates and o.twirling.enable_measure
    d = sub["device"]
    assert d["calibration"]["sha256"] == kingston.calibration_sha256(snap()) and d["measured_on"] == kw["initial_layout"]
    assert len(d["readout"]) == 2 and d["qpu_seconds_estimate"] == 2.502
    j = router.refresh(sub["job_id"])
    assert j["status"] == "done" and j["device"]["quantum_seconds"] == 2.0 and j["device"]["layout"]
    assert b.meter.used_s() == 2.0
    off = ibm(runtime, suppression=False)
    off.submit(BELL, 2, [], 100, "x")
    assert not runtime.sampler_opts[-1].dynamical_decoupling.enable


def test_open_plan_guard_blocks_before_submit(runtime, tmp_path):
    b = ibm(runtime, open_plan_seconds=10, reserve_seconds=5)
    router = HardwareRouter(str(tmp_path / "g.db"), [LocalBackend(), b])
    with pytest.raises(HardwareError, match="Open Plan guard"):
        router.choose("ibm:ibm_kingston", "cheapest", 10000, None)
    assert not runtime.runs                          # nothing reached IBM
    d = {x["id"]: x for x in router.directory(10000)}
    assert not d["ibm:ibm_kingston"]["usable_now"] and "Open Plan" in d["ibm:ibm_kingston"]["money_guard"]
    assert router.choose("auto", "cheapest", 10000, None)[0].id == "local"   # auto routing falls back


class FakeAnchor:
    def anchor(self, hashes, label):
        return {"status": "confirmed", "tx_hash": "0x" + "ab" * 32, "merkle_root": "00" * 32, "chain_id": 8453,
                "receipts": [{"hash": h, "proof": []} for h in hashes]}

    def verify(self, *a):
        return {"verified": True}


def test_mcp_kingston_status_and_sealed_device_record(runtime, tmp_path, monkeypatch):
    monkeypatch.setitem(globals(), "RO", [0.06] * 10)   # calibration = the fake device's real readout flips
    from starlette.testclient import TestClient
    db = str(tmp_path / "m.db")
    att = Attestor(db)
    router = HardwareRouter(db, [LocalBackend(), ibm(runtime)])
    server = build_server(Settings(db_path=db), att, FakeAnchor(), None, router)
    jobs = {"jobs": [{"name": f"J{i}", "minutes": m} for i, m in enumerate([42, 17, 33, 8, 25, 61])]}

    async def go():
        async with Client(server) as c:
            st = (await c.call_tool("quantum_ibm_kingston", {"qubits": 5})).structured_content
            assert st["backend"] == "ibm:ibm_kingston" and st["queue"]["pending_jobs"] == 7
            assert st["calibration"]["two_qubit_gate"] == "cz" and {x["qubits"] for x in st["best_layouts"]} >= {2, 5}
            assert st["open_plan"]["ibm_reported"]["remaining_s"] == 590.0
            j = (await c.call_tool("quantum_run_circuit", {"qasm": BELL, "backend": "ibm:ibm_kingston",
                                                          "shots": 4000})).structured_content
            done = (await c.call_tool("quantum_hardware_job", {"job_id": j["job_id"]})).structured_content
            assert done["status"] == "done" and done["device"]["calibration_sha256"]
            raw = {o["bitstring"]: o["probability"] for o in done["top_outcomes"]}
            mit = {o["bitstring"]: o["probability"] for o in done["mitigated_top_outcomes"]}
            assert mit.get("00", 0) + mit.get("11", 0) > raw.get("00", 0) + raw.get("11", 0) + 0.05
            q = (await c.call_tool("quantum_run_hardware", {"problem": "balance_lines", "data": jobs,
                                                            "backend": "ibm:ibm_kingston", "shots": 2000})).structured_content
            qd = (await c.call_tool("quantum_hardware_job", {"job_id": q["job_id"]})).structured_content
            assert qd["status"] == "done" and qd["device"]["error_suppression"] == ["dynamical_decoupling:XY4",
                                                                                     "twirling:gates+measure"]
            rm = qd["readout_mitigation"]
            assert rm["optimum_frequency_mitigated"] >= rm["optimum_frequency_raw"]
            return done["attestation"]["id"], qd["attestation"]["id"]
    a1, a2 = anyio.run(go)
    for aid in (a1, a2):   # the machine record is inside the signed body
        assert att.get(aid)["body"]["device"]["calibration_sha256"] == kingston.calibration_sha256(snap())
    assert "mitigated_top_outcomes" in att.get(a1)["body"] and "readout_mitigation" in att.get(a2)["body"]
    app = server.streamable_http_app(host="0.0.0.0", stateless_http=True, json_response=True)
    with TestClient(app) as http:
        r = http.get("/ibm/kingston.json")
        assert r.status_code == 200 and r.json()["calibration"]["num_qubits"] == 10


def test_kingston_tool_without_ibm(tmp_path):
    db = str(tmp_path / "n.db")
    server = build_server(Settings(db_path=db), Attestor(db), FakeAnchor(), None, HardwareRouter(db, [LocalBackend()]))

    async def go():
        async with Client(server) as c:
            r = await c.call_tool("quantum_ibm_kingston", {})
            assert r.is_error and "IBM_QUANTUM_TOKEN" in r.structured_content["error"]
    anyio.run(go)
