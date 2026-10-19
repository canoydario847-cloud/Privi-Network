"""No-secrets validation of candidate launch evidence; synthetic test fixtures."""
import json
from pathlib import Path
import tempfile
import unittest
import strict_json_evidence as guard

class StrictJSONEvidenceTests(unittest.TestCase):
    def read(self, raw):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"candidate.json"
            p.write_text(raw,encoding="utf-8")
            return guard.load(p)

    def test_accepts_nonsecret_validator_fingerprints(self):
        doc={"operator":"Privi World Corp","consensus_pubkey_sha256":"a"*64,
             "signer_attestation":"review-required","private_overlay_ipv4":"10.10.0.1"}
        self.assertEqual(self.read(json.dumps(doc)),doc)

    def test_rejects_duplicate_top_level_properties(self):
        with self.assertRaisesRegex(ValueError,"duplicate JSON property"):
            self.read('{"network":"privi-mainnet","network":"local-4221"}')

    def test_rejects_duplicate_nested_properties(self):
        with self.assertRaisesRegex(ValueError,"duplicate JSON property"):
            self.read('{"app_state":{"bank":{"supply":[],"supply":[]}}}')

    def test_rejects_private_key_field_anywhere(self):
        for raw in ({"private_key":"not-a-real-value"},
                    {"operator":{"wallet_seed":"not-a-real-value"}},
                    {"validators":[{"api_key":"not-a-real-value"}]},
                    {"signers":[{"refresh_token":"not-a-real-value"}]}):
            with self.assertRaisesRegex(ValueError,"credential-like JSON field"):
                self.read(json.dumps(raw))

    def test_rejects_suspect_credential_value(self):
        for value in ("-----BEGIN PRIVATE KEY-----\nfake",
                      "-----BEGIN OPENSSH PRIVATE KEY-----\nfake",
                      "sk-proj-0123456789ABCDEFGHIJ"):
            with self.assertRaisesRegex(ValueError,"probable sensitive"):
                self.read(json.dumps({"description":value}))

    def test_error_never_prints_credentials(self):
        marker="sk-proj-0123456789ABCDEFGHIJ"
        with self.assertRaises(ValueError) as ctx:
            self.read(json.dumps({"description":marker}))
        self.assertNotIn(marker,str(ctx.exception))

    def test_rejects_nonfinite_nan(self):
        with self.assertRaisesRegex(ValueError,"nonfinite"):
            self.read('{"total":NaN}')

    def test_rejects_wrong_json(self):
        with self.assertRaises(ValueError):
            self.read('{"app_state":')

    def test_rejects_invalid_utf8(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"evidence.json"
            p.write_bytes(b'\xff')
            with self.assertRaises(ValueError):
                guard.load(p)

if __name__=="__main__":
    unittest.main()
