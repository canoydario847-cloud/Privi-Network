"""Independently verifiable sandbox Ed25519 signatures, no network or real actions."""
import importlib.util
from pathlib import Path
import unittest

try:
    import cryptography  # noqa: F401
except ImportError:
    cryptography = None


@unittest.skipUnless(cryptography is not None, "install cryptography>=43,<47")
class SignedReceiptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).with_name("signed_receipt.py")
        spec = importlib.util.spec_from_file_location("privi_one_signed_receipt_tests", path)
        cls.signer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.signer)

    def setUp(self):
        self.private, self.public = self.signer.create_keypair()
        self.kid = self.signer.key_id(self.public)
        self.receipt = {
            "schema": "privi-one-prelaunch-v1",
            "mode": "PRELAUNCH_SIMULATION_NO_EXTERNAL_EXECUTION",
            "execution": "NOT_ATTEMPTED",
            "ledger": "NOT_SUBMITTED",
            "routing": {"selected_id": "balanced", "estimated_savings_cents": 11},
        }

    def test_signature_verified_by_pinned_public_key(self):
        signed = self.signer.sign_receipt(self.receipt, private_key_bytes=self.private)
        self.assertTrue(self.signer.verify_receipt(signed, trusted_keys={self.kid: self.public}))
        self.assertFalse(self.signer.verify_receipt(signed, trusted_keys={}))

    def test_receipt_modification_rejected(self):
        signed = self.signer.sign_receipt(self.receipt, private_key_bytes=self.private)
        signed["signed"]["receipt"]["routing"]["estimated_savings_cents"] = 9999
        self.assertFalse(self.signer.verify_receipt(signed, trusted_keys={self.kid: self.public}))

    def test_signature_substitution_rejected(self):
        signed = self.signer.sign_receipt(self.receipt, private_key_bytes=self.private)
        other, _ = self.signer.create_keypair()
        forged = self.signer.sign_receipt(self.receipt, private_key_bytes=other)
        signed["signature_b64url"] = forged["signature_b64url"]
        self.assertFalse(self.signer.verify_receipt(signed, trusted_keys={self.kid: self.public}))

    def test_embedded_public_key_not_trusted(self):
        signed = self.signer.sign_receipt(self.receipt, private_key_bytes=self.private)
        signed["public_key"] = self.signer.b64(self.public)
        self.assertFalse(self.signer.verify_receipt(signed, trusted_keys={}))
        self.assertTrue(self.signer.verify_receipt(signed, trusted_keys={self.kid: self.public}))

    def test_non_demo_execution_refused(self):
        r = dict(self.receipt, mode="PRODUCTION", execution="SUCCESS")
        with self.assertRaises(ValueError):
            self.signer.sign_receipt(r, private_key_bytes=self.private)

    def test_key_id_mismatch_rejected(self):
        with self.assertRaises(ValueError):
            self.signer.sign_receipt(self.receipt, private_key_bytes=self.private,
                                     key_id_value="untrusted-key")
        signed = self.signer.sign_receipt(self.receipt, private_key_bytes=self.private)
        self.assertFalse(self.signer.verify_receipt(
            signed, trusted_keys={self.kid: b"0" * 32}))

    def test_offline_generate_and_verify(self):
        import tempfile
        demo_path = Path(__file__).with_name("signing_demo.py")
        spec = importlib.util.spec_from_file_location("privi_one_offline_signing_example", demo_path)
        example = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(example)
        with tempfile.TemporaryDirectory() as folder:
            artifact = Path(folder) / "signed.json"
            pinned = Path(folder) / "trusted.json"
            example.generate(artifact, pinned)
            self.assertTrue(example.verify(artifact, pinned))
            signed = __import__("json").loads(artifact.read_text())
            signed["signed"]["receipt"]["decision"] = "PRODUCTION_SUCCESS"
            artifact.write_text(__import__("json").dumps(signed))
            self.assertFalse(example.verify(artifact, pinned))

    def test_malformed_signature_fails_closed(self):
        signed = self.signer.sign_receipt(self.receipt, private_key_bytes=self.private)
        signed["signature_b64url"] = "invalid"
        self.assertFalse(self.signer.verify_receipt(signed, trusted_keys={self.kid: self.public}))


if __name__ == "__main__":
    unittest.main()
