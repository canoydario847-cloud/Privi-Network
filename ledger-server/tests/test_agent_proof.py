"""Security regression tests for paid Privi Agent Proof skill."""
import base64
import hashlib
import json
import time
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
# Load isolated signature verifier without importing the entire MCP server package.
import importlib.util
from pathlib import Path
_spec = importlib.util.spec_from_file_location(
    "privi_agent_proof_isolated", Path(__file__).parents[1] / "src" / "privi_ledger" / "agent_proof.py"
)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
verify_agent_proof = _module.verify_agent_proof


def canon(data):
    return json.dumps(data, sort_keys=True, separators=(",",":"), ensure_ascii=True).encode()


def digest(data):
    return hashlib.sha256(canon({k:v for k,v in data.items() if k != "signature"})).hexdigest()


def b64(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def sign(data, key):
    data["signature"] = b64(key.sign(canon({k:v for k,v in data.items() if k != "signature"})))


def fixture():
    now = int(time.time() * 1000)
    policy = Ed25519PrivateKey.generate()
    executor = Ed25519PrivateKey.generate()
    a = dict(version="privi-agent-proof-v1", tenant_id="tenant-a", actor_id="bot-a",
             decision_id="decision-1", action_id="action-1", policy_digest="a"*64,
             request_digest="b"*64, decision="ALLOW", issued_at_ms=now-5000,
             expires_at_ms=now+60000, signer_id="policy-1")
    sign(a, policy)
    e = dict(version="privi-agent-proof-v1", decision_id="decision-1", action_id="action-1",
             authorization_digest=digest(a), status="COMPLETED", result_digest="c"*64,
             recorded_at_ms=now-1000, executor_id="executor-1", signer_id="executor-1")
    sign(e, executor)
    key = lambda k: b64(k.public_key().public_bytes(encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw))
    trust = {"policy": {"signer_id":"policy-1", "public_key":key(policy)},
             "executor":{"signer_id":"executor-1", "public_key":key(executor)}}
    return a, e, trust, policy, executor, now


class AgentProofTests(unittest.TestCase):
    def test_valid_independent_signatures(self):
        a,e,t,_,_,now=fixture()
        result=verify_agent_proof(a,e,t,now_ms=now)
        self.assertTrue(result["authorized_and_completed"])
        self.assertTrue(result["verified"])
        self.assertEqual(result["storage"], "none")

    def test_policy_tampering_rejected(self):
        a,e,t,_,_,now=fixture()
        a["decision"]="DENY"
        self.assertFalse(verify_agent_proof(a,e,t,now_ms=now)["verified"])

    def test_acknowledgment_tampering_rejected(self):
        a,e,t,_,_,now=fixture()
        e["status"]="FAILED"
        self.assertFalse(verify_agent_proof(a,e,t,now_ms=now)["verified"])

    def test_mismatched_action_rejected(self):
        a,e,t,_,ex,now=fixture()
        e["action_id"]="action-other"
        sign(e,ex)
        self.assertEqual(verify_agent_proof(a,e,t,now_ms=now)["reason"],"identity_mismatch")

    def test_denial_never_counts_as_execution(self):
        a,e,t,pol,ex,now=fixture()
        a["decision"]="DENY"
        sign(a,pol)
        e["authorization_digest"]=digest(a)
        sign(e,ex)
        result=verify_agent_proof(a,e,t,now_ms=now)
        self.assertTrue(result["verified"])
        self.assertFalse(result["authorized_and_completed"])

    def test_acceptance_not_completion(self):
        a,e,t,_,ex,now=fixture()
        e["status"]="ACCEPTED"
        sign(e,ex)
        result=verify_agent_proof(a,e,t,now_ms=now)
        self.assertTrue(result["verified"])
        self.assertFalse(result["authorized_and_completed"])

    def test_wrong_public_key_rejected(self):
        a,e,t,_,_,now=fixture()
        other=Ed25519PrivateKey.generate()
        t["policy"]["public_key"]=b64(other.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,format=serialization.PublicFormat.Raw))
        self.assertFalse(verify_agent_proof(a,e,t,now_ms=now)["verified"])

    def test_missing_executor_trust_fails_closed(self):
        a,e,t,_,_,now=fixture()
        del t["executor"]
        self.assertFalse(verify_agent_proof(a,e,t,now_ms=now)["verified"])

    def test_replay_old_record_rejected(self):
        a,e,t,_,_,now=fixture()
        self.assertEqual(verify_agent_proof(a,e,t,now_ms=now+600_001)["reason"],
                         "expired_or_inconsistent_timestamps")

    def test_extra_unsigned_fields_rejected(self):
        a,e,t,_,_,now=fixture()
        a["admin"]=True
        self.assertEqual(verify_agent_proof(a,e,t,now_ms=now)["reason"],"invalid_schema")

    def test_reused_signer_denied(self):
        a,e,t,_,ex,now=fixture()
        e["signer_id"]="policy-1"
        sign(e,ex)
        t["executor"]["signer_id"]="policy-1"
        self.assertEqual(verify_agent_proof(a,e,t,now_ms=now)["reason"],"distinct_signers_required")

    def test_non_dict_inputs_rejected(self):
        self.assertFalse(verify_agent_proof([],{},{} )["verified"])

    def test_invalid_truthy_bool_timestamps_rejected(self):
        a,e,t,_,_,now=fixture()
        a["issued_at_ms"]=True
        self.assertEqual(verify_agent_proof(a,e,t,now_ms=now)["reason"],"invalid_timestamp")


if __name__ == "__main__":
    unittest.main()
