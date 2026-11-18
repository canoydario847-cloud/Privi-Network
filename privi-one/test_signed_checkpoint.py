"""Offline signed sandbox checkpoints: trust, tampering, and truncation."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

try:
    import cryptography  # noqa
except ImportError:
    cryptography = None


@unittest.skipUnless(cryptography is not None, "install cryptography>=43,<47")
class SignedCheckpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).with_name("signed_checkpoint.py")
        spec = importlib.util.spec_from_file_location("one_signed_checkpoint", path)
        cls.s = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.s)
        p = Path(__file__).with_name("receipt_journal.py")
        spec2 = importlib.util.spec_from_file_location("one_receipt_journal", p)
        cls.j = importlib.util.module_from_spec(spec2)
        spec2.loader.exec_module(cls.j)

    def setUp(self):
        self.key, self.pub = self.s.generate_keypair()
        self.kid = self.s.key_id(self.pub)
        self.dir = tempfile.TemporaryDirectory()
        self.dbpath = str(Path(self.dir.name) / "test.sqlite3")
        self.store = self.j.Journal(self.dbpath)

    def tearDown(self):
        self.dir.cleanup()

    def fixture(self):
        self.store.run_once("session1", "request-001", {"task": "synthetic"},
                            lambda: {"receipt": "not executed"})
        return self.j.checkpoint(self.store)

    def test_independent_verification_with_pinned_key(self):
        signed = self.s.sign(self.fixture(), private_key=self.key)
        self.assertTrue(self.s.verify(signed, pinned_public_keys={self.kid: self.pub}))
        self.assertFalse(self.s.verify(signed, pinned_public_keys={}))

    def test_changed_checkpoint_is_not_signed(self):
        signed = self.s.sign(self.fixture(), private_key=self.key)
        signed["body"]["checkpoint"]["sequence"] += 1
        self.assertFalse(self.s.verify(signed, pinned_public_keys={self.kid: self.pub}))

    def test_rogue_key_does_not_validate(self):
        signed = self.s.sign(self.fixture(), private_key=self.key)
        other_private, other_public = self.s.generate_keypair()
        other_signed = self.s.sign(signed["body"]["checkpoint"], private_key=other_private)
        self.assertFalse(self.s.verify(other_signed, pinned_public_keys={self.kid: self.pub}))
        self.assertFalse(self.s.verify(signed, pinned_public_keys={self.kid: other_public}))

    def test_signed_checkpoint_detects_truncation(self):
        checkpoint = self.fixture()
        signed = self.s.sign(checkpoint, private_key=self.key)
        self.assertTrue(self.s.verify(signed, pinned_public_keys={self.kid: self.pub}))
        self.assertTrue(self.j.check_pinned_checkpoint(self.store, checkpoint)["valid"])
        import sqlite3
        with sqlite3.connect(self.dbpath) as db:
            db.execute("DELETE FROM receipts")
        self.assertEqual(self.j.check_pinned_checkpoint(
            self.store, signed["body"]["checkpoint"])["reason"], "journal_truncated")

    def test_malformed_and_non_sandbox_rejected(self):
        with self.assertRaises(ValueError):
            self.s.sign({"sequence": 1, "head": "0"*64}, private_key=self.key)
        signed = self.s.sign(self.fixture(), private_key=self.key)
        signed["signature_b64url"] = "@"
        self.assertFalse(self.s.verify(signed, pinned_public_keys={self.kid: self.pub}))


if __name__ == "__main__":
    unittest.main()
