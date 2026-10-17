#!/usr/bin/env python3
"""Tamper-negative, offline tests for signed Privi recovery safety preflight."""
import base64
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "privi_cold_recovery", ROOT / "operator-kit" / "recovery_preflight.py")
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)

NOW = datetime(2026, 10, 17, 19, 0, tzinfo=timezone.utc)
CID = "privi-ci-nonproduction-999"


class OfflineRecoverySafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="privi-ci-recovery-unit-")
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "validator"
        (self.home / "config").mkdir(parents=True)
        (self.home / "data").mkdir()
        self.operator = Ed25519PrivateKey.generate()
        self.operator_public = self.operator.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.consensus_seed = bytes(range(32))  # ephemeral synthetic unit-test material
        self.consensus_key = Ed25519PrivateKey.from_private_bytes(self.consensus_seed).public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.genesis = self.home / "config" / "genesis.json"
        self.genesis.write_text(json.dumps({"chain_id": CID, "app_state": {}}))
        self.keyfile = self.home / "config" / "priv_validator_key.json"
        self.keyfile.write_text(json.dumps({
            "pub_key": {"type": "tendermint/PubKeyEd25519",
                        "value": base64.b64encode(self.consensus_key).decode()},
            "priv_key": {"type": "tendermint/PrivKeyEd25519",
                         "value": base64.b64encode(self.consensus_seed + self.consensus_key).decode()}
        }))
        self.keyfile.chmod(0o600)
        self.statefile = self.home / "data" / "priv_validator_state.json"
        self.statefile.write_text(json.dumps({"height": "11", "round": 0, "step": 2}))
        self.statefile.chmod(0o600)
        start = NOW - timedelta(minutes=2)
        end = NOW + timedelta(minutes=45)
        self.message = {
            "schema_version": 1,
            "status": guard.STATUS,
            "operator_id": "ci-operator-only",
            "cosmos_chain_id": CID,
            "genesis_sha256": hashlib.sha256(self.genesis.read_bytes()).hexdigest(),
            "consensus_pubkey_b64": base64.b64encode(self.consensus_key).decode(),
            "minimum_sign_state": {"height": "10", "round": 0, "step": 1},
            "original_signer_fenced_claim": True,
            "remote_signer_fenced_claim": True,
            "created_at": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "expires_at": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "nonce": "a" * 32,
        }

    def signed(self, message=None):
        message = self.message if message is None else message
        return {
            "statement": copy.deepcopy(message),
            "signature_b64": base64.b64encode(
                self.operator.sign(guard.canonical(message))).decode()
        }

    def check(self, bundle=None):
        return guard.check_recovery(
            self.home, bundle if bundle is not None else self.signed(),
            self.operator_public, trusted_chain_id=CID,
            trusted_consensus_key=self.consensus_key, now=NOW)

    def test_positive_stays_review_only_and_offline(self):
        result = self.check()
        self.assertIn("NOT_AUTHORIZED_TO_START", result["status"])
        self.assertFalse(result["validator_start_authorized"])
        self.assertFalse(result["physical_fencing_independently_verified"])
        self.assertFalse(result["financial_mainnet_activated"])
        self.assertNotIn("priv_key", json.dumps(result))
        self.assertTrue(result["non_decreasing_last_sign_state"])

    def test_signed_statement_tampering_is_rejected(self):
        bundle = self.signed()
        bundle["statement"]["minimum_sign_state"]["height"] = "2"
        with self.assertRaisesRegex(ValueError, "signature invalid"):
            self.check(bundle)

    def test_wrong_trusted_operator_key_is_rejected(self):
        other = Ed25519PrivateKey.generate().public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        with self.assertRaisesRegex(ValueError, "signature invalid"):
            guard.check_recovery(
                self.home, self.signed(), other, trusted_chain_id=CID,
                trusted_consensus_key=self.consensus_key, now=NOW)

    def test_stale_backup_last_sign_state_is_blocked(self):
        self.message["minimum_sign_state"] = {"height": "12", "round": 0, "step": 0}
        with self.assertRaisesRegex(ValueError, "double-sign"):
            self.check()

    def test_same_height_lower_round_and_step_is_blocked(self):
        self.message["minimum_sign_state"] = {"height": "11", "round": 1, "step": 0}
        with self.assertRaisesRegex(ValueError, "double-sign"):
            self.check()
        self.message["minimum_sign_state"] = {"height": "11", "round": 0, "step": 3}
        with self.assertRaisesRegex(ValueError, "double-sign"):
            self.check()

    def test_wrong_genesis_or_consensus_public_key_is_rejected(self):
        self.genesis.write_text(json.dumps({"chain_id": CID, "app_state": {"wrong": 1}}))
        with self.assertRaisesRegex(ValueError, "genesis hash"):
            self.check()
        self.genesis.write_text(json.dumps({"chain_id": CID, "app_state": {}}))
        row = json.loads(self.keyfile.read_text())
        row["pub_key"]["value"] = base64.b64encode(bytes([255]) * 32).decode()
        self.keyfile.write_text(json.dumps(row))
        with self.assertRaisesRegex(ValueError, "signer does not match"):
            self.check()

    def test_private_signer_must_match_signed_and_trusted_public_identity(self):
        key = json.loads(self.keyfile.read_text())
        bogus = bytes([42])*64
        key["priv_key"]["value"] = base64.b64encode(bogus).decode()
        self.keyfile.write_text(json.dumps(key))
        with self.assertRaisesRegex(ValueError, "does not match approved identity"):
            self.check()

    def test_claims_do_not_substitute_for_signature(self):
        self.message["original_signer_fenced_claim"] = False
        with self.assertRaisesRegex(ValueError, "Fencing"):
            self.check()
        self.message["original_signer_fenced_claim"] = True
        self.message["remote_signer_fenced_claim"] = False
        with self.assertRaisesRegex(ValueError, "Fencing"):
            self.check()

    def test_expired_or_overlong_signed_statements_blocked(self):
        self.message["expires_at"] = (NOW - timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self.assertRaisesRegex(ValueError, "expired"):
            self.check()
        self.message["expires_at"] = (NOW + timedelta(hours=28)).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self.assertRaisesRegex(ValueError, "over 24 hours"):
            self.check()

    def test_insecure_sensitive_file_permissions_rejected(self):
        self.statefile.chmod(0o644)
        with self.assertRaisesRegex(ValueError, "only by its owner"):
            self.check()
        self.statefile.chmod(0o600)
        self.keyfile.chmod(0o644)
        with self.assertRaisesRegex(ValueError, "only by its owner"):
            self.check()

    def test_broken_symlink_and_missing_state_blocked(self):
        self.statefile.unlink()
        with self.assertRaises(ValueError):
            self.check()
        self.statefile.symlink_to(self.keyfile)
        with self.assertRaisesRegex(ValueError, "non-symlink"):
            self.check()

    def test_unsigned_extra_field_and_noncanonical_integer_blocked(self):
        extra = copy.deepcopy(self.message)
        extra["allow_mainnet_launch"] = True
        with self.assertRaisesRegex(ValueError, "unknown|Unknown|missing"):
            self.check(self.signed(extra))
        for value in ("01", "-1", 3.0, True, None):
            with self.subTest(value=value):
                self.assertRaises(ValueError, guard.state_tuple, {"height": value, "round": 0, "step": 2})


if __name__ == "__main__":
    unittest.main()
