# Copyright (c) 2026 Privi World Corp. All rights reserved.
# Made by Dario Canoy.
"""Dual-signed Privi readback certificate tests, entirely synthetic/offline."""
from types import SimpleNamespace
import copy
import tempfile

import pytest
from qiskit import QuantumCircuit

from privi_quantum.attest import Attestor
from privi_quantum.ibm_certificate import (
    issue_readback_certificate, verify_readback_certificate,
)
from privi_quantum.qaoa import ProblemError
from test_ibm_input_binding import inputs, ExistingJob, ReadOnlyService


@pytest.fixture
def signer(tmp_path):
    return Attestor(str(tmp_path/"quantum-signing-test.db"))


def good():
    receipt,qasm=inputs()
    return receipt,qasm,ReadOnlyService(ExistingJob(QuantumCircuit.from_qasm_str(qasm)))


def test_signs_limited_readback_and_verifies_both_signatures(signer):
    receipt,qasm,service=good()
    result=issue_readback_certificate(
        receipt,compiled_qasm=qasm,service=service,attestor=signer)
    checked=verify_readback_certificate(result)
    assert checked["cryptographically_valid"]
    assert checked["limited_claims_safe"]
    assert not checked["issuer_key_independently_trusted"]
    assert not checked["physical_qpu_execution_verified"]
    assert not checked["quantum_advantage_claimed"]
    certificate=result["certificate"]
    assert certificate["anchor"] is None
    assert certificate["body"]["scope"]["ibm_provider_signed_attestation"] is False
    assert certificate["body"]["scope"]["blockchain_anchor_created"] is False
    assert certificate["body"]["source_receipt_sha256"]==receipt["content_sha256"]
    assert service.calls==["synthetic-123"]


def test_body_tamper_invalidates_certificate(signer):
    receipt,qasm,service=good()
    result=issue_readback_certificate(
        receipt,compiled_qasm=qasm,service=service,attestor=signer)
    altered=copy.deepcopy(result)
    altered["certificate"]["body"]["scope"]["physical_qpu_execution_verified"]=True
    assert not verify_readback_certificate(altered)["cryptographically_valid"]
    altered=copy.deepcopy(result)
    altered["certificate"]["body"]["provider_job_id"]="forged"
    assert not verify_readback_certificate(altered)["cryptographically_valid"]


def test_bad_signature_and_incomplete_bundle_rejected(signer):
    receipt,qasm,service=good()
    result=issue_readback_certificate(
        receipt,compiled_qasm=qasm,service=service,attestor=signer)
    altered=copy.deepcopy(result)
    altered["certificate"]["signatures"]["ed25519"]="AAAA"
    assert not verify_readback_certificate(altered)["cryptographically_valid"]
    assert not verify_readback_certificate({})["cryptographically_valid"]


def test_reject_mismatched_job_before_signing(signer):
    receipt,qasm,service=good()
    service.existing.circuit.rz(0.25,0)
    before=signer.count()
    with pytest.raises(ProblemError,match="differs"):
        issue_readback_certificate(
            receipt,compiled_qasm=qasm,service=service,attestor=signer)
    assert signer.count()==before


def test_reject_untrusted_signer_before_reading_ibm_job():
    receipt,qasm,service=good()
    with pytest.raises(ProblemError,match="Trusted Privi attestor"):
        issue_readback_certificate(
            receipt,compiled_qasm=qasm,service=service,attestor=object())
    assert service.calls==[]


def test_no_provider_signature_claim_even_with_own_valid_signatures(signer):
    receipt,qasm,service=good()
    bundle=issue_readback_certificate(
        receipt,compiled_qasm=qasm,service=service,attestor=signer)
    assert bundle["certificate"]["body"]["evidence_class"]=="account_authenticated_client_readback_only"
    assert not verify_readback_certificate(bundle)["issuer_key_independently_trusted"]

def test_independently_pinned_issuer_keys_required_for_trusted_verdict(signer):
    receipt,qasm,service=good()
    bundle=issue_readback_certificate(
        receipt,compiled_qasm=qasm,service=service,attestor=signer)
    public=signer.public_keys()
    verified=verify_readback_certificate(bundle,pinned_issuer_keys=public)
    assert verified["cryptographically_valid"]
    assert verified["issuer_key_independently_trusted"]
    assert verified["physical_qpu_execution_verified"] is False
    incorrect=dict(public,ed25519="different")
    assert not verify_readback_certificate(
        bundle,pinned_issuer_keys=incorrect)["issuer_key_independently_trusted"]
    assert not verify_readback_certificate(
        bundle)["issuer_key_independently_trusted"]
