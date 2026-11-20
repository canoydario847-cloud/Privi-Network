# Copyright (c) 2026 Privi World Corp. All rights reserved.
# Made by Dario Canoy.
"""Opt-in IBM Runtime recovered-input circuit binding. No job submission.

Uses an EXISTING authorized Runtime job's inputs, when exposed by the SDK,
and compares the actual retrieved circuit operation-by-operation with the
declared compiled OpenQASM 2, including qubit indices, parameters and
measurement assignments. Requires Qiskit. Absence/ambiguity => fail closed.

The retrieved inputs are authenticated to the account connection, but are NOT
an IBM-signed attestation or independent proof of physical QPU execution.
"""
from __future__ import annotations

import hashlib
import math

from .evidence_lab import canonical_sha256
from .hardware_evidence import _identifier
from .ibm_readback import verify_ibm_readback
from .qaoa import ProblemError

MAX_QASM=200_000


def _instructions(circuit):
    """Normalized exact gate/measurement instruction sequence, ignoring labels."""
    from qiskit import QuantumCircuit
    if not isinstance(circuit, QuantumCircuit):
        raise ProblemError("Only Qiskit QuantumCircuit inputs are supported")
    if circuit.num_qubits < 1 or circuit.num_qubits > 10:
        raise ProblemError("Invalid recovered circuit width")
    if circuit.num_clbits != circuit.num_qubits:
        raise ProblemError("Recovered circuit needs a full measurement register")
    accepted={"h","rx","rz","cx","measure","barrier"}
    steps=[]
    for item in circuit.data:
        name=item.operation.name
        if name=="barrier":
            continue
        if name not in accepted:
            raise ProblemError("Unverifiable compiled gate; transpile to h/rx/rz/cx")
        params=[]
        for p in item.operation.params:
            try:
                value=float(p)
            except (TypeError,ValueError) as exc:
                raise ProblemError("Unbound circuit parameter") from exc
            if not math.isfinite(value):
                raise ProblemError("Nonfinite circuit parameter")
            params.append(value)
        qs=tuple(circuit.find_bit(q).index for q in item.qubits)
        cs=tuple(circuit.find_bit(c).index for c in item.clbits)
        steps.append((name,qs,cs,tuple(params)))
        if len(steps)>20000:
            raise ProblemError("Too many circuit instructions")
    return steps


def _compare_instructions(expected,recovered):
    if len(expected)!=len(recovered):
        return False
    for a,b in zip(expected,recovered):
        if a[:3]!=b[:3] or len(a[3])!=len(b[3]):
            return False
        if any(abs(x-y)>1e-10 for x,y in zip(a[3],b[3])):
            return False
    return True


def bind_existing_ibm_job(receipt:dict, *, compiled_qasm:str, service) -> dict:
    """Link an existing job's returned input circuit to evidence; no QPU calls.

    A real authenticated service must be server-created for one authorized
    customer account, with allowed job IDs verified upstream. This module
    does not implement those customer authorization controls or expose HTTP.
    """
    from qiskit import QuantumCircuit
    if not isinstance(compiled_qasm,str) or not 0<len(compiled_qasm)<=MAX_QASM:
        raise ProblemError("Compiled QASM required")
    if not isinstance(receipt,dict):
        raise ProblemError("Invalid receipt")
    declared_hash=receipt.get("compiled_qasm_sha256")
    if hashlib.sha256(compiled_qasm.encode()).hexdigest()!=declared_hash:
        raise ProblemError("Declared compiled circuit digest mismatch")
    # Retrieve exactly one authorized existing job and reuse the SAME object
    # for result/count checks and recovered-input circuit verification.
    # Two independent service.job calls can otherwise read different jobs
    # under a mutable/misconfigured provider adapter (TOCTOU).
    if not isinstance(receipt,dict):
        raise ProblemError("Invalid receipt")
    job_id=_identifier(receipt.get("provider_job_id"),"provider_job_id")
    # Validate content hash before touching the provider-facing client.
    receipt_hash=receipt.get("content_sha256")
    if (not isinstance(receipt_hash,str) or
            canonical_sha256({k:v for k,v in receipt.items() if k!="content_sha256"}) != receipt_hash):
        raise ProblemError("Receipt content hash mismatch")
    job=service.job(job_id)
    if str(job.job_id())!=job_id:
        raise ProblemError("Recovered input job identifier mismatch")

    class _SingleJobReadback:
        def job(self, requested):
            if requested != job_id:
                raise ProblemError("Unexpected provider job lookup")
            return job

    readback=verify_ibm_readback(receipt,service=_SingleJobReadback())
    inputs=getattr(job,"inputs",None)
    if callable(inputs):
        inputs=inputs()
    if not isinstance(inputs,dict) or "pubs" not in inputs:
        raise ProblemError("IBM job input circuits unavailable")
    pubs=inputs["pubs"]
    if not isinstance(pubs,(tuple,list)) or len(pubs)!=1:
        raise ProblemError("Expected one IBM Sampler PUB input")
    pub=pubs[0]
    candidate=pub[0] if isinstance(pub,(tuple,list)) and pub else pub
    if not isinstance(candidate,QuantumCircuit):
        raise ProblemError("IBM job circuit was not available as QuantumCircuit")
    try:
        declared=QuantumCircuit.from_qasm_str(compiled_qasm)
    except Exception as exc:
        raise ProblemError("Cannot parse declared OpenQASM 2") from exc
    if declared.num_qubits!=receipt["qubits"] or candidate.num_qubits!=receipt["qubits"]:
        raise ProblemError("Recovered IBM input width mismatch")
    if not _compare_instructions(_instructions(declared),_instructions(candidate)):
        raise ProblemError("Recovered IBM input circuit differs from declared compiled circuit")
    outcome={
        "schema":"privi.quantum.ibm_input_binding.v1",
        "receipt_sha256":receipt["content_sha256"],
        "readback_sha256":readback["content_sha256"],
        "compiled_qasm_sha256":declared_hash,
        "provider_job_id":job_id,
        "job_inputs_retrieved_from_authenticated_client":True,
        "retrieved_input_circuit_matches_declared":True,
        "provider_signed_attestation":False,
        "physical_qpu_execution_verified":False,
        "quantum_advantage_claimed":False,
        "limitations":[
            "Job input is returned by authenticated SDK; it is not an IBM-signed independent attestation",
            "Compiled circuit execution, backend physical type and provider identity require additional assurance",
            "Circuit equivalence is strict instruction matching in a limited h/rx/rz/cx basis",
        ],
    }
    outcome["content_sha256"]=canonical_sha256(outcome)
    return outcome
