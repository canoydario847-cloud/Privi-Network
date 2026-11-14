# Copyright (c) 2026 Privi World Corp.
import time
import pytest
from privi_quantum.cloud import QuantumCloud, auth, MAX_QUBITS

BELL = """OPENQASM 2.0;
include "qelib1.inc";
qreg q[2];
creg c[2];
h q[0];
cx q[0],q[1];
measure q[0] -> c[0];
measure q[1] -> c[1];
"""

def test_bell_cloud_job_completes_and_persists(tmp_path):
    db = str(tmp_path / "jobs.db")
    q = QuantumCloud(db)
    job = q.submit("owner-one", BELL, 1000)
    assert job["physical_qpu"] is False
    assert q.get(job["job_id"], "owner-two") is None
    for _ in range(200):
        result = q.get(job["job_id"], "owner-one")
        if result["status"] in ("completed", "failed"):
            break
        time.sleep(.02)
    assert result["status"] == "completed", result
    counts = result["result"]["counts"]
    assert sum(counts.values()) == 1000
    assert set(counts).issubset({"00", "11"})
    assert q.get(job["job_id"], "owner-one")["status"] == "completed"
    q.pool.shutdown(wait=True)
    q2 = QuantumCloud(db)
    assert q2.get(job["job_id"], "owner-one")["status"] == "completed"
    q2.pool.shutdown(wait=True)

def test_limits_and_invalid_input(tmp_path):
    q = QuantumCloud(str(tmp_path / "jobs.db"))
    with pytest.raises(ValueError):
        q.submit("owner", BELL, 4097)
    with pytest.raises(ValueError):
        q.submit("owner", BELL, True)
    with pytest.raises(ValueError):
        q.submit("owner", "", 100)
    with pytest.raises(ValueError):
        q.submit("owner", "OPENQASM 2.0; qreg q[15];", 100)
    assert MAX_QUBITS == 12
    q.pool.shutdown(wait=True)

def test_auth_disabled_and_tenant_isolation(monkeypatch):
    class Req:
        def __init__(self, header):
            self.headers = {"authorization": header}
    monkeypatch.delenv("QUANTUM_CLOUD_API_KEYS", raising=False)
    assert auth(Req("Bearer leaked")) == (None, 503)
    monkeypatch.setenv("QUANTUM_CLOUD_API_KEYS", "key-one,key-two")
    assert auth(Req("Bearer wrong")) == (None, 401)
    first, code = auth(Req("Bearer key-one"))
    second, code2 = auth(Req("Bearer key-two"))
    assert code == code2 == 200 and first != second
