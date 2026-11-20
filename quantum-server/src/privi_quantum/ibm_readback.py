# Copyright (c) 2026 Privi World Corp. All rights reserved.
# Made by Dario Canoy.
"""Read-only IBM Quantum Runtime job readback. No job submission methods.

Retrieval of an existing SamplerV2 job via authenticated service is evidence
of returned metadata and counts, NOT an IBM-signed execution attestation or
proof that the supplied compiled QASM was executed. No paid work triggered.
"""
from __future__ import annotations
from .evidence_lab import canonical_sha256
from .qaoa import ProblemError
from .hardware_evidence import _identifier

MAX_COUNTS=1_000_000
MAX_BITS=10


def _status(raw):
    return str(getattr(raw,"name",raw)).upper().split(".")[-1]


def _counts(pub,n):
    data=getattr(pub,"data",None)
    if data is None:
        raise ProblemError("Sampler result missing data")
    attrs=vars(data) if hasattr(data,"__dict__") else {}
    registers=[v for k,v in attrs.items() if not k.startswith("_")
               and callable(getattr(v,"get_counts",None))]
    if len(registers)!=1:
        raise ProblemError("Sampler result requires exactly one measurement register")
    result=registers[0].get_counts()
    if not isinstance(result,dict) or not result:
        raise ProblemError("Invalid Sampler counts")
    clean={}
    total=0
    for bits,value in result.items():
        if not isinstance(bits,str) or len(bits)!=n or any(c not in "01" for c in bits):
            raise ProblemError("IBM readback bitstrings mismatch circuit width")
        if type(value) is not int or value<0:
            raise ProblemError("IBM readback counts invalid")
        total+=value
        if total>MAX_COUNTS:
            raise ProblemError("IBM readback shots above maximum")
        clean[bits]=value
    if total==0:
        raise ProblemError("Empty IBM readback")
    return clean,total


def verify_ibm_readback(receipt:dict, *, service) -> dict:
    """Compare a content-addressed receipt against an existing IBM job.

    The service must be a server-owned authenticated QiskitRuntimeService.
    No arbitrary user-supplied URLs. Neither this function nor its helpers
    may submit, schedule, cancel, or pay for a new job.
    """
    if not isinstance(receipt,dict) or receipt.get("schema")!="privi.quantum.hardware_evidence.v1":
        raise ProblemError("Expected Privi Quantum hardware evidence receipt")
    original_hash=receipt.get("content_sha256")
    if (not isinstance(original_hash,str) or len(original_hash)!=64 or
            canonical_sha256({k:v for k,v in receipt.items() if k!="content_sha256"})!=original_hash):
        raise ProblemError("Receipt content hash mismatch")
    if (receipt.get("provider_provenance_verified") is not False or
            receipt.get("physical_qpu_execution_verified") is not False):
        raise ProblemError("Untrusted original receipt provenance flags")
    job_id=_identifier(receipt.get("provider_job_id"),"provider_job_id")
    backend=_identifier(receipt.get("backend"),"backend")
    if receipt.get("provider") not in ("IBM-Quantum","IBM Quantum"):
        raise ProblemError("Not an IBM Quantum receipt")
    n=receipt.get("qubits")
    if type(n) is not int or not 1<=n<=MAX_BITS:
        raise ProblemError("Unsupported circuit width")
    job=service.job(job_id)
    if str(job.job_id())!=job_id:
        raise ProblemError("Authenticated job identifier mismatch")
    if _status(job.status()) not in ("DONE","COMPLETED"):
        raise ProblemError("IBM job not complete")
    actual_backend=job.backend()
    backend_name=getattr(actual_backend,"name",None)
    if callable(backend_name):
        backend_name=backend_name()
    if backend_name!=backend:
        raise ProblemError("Authenticated IBM backend mismatch")
    program_id=getattr(job,"program_id",None)
    if callable(program_id):
        program_id=program_id()
    if program_id is not None and str(program_id) not in ("sampler","sampler_v2"):
        raise ProblemError("Not an IBM Sampler job")
    result=job.result()
    if not hasattr(result,"__len__") or len(result)!=1:
        raise ProblemError("Only one-PUB Sampler results supported")
    provider_counts,total=_counts(result[0],n)
    if receipt.get("counts")!=provider_counts or receipt.get("shots")!=total:
        raise ProblemError("Provider readback differs from submitted evidence")
    outcome={
        "schema":"privi.quantum.ibm_readback.v1",
        "receipt_sha256":original_hash,
        "source":"authenticated_QiskitRuntimeService_read",
        "provider":"IBM Quantum",
        "provider_job_id":job_id,
        "backend":backend,
        "shots":total,
        "counts_sha256":canonical_sha256(provider_counts),
        "provider_job_readback_matched":True,
        "provider_counts_authenticated_via_client":True,
        "submitted_circuit_provenance_verified":False,
        "compiled_circuit_provenance_verified":False,
        "physical_qpu_execution_verified":False,
        "quantum_advantage_claimed":False,
        "limitations":[
            "Client API readback is not a signed IBM attestation",
            "The submitted ISA circuit and its SHA256 digest were not independently recovered",
            "QPU versus simulator classification was not independently verified",
            "No quantum advantage or benchmark speedup is established",
        ],
    }
    outcome["content_sha256"]=canonical_sha256(outcome)
    return outcome
