# Copyright (c) 2026 Privi World Co. All rights reserved.
"""Unit tests for the Privi Quantum migration gate (standard library only)."""
import unittest
from privi_quantum.migration_gate import (
    SignatureEvidence, canonical_event, event_digest, migration_gate,
)


class MigrationGateTests(unittest.TestCase):
    def setUp(self):
        self.event = {"chain": "privi", "height": 17, "agent": "jose"}
        self.digest = event_digest(self.event)

    def test_canonical_order(self):
        self.assertEqual(self.digest, event_digest(dict(reversed(list(self.event.items())))))

    def test_reject_float(self):
        with self.assertRaises(ValueError):
            canonical_event({"amount": 0.1})

    def test_no_evidence_fails_closed(self):
        self.assertFalse(migration_gate(self.event, [])["approved"])

    def test_pq_only_needs_hybrid_by_default(self):
        pq = SignatureEvidence("ML-DSA-65", True, self.digest)
        self.assertFalse(migration_gate(self.event, [pq])["approved"])
        self.assertTrue(migration_gate(self.event, [pq], require_hybrid=False)["approved"])

    def test_hybrid_passes(self):
        evidence = [SignatureEvidence("ML-DSA-65", True, self.digest),
                    SignatureEvidence("Ed25519", True, self.digest)]
        self.assertTrue(migration_gate(self.event, evidence)["approved"])

    def test_wrong_digest_fails(self):
        evidence = [SignatureEvidence("ML-DSA-65", True, "0" * 64),
                    SignatureEvidence("Ed25519", True, self.digest)]
        self.assertFalse(migration_gate(self.event, evidence)["approved"])

    def test_unverified_fails(self):
        evidence = [SignatureEvidence("ML-DSA-65", False, self.digest),
                    SignatureEvidence("Ed25519", True, self.digest)]
        self.assertFalse(migration_gate(self.event, evidence)["approved"])

    def test_unknown_algorithm_fails(self):
        evidence = [SignatureEvidence("ML-DSA-65", True, self.digest),
                    SignatureEvidence("Ed25519", True, self.digest),
                    SignatureEvidence("UnknownPQ", True, self.digest)]
        self.assertFalse(migration_gate(self.event, evidence)["approved"])


if __name__ == "__main__":
    unittest.main()
