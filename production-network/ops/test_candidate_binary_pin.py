#!/usr/bin/env python3
"""Tests for the testnet-only candidate binary pin."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "candidate_binary_pin.py"
TEMPLATE = Path(__file__).resolve().parent / "candidate_binary_pin.UNPINNED.json"


def load_mod():
    spec = importlib.util.spec_from_file_location("candidate_binary_pin", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def base_pin():
    return {
        "schema": "privi-candidate-binary-pin-v1",
        "scope": "testnet-candidate-only",
        "financial_mainnet": False,
        "production_release": False,
        "mainnet_activated": False,
        "upstream": {
            "repo": "cosmos/evm",
            "tag": "v0.7.3",
            "commit": "c3ae9067a7eadcdea55a5192226916deb44c71c4",
        },
        "go": "1.25.9",
        "sdk": "v0.54.3",
        "cosmos_chain_id": "privi-testnet-candidate",
        "evm_chain_id": 867530901,
        "artifact": {"name": "evmd", "sha256": "UNPINNED"},
    }


class CandidateBinaryPinTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_mod()

    def test_template_is_incomplete(self):
        code = self.mod.main(["--pin", str(TEMPLATE)])
        self.assertEqual(code, 1)
        pin = json.loads(TEMPLATE.read_text(encoding="utf-8"))
        self.assertEqual(pin["artifact"]["sha256"], "UNPINNED")
        self.assertIs(pin["financial_mainnet"], False)
        self.assertEqual(self.mod.check_policy(pin), [])

    def test_matching_binary_still_not_mainnet(self):
        blob = b"candidate-evmd-bytes"
        digest = hashlib.sha256(blob).hexdigest()
        pin = base_pin()
        pin["artifact"]["sha256"] = digest
        with tempfile.TemporaryDirectory() as td:
            binary = Path(td) / "evmd"
            binary.write_bytes(blob)
            path = Path(td) / "pin.json"
            path.write_text(json.dumps(pin), encoding="utf-8")
            code = self.mod.main(["--pin", str(path), "--binary", str(binary)])
        self.assertEqual(code, 0)

    def test_hash_mismatch(self):
        pin = base_pin()
        pin["artifact"]["sha256"] = "ab" * 32
        with tempfile.TemporaryDirectory() as td:
            binary = Path(td) / "evmd"
            binary.write_bytes(b"other")
            path = Path(td) / "pin.json"
            path.write_text(json.dumps(pin), encoding="utf-8")
            code = self.mod.main(["--pin", str(path), "--binary", str(binary)])
        self.assertEqual(code, 1)

    def test_rejects_demo_and_mainnet_claims(self):
        demo = base_pin()
        demo["cosmos_chain_id"] = "local-4221"
        self.assertTrue(self.mod.check_policy(demo))
        financial = base_pin()
        financial["financial_mainnet"] = True
        self.assertTrue(any("financial_mainnet" in e for e in self.mod.check_policy(financial)))
        evm = base_pin()
        evm["evm_chain_id"] = 262144
        self.assertTrue(self.mod.check_policy(evm))
        drifted = base_pin()
        drifted["upstream"]["commit"] = "0" * 40
        self.assertTrue(any("upstream.commit" in e for e in self.mod.check_policy(drifted)))


if __name__ == "__main__":
    unittest.main()
