# Copyright (c) 2026 Privi World Corp. All rights reserved.
# Made by Dario Canoy.
"""Strict recovered IBM input circuit binding; all tests are offline."""
import copy
from types import SimpleNamespace

import pytest
from qiskit import QuantumCircuit
from privi_quantum.evidence_lab import canonical_sha256
from privi_quantum.hardware_evidence import make_hardware_evidence
from privi_quantum.ibm_input_binding import bind_existing_ibm_job
from privi_quantum.qaoa import ProblemError, Qubo, to_qasm


def inputs():
    q=Qubo([[1.,-.4],[-.4,-.7]])
    cs=q.all_costs()
    qasm=to_qasm(q,[.7],[.5],float(cs.min()),float(cs.max()-cs.min()))
    receipt=make_hardware_evidence(
        qubo=q,gammas=[.7],betas=[.5],
        source_qasm=qasm,compiled_qasm=qasm,
        counts={"00":5,"01":7,"10":8},provider="IBM-Quantum",
        backend="ibm_fake_2q",provider_job_id="synthetic-123",
        submitted_utc="2026-11-20T11:00:00Z",
        completed_utc="2026-11-20T11:05:00Z",shots=20)
    return receipt,qasm


class Register:
    def get_counts(self):
        return {"00":5,"01":7,"10":8}


class ExistingJob:
    program_id="sampler"
    def __init__(self, circuit, *, pubs=None):
        self.circuit=circuit
        self._pubs=pubs
    def job_id(self): return "synthetic-123"
    def backend(self): return SimpleNamespace(name="ibm_fake_2q")
    def status(self): return "DONE"
    def result(self):
        return [SimpleNamespace(data=SimpleNamespace(c=Register()))]
    @property
    def inputs(self):
        return {"pubs":[(self.circuit,)]} if self._pubs is None else self._pubs


class ReadOnlyService:
    def __init__(self, job):
        self.existing=job
        self.calls=[]
    def job(self, job_id):
        self.calls.append(job_id)
        return self.existing


def test_bind_original_compiled_circuit_from_existing_job():
    receipt,qasm=inputs()
    service=ReadOnlyService(ExistingJob(QuantumCircuit.from_qasm_str(qasm)))
    output=bind_existing_ibm_job(receipt,compiled_qasm=qasm,service=service)
    assert output["retrieved_input_circuit_matches_declared"]
    assert not output["provider_signed_attestation"]
    assert not output["physical_qpu_execution_verified"]
    assert output["receipt_sha256"]==receipt["content_sha256"]
    assert output["content_sha256"]==canonical_sha256(
        {k:v for k,v in output.items() if k!="content_sha256"})
    assert service.calls==["synthetic-123","synthetic-123"]


def test_reject_tampered_qasm_before_readback():
    receipt,qasm=inputs()
    service=ReadOnlyService(ExistingJob(QuantumCircuit.from_qasm_str(qasm)))
    with pytest.raises(ProblemError, match="digest mismatch"):
        bind_existing_ibm_job(receipt,compiled_qasm=qasm+"\n//changed",service=service)
    assert service.calls==[]


def test_valid_but_altered_input_rejected():
    receipt,qasm=inputs()
    wrong=QuantumCircuit.from_qasm_str(qasm)
    wrong.x(0)
    service=ReadOnlyService(ExistingJob(wrong))
    with pytest.raises(ProblemError,match="differs"):
        bind_existing_ibm_job(receipt,compiled_qasm=qasm,service=service)


def test_changed_gate_angle_rejected():
    receipt,qasm=inputs()
    wrong=QuantumCircuit.from_qasm_str(qasm)
    for instruction in wrong.data:
        if instruction.operation.name=="rz":
            instruction.operation.params[0]=float(instruction.operation.params[0])+.2
            break
    with pytest.raises(ProblemError,match="differs"):
        bind_existing_ibm_job(receipt,compiled_qasm=qasm,
                              service=ReadOnlyService(ExistingJob(wrong)))


@pytest.mark.parametrize("pubs",[
    {}, {"pubs":[]}, {"pubs":[("not a circuit",)]},
    {"pubs":[(1,),(2,)]},
])
def test_missing_or_ambiguous_input_fails_closed(pubs):
    receipt,qasm=inputs()
    service=ReadOnlyService(ExistingJob(QuantumCircuit.from_qasm_str(qasm),pubs=pubs))
    with pytest.raises(ProblemError):
        bind_existing_ibm_job(receipt,compiled_qasm=qasm,service=service)


def test_modified_receipt_rejected_before_input_retrieval():
    receipt,qasm=inputs()
    receipt["shots"]=99
    service=ReadOnlyService(ExistingJob(QuantumCircuit.from_qasm_str(qasm)))
    with pytest.raises(ProblemError,match="hash mismatch"):
        bind_existing_ibm_job(receipt,compiled_qasm=qasm,service=service)
    assert service.calls==[]
