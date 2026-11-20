# Copyright (c) 2026 Privi World Corp. All rights reserved.
# Made by Dario Canoy.
"""Offline Privi Quantum evidence certificates, with conservative trust labels.

A Privi dual-signature (Ed25519 and ML-DSA-87) authenticates the statement
made by Privi and detects alteration. It does NOT turn self-reported data
into provider-signed evidence, certify a physical QPU or prove advantage.

The caller must supply a trusted server-owned Attestor and an authorized
pre-existing Runtime service. No HTTP endpoint, billing, token operation,
network job submission, or blockchain anchoring is performed.
"""
from __future__ import annotations

import hashlib
import hmac
from .attest import Attestor, canonical
from .evidence_lab import canonical_sha256
from .ibm_input_binding import bind_existing_ibm_job
from .qaoa import ProblemError


KIND="ibm_existing_job_input_readback_v1"


def issue_readback_certificate(receipt:dict, *, compiled_qasm:str, service, attestor:Attestor) -> dict:
    """Verify a previously completed job and sign a limited factual statement.

    This library requires explicit trusted server-side adapters; it is not
    made available as an open MCP tool to prevent job enumeration and
    accidental exposure of account-private IBM data.
    """
    if not isinstance(attestor, Attestor):
        raise ProblemError("Trusted Privi attestor required")
    binding=bind_existing_ibm_job(receipt,compiled_qasm=compiled_qasm,service=service)
    if (binding.get("retrieved_input_circuit_matches_declared") is not True
            or binding.get("job_inputs_retrieved_from_authenticated_client") is not True
            or binding.get("provider_signed_attestation") is not False
            or binding.get("physical_qpu_execution_verified") is not False
            or binding.get("quantum_advantage_claimed") is not False):
        raise ProblemError("Unsafe evidence claims")
    body={
        "schema":"privi.quantum.ibm_evidence_certificate.v1",
        "evidence_class":"account_authenticated_client_readback_only",
        "source_receipt_sha256":receipt["content_sha256"],
        "input_binding_sha256":binding["content_sha256"],
        "provider_job_id":binding["provider_job_id"],
        "compiled_qasm_sha256":binding["compiled_qasm_sha256"],
        "verified_checks":{
            "readback_counts_match_receipt":True,
            "retrieved_job_input_matches_declared_circuit":True,
        },
        "scope":{
            "privi_signatures_authenticate_certificate":True,
            "ibm_provider_signed_attestation":False,
            "physical_qpu_execution_verified":False,
            "quantum_advantage_claimed":False,
            "blockchain_anchor_created":False,
        },
        "limitations":[
            "Privi's own signature authenticates only this limited Privi statement",
            "Existing IBM job was read via an account-authenticated SDK, not an IBM-signed independent certificate",
            "Job execution, provider identity, backend physical type and quantum advantage are not proven",
        ],
    }
    # Signed statement contains no raw customer tokens or quantum job counts.
    att=attestor.issue(KIND,body)
    if att["anchor"] is not None:
        raise ProblemError("Unexpected external anchoring")
    return {"certificate":att,"privi_public_keys":attestor.public_keys()}


def verify_readback_certificate(bundle:dict) -> dict:
    """Verify both Privi signatures and the narrow immutable claim scope.

    Public keys supplied in the bundle are not a trust root. A reviewer must
    independently pin the actual Privi issuer's expected key ID/public keys.
    """
    try:
        att=bundle["certificate"]
        public=bundle["privi_public_keys"]
        body=att["body"]
        signed=Attestor.verify(att,public["ed25519"],public["ml_dsa_87"])
        safe=(body.get("schema")=="privi.quantum.ibm_evidence_certificate.v1"
              and body.get("kind")==KIND
              and body.get("evidence_class")=="account_authenticated_client_readback_only"
              and body.get("scope",{}).get("ibm_provider_signed_attestation") is False
              and body.get("scope",{}).get("physical_qpu_execution_verified") is False
              and body.get("scope",{}).get("quantum_advantage_claimed") is False
              and body.get("scope",{}).get("blockchain_anchor_created") is False
              and att.get("anchor") is None
              and att.get("key_id")==public.get("key_id"))
        return {"cryptographically_valid":signed["valid"] and bool(safe),
                "limited_claims_safe":bool(safe),
                "issuer_key_independently_trusted":False,
                "physical_qpu_execution_verified":False,
                "quantum_advantage_claimed":False}
    except (KeyError,TypeError,ValueError,AttributeError):
        return {"cryptographically_valid":False,"limited_claims_safe":False,
                "issuer_key_independently_trusted":False,
                "physical_qpu_execution_verified":False,
                "quantum_advantage_claimed":False}
