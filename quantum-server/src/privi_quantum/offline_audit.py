# Copyright (c) 2026 Privi World Corp. All rights reserved.
# Made by Dario Canoy.
"""Fully offline, read-only audit of a Privi Quantum certificate evidence chain.

An external reviewer supplies a certificate, independently trusted Privi
public keys, the original hardware receipt, readback record and input-binding
record. Verifies both signatures, chain digests and matching job/circuit
identifiers. Never contacts IBM, a blockchain or a Privi service.

Important: self-contained chain verification does NOT independently prove the
IBM account connection, physical QPU execution or provider-signed provenance.
The signer-key pin MUST come from an independent trusted channel.
"""
from __future__ import annotations

import hashlib
import hmac
from .evidence_lab import canonical_sha256
from .ibm_certificate import verify_readback_certificate


def _digest_ok(record):
    if not isinstance(record, dict):
        return False
    digest=record.get("content_sha256")
    if not isinstance(digest,str) or len(digest)!=64:
        return False
    try:
        expected=canonical_sha256({k:v for k,v in record.items() if k!="content_sha256"})
    except (ValueError,TypeError,UnicodeError):
        return False
    return hmac.compare_digest(digest,expected)


def audit_evidence_chain(bundle, *, pinned_issuer_keys, hardware_receipt,
                         ibm_readback, input_binding, compiled_qasm=None):
    """Produce a bounded verdict. All inputs local, no credential access."""
    rejected={
        "schema":"privi.quantum.offline_chain_audit.v1",
        "valid":False,
        "issuer_key_independently_trusted":False,
        "chain_integrity_verified":False,
        "ibm_provider_signed_attestation":False,
        "physical_qpu_execution_verified":False,
        "quantum_advantage_claimed":False,
    }
    try:
        cert=verify_readback_certificate(bundle,pinned_issuer_keys=pinned_issuer_keys)
        if (not cert["cryptographically_valid"] or
                not cert["issuer_key_independently_trusted"]):
            return dict(rejected,reason="issuer_signature_or_trust_pin_failed")
        if not all(_digest_ok(item) for item in
                   (hardware_receipt,ibm_readback,input_binding)):
            return dict(rejected,reason="evidence_content_hash_failed")
        body=bundle["certificate"]["body"]
        scope=body["scope"]
        if any((
            body.get("schema")!="privi.quantum.ibm_evidence_certificate.v1",
            body.get("evidence_class")!="account_authenticated_client_readback_only",
            hardware_receipt.get("schema")!="privi.quantum.hardware_evidence.v1",
            ibm_readback.get("schema")!="privi.quantum.ibm_readback.v1",
            input_binding.get("schema")!="privi.quantum.ibm_input_binding.v1",
            body.get("source_receipt_sha256")!=hardware_receipt["content_sha256"],
            body.get("input_binding_sha256")!=input_binding["content_sha256"],
            input_binding.get("readback_sha256")!=ibm_readback["content_sha256"],
            input_binding.get("receipt_sha256")!=hardware_receipt["content_sha256"],
            ibm_readback.get("receipt_sha256")!=hardware_receipt["content_sha256"],
            body.get("compiled_qasm_sha256")!=hardware_receipt.get("compiled_qasm_sha256"),
            input_binding.get("compiled_qasm_sha256")!=hardware_receipt.get("compiled_qasm_sha256"),
            body.get("provider_job_id")!=hardware_receipt.get("provider_job_id"),
            input_binding.get("provider_job_id")!=hardware_receipt.get("provider_job_id"),
            ibm_readback.get("provider_job_id")!=hardware_receipt.get("provider_job_id"),
            ibm_readback.get("backend")!=hardware_receipt.get("backend"),
            ibm_readback.get("shots")!=hardware_receipt.get("shots"),
            ibm_readback.get("counts_sha256")!=canonical_sha256(hardware_receipt["counts"]),
            ibm_readback.get("provider_counts_authenticated_via_client") is not True,
            ibm_readback.get("provider_job_readback_matched") is not True,
            input_binding.get("job_inputs_retrieved_from_authenticated_client") is not True,
            input_binding.get("retrieved_input_circuit_matches_declared") is not True,
            hardware_receipt.get("provider_provenance_verified") is not False,
            hardware_receipt.get("physical_qpu_execution_verified") is not False,
            ibm_readback.get("physical_qpu_execution_verified") is not False,
            input_binding.get("physical_qpu_execution_verified") is not False,
            input_binding.get("provider_signed_attestation") is not False,
            scope.get("ibm_provider_signed_attestation") is not False,
            scope.get("physical_qpu_execution_verified") is not False,
            scope.get("quantum_advantage_claimed") is not False,
            scope.get("blockchain_anchor_created") is not False,
        )):
            return dict(rejected,reason="cross_record_mismatch_or_unsafe_claim")
        if compiled_qasm is not None:
            if (not isinstance(compiled_qasm,str) or
                    hashlib.sha256(compiled_qasm.encode("utf-8")).hexdigest()
                    !=body["compiled_qasm_sha256"]):
                return dict(rejected,reason="compiled_circuit_digest_mismatch")
        return {
            "schema":"privi.quantum.offline_chain_audit.v1",
            "valid":True,
            "issuer_key_independently_trusted":True,
            "chain_integrity_verified":True,
            "source_receipt_sha256":hardware_receipt["content_sha256"],
            "certificate_body_sha256":bundle["certificate"]["body_sha256"],
            "ibm_provider_signed_attestation":False,
            "physical_qpu_execution_verified":False,
            "quantum_advantage_claimed":False,
            "scope":"Privi-signed local chain consistency; not independent IBM verification",
        }
    except (KeyError,TypeError,ValueError,UnicodeError,AttributeError):
        return dict(rejected,reason="malformed_or_incomplete_evidence")
