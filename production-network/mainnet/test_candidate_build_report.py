#!/usr/bin/env python3
"""Fail-closed, offline tests for nonproduction-only candidate build receipts."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("candidate_build_report",HERE/"candidate_build_report.py")
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class BuildReceiptTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)
        self.binary=root/"candidate"
        self.binary.write_bytes(b"\x7fELF" + b"synthetic test only")
        self.binary.chmod(0o700)
        self.patch=root/"candidate.diff"
        anchors=("evmd/config/bech32.go","evmd/genesis.go","evmd/cmd/evmd/cmd/root.go","evmd/app.go")
        self.patch.write_text("".join(f"diff --git a/{path} b/{path}\n" for path in anchors)
                              +'GetSupply(ctx, "aprvi")\n')
        self.config=root/"config.json"
        self.doc=json.loads((HERE/"privi_chain_config.json").read_text())
        self.doc["network"]["cosmos_chain_id"]=m.CI_COSMOS
        self.doc["network"]["evm_chain_id"]=m.CI_EVM
        self.config.write_text(json.dumps(self.doc))

    def run_receipt(self):
        return m.make_receipt(self.binary,self.patch,self.config,
                              ref="refs/pull/10/merge",commit="a"*40,
                              go_version="go version go1.25.9 linux/amd64")

    def test_hash_only_receipt_remains_nonproduction(self):
        result=self.run_receipt()
        self.assertFalse(result["approved_for_financial_mainnet"])
        self.assertFalse(result["production_binary_uploaded"])
        self.assertEqual(result["binary_sha256"],m.digest(self.binary))
        self.assertEqual(result["synthetic_evm_chain_id"],999991)
        self.assertNotIn("private_key",result)

    def test_real_production_ids_are_rejected(self):
        bad=copy.deepcopy(self.doc)
        bad["network"]["cosmos_chain_id"]="privi-mainnet-1"
        bad["network"]["evm_chain_id"]=2026101601
        self.config.write_text(json.dumps(bad))
        with self.assertRaises(ValueError):
            self.run_receipt()

    def test_supply_cap_change_is_rejected(self):
        self.doc["coin"]["max_supply_base_units"]=str(10**28)
        self.config.write_text(json.dumps(self.doc))
        with self.assertRaisesRegex(ValueError,"fixed-cap"):
            self.run_receipt()

    def test_incomplete_source_overlay_fails(self):
        self.patch.write_text("diff --git a/evmd/app.go b/evmd/app.go\n")
        with self.assertRaises(ValueError):
            self.run_receipt()

    def test_missing_non_executable_binary_fails(self):
        self.binary.chmod(0o600)
        with self.assertRaises(ValueError):
            self.run_receipt()

    def test_non_pull_request_cannot_issue_receipt(self):
        with self.assertRaises(ValueError):
            m.make_receipt(self.binary,self.patch,self.config,
                           ref="refs/heads/main",commit="a"*40,
                           go_version="go version go1.25.9 linux/amd64")


if __name__=="__main__":
    unittest.main()
