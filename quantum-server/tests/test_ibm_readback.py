# Copyright (c) 2026 Privi World Corp. All rights reserved.
# Made by Dario Canoy.
"""Offline readback tests. Fake authenticated service has no submit or run."""
from types import SimpleNamespace
import copy
import pytest
import numpy as np
from privi_quantum.evidence_lab import canonical_sha256
from privi_quantum.ibm_readback import verify_ibm_readback
from privi_quantum.hardware_evidence import make_hardware_evidence
from privi_quantum.qaoa import Qubo, ProblemError, to_qasm


def fixture():
    q=Qubo(np.array([[1.0,-.4],[-.4,-.7]]))
    costs=q.all_costs()
    source=to_qasm(q,[.7],[.5],float(costs.min()),float(costs.max()-costs.min()))
    return make_hardware_evidence(
        qubo=q,gammas=[.7],betas=[.5],source_qasm=source,compiled_qasm=source,
        counts={"00":5,"01":7,"10":8},provider="IBM-Quantum",
        backend="ibm_fake_2q",provider_job_id="synthetic-123",
        submitted_utc="2026-11-20T11:00:00Z",
        completed_utc="2026-11-20T11:05:00Z",shots=20)


class MockRegister:
    def __init__(self,counts):
        self.counts=counts
    def get_counts(self):
        return self.counts


class FakeJob:
    program_id="sampler"
    def __init__(self,counts=None,backend="ibm_fake_2q",status="DONE",
                 job_id="synthetic-123",pubs=1):
        self._counts=counts if counts is not None else {"00":5,"01":7,"10":8}
        self._backend=backend
        self._status=status
        self._job_id=job_id
        self._pubs=pubs
    def job_id(self):return self._job_id
    def backend(self):return SimpleNamespace(name=self._backend)
    def status(self):return self._status
    def result(self):
        return [SimpleNamespace(data=SimpleNamespace(c=MockRegister(self._counts)))
                for _ in range(self._pubs)]


class FakeService:
    def __init__(self,job):
        self._job=job
        self.calls=[]
    def job(self,job_id):
        self.calls.append(("read_existing_job",job_id))
        return self._job


def test_readback_matches_without_hardware_claim():
    receipt=fixture()
    service=FakeService(FakeJob())
    record=verify_ibm_readback(receipt,service=service)
    assert service.calls==[("read_existing_job","synthetic-123")]
    assert record["provider_job_readback_matched"] is True
    assert record["provider_counts_authenticated_via_client"] is True
    assert record["compiled_circuit_provenance_verified"] is False
    assert record["physical_qpu_execution_verified"] is False
    assert record["quantum_advantage_claimed"] is False
    assert record["receipt_sha256"]==receipt["content_sha256"]
    assert record["content_sha256"]==canonical_sha256({
        k:v for k,v in record.items() if k!="content_sha256"})
    assert receipt["provider_provenance_verified"] is False


@pytest.mark.parametrize("job",[
    FakeJob(counts={"00":5,"01":8,"10":7}),
    FakeJob(counts={"00":5,"01":7,"10":7}),
    FakeJob(counts={"00":5,"01":7,"10":8,"111":1}),
    FakeJob(counts={"00":5,"01":7,"10":True}),
    FakeJob(backend="other_backend"),
    FakeJob(job_id="wrong"),
    FakeJob(status="RUNNING"),
    FakeJob(pubs=2),
])
def test_incorrect_ibm_readback_is_rejected(job):
    with pytest.raises(ProblemError):
        verify_ibm_readback(fixture(),service=FakeService(job))


def test_receipt_tampering_rejected_before_service_call():
    receipt=fixture()
    receipt["shots"]=21
    service=FakeService(FakeJob())
    with pytest.raises(ProblemError,match="hash mismatch"):
        verify_ibm_readback(receipt,service=service)
    assert service.calls==[]


def test_non_ibm_receipt_rejected():
    receipt=fixture()
    receipt["provider"]="unknown_provider"
    receipt["content_sha256"]=canonical_sha256({
        k:v for k,v in receipt.items() if k!="content_sha256"})
    service=FakeService(FakeJob())
    with pytest.raises(ProblemError,match="Not an IBM"):
        verify_ibm_readback(receipt,service=service)
    assert service.calls==[]


def test_reject_claimed_provider_verification_without_api():
    receipt=fixture()
    receipt["physical_qpu_execution_verified"]=True
    receipt["content_sha256"]=canonical_sha256({
        k:v for k,v in receipt.items() if k!="content_sha256"})
    with pytest.raises(ProblemError,match="Untrusted"):
        verify_ibm_readback(receipt,service=FakeService(FakeJob()))


def test_empty_ambiguous_and_non_sampler_results_rejected():
    receipt=fixture()
    for job in (FakeJob(pubs=0),FakeJob(counts={}),FakeJob()):
        if job._counts and job._pubs:
            job.program_id="estimator"
        with pytest.raises(ProblemError):
            verify_ibm_readback(receipt,service=FakeService(job))
