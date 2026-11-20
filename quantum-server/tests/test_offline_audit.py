# Copyright (c) 2026 Privi World Corp. All rights reserved.
# Made by Dario Canoy.
"""Offline external audit tests using temporary keys and synthetic IBM jobs."""
import copy
import pytest
from qiskit import QuantumCircuit

from privi_quantum.attest import Attestor
from privi_quantum.ibm_certificate import issue_readback_certificate
from privi_quantum.ibm_input_binding import bind_existing_ibm_job
from privi_quantum.ibm_readback import verify_ibm_readback
from privi_quantum.offline_audit import audit_evidence_chain
from test_ibm_input_binding import inputs, ExistingJob, ReadOnlyService


@pytest.fixture
def chain(tmp_path):
    receipt,qasm=inputs()
    service=ReadOnlyService(ExistingJob(QuantumCircuit.from_qasm_str(qasm)))
    signer=Attestor(str(tmp_path/"local-test-only.db"))
    bundle=issue_readback_certificate(
        receipt,compiled_qasm=qasm,service=service,attestor=signer)
    rb=verify_ibm_readback(receipt,service=service)
    binding=bind_existing_ibm_job(receipt,compiled_qasm=qasm,service=service)
    return {
        "bundle":bundle, "pinned_issuer_keys":signer.public_keys(),
        "hardware_receipt":receipt,"ibm_readback":rb,
        "input_binding":binding,"compiled_qasm":qasm,
    }


def test_independent_chain_verified_without_IBM_or_Payment(chain):
    result=audit_evidence_chain(**chain)
    assert result["valid"]
    assert result["issuer_key_independently_trusted"]
    assert result["chain_integrity_verified"]
    assert result["ibm_provider_signed_attestation"] is False
    assert result["physical_qpu_execution_verified"] is False
    assert result["quantum_advantage_claimed"] is False


def test_self_supplied_public_keys_without_independent_pin_fail(chain):
    chain["pinned_issuer_keys"]=None
    result=audit_evidence_chain(**chain)
    assert not result["valid"]
    assert result["reason"]=="issuer_signature_or_trust_pin_failed"


def test_wrong_trust_pin_fail(chain):
    chain["pinned_issuer_keys"]=dict(chain["pinned_issuer_keys"],ed25519="not-a-key")
    assert not audit_evidence_chain(**chain)["valid"]


@pytest.mark.parametrize("field,mutator",[
    ("hardware_receipt",lambda x: x.update(shots=21)),
    ("ibm_readback",lambda x: x.update(shots=21)),
    ("input_binding",lambda x: x.update(provider_job_id="different")),
])
def test_tamper_detection_at_all_evidence_levels(chain,field,mutator):
    mutator(chain[field])
    assert not audit_evidence_chain(**chain)["valid"]


def test_circuit_digest_fail(chain):
    chain["compiled_qasm"]+="\n// tampered"
    assert not audit_evidence_chain(**chain)["valid"]


def test_validly_rehashed_unrelated_readback_fails_chain(chain):
    from privi_quantum.evidence_lab import canonical_sha256
    chain["ibm_readback"]["provider_job_id"]="other-job"
    chain["ibm_readback"]["content_sha256"]=canonical_sha256({
        k:v for k,v in chain["ibm_readback"].items() if k!="content_sha256"})
    assert not audit_evidence_chain(**chain)["valid"]


def test_validly_rehashed_unsafe_provider_flag_fails(chain):
    from privi_quantum.evidence_lab import canonical_sha256
    chain["input_binding"]["physical_qpu_execution_verified"]=True
    chain["input_binding"]["content_sha256"]=canonical_sha256({
        k:v for k,v in chain["input_binding"].items() if k!="content_sha256"})
    assert not audit_evidence_chain(**chain)["valid"]


def test_malformed_or_missing_records_fail_closed(chain):
    for key in ("hardware_receipt","ibm_readback","input_binding","bundle"):
        candidate=chain.copy()
        candidate[key]={}
        assert not audit_evidence_chain(**candidate)["valid"]


def test_certificate_signature_tampering_fails(chain):
    chain["bundle"]["certificate"]["body"]["provider_job_id"]="forged"
    assert not audit_evidence_chain(**chain)["valid"]
