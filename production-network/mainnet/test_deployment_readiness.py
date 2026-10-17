#!/usr/bin/env python3
"""Prove financial deployment remains BLOCKED with incomplete or mismatched inputs."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("privi_deploycheck",HERE/"deployment_readiness.py")
gate=importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def load(name):
    return json.loads((HERE/name).read_text(encoding="utf-8"))


class DeploymentSafetyTests(unittest.TestCase):
    def test_existing_design_config_is_not_financially_deployable(self):
        manifest=load("manifest.example.json")
        config=load("privi_chain_config.json")
        release=load("operator-kit/release.template.json")
        roster=load("operator_roster.template.json")
        failures=gate.check_consistency(manifest,config,release,roster)
        self.assertTrue(any("not an independently audited" in v for v in failures))
        self.assertTrue(any("operator" in v for v in failures))
        self.assertTrue(any("chain IDs" in v for v in failures))

    def test_synthetic_ci_candidate_identifiers_can_never_authorize_financial_release(self):
        m = load("manifest.example.json")
        c = load("privi_chain_config.json")
        r = load("operator-kit/release.template.json")
        c["status"] = gate.RELEASE_STATUS
        c["network"]["cosmos_chain_id"] = "privi-ci-nonproduction-999"
        c["network"]["evm_chain_id"] = 999991
        m["network"]["cosmos_chain_id"] = c["network"]["cosmos_chain_id"]
        m["network"]["evm_chain_id"] = c["network"]["evm_chain_id"]
        r["cosmos_chain_id"] = c["network"]["cosmos_chain_id"]
        r["evm_chain_id"] = c["network"]["evm_chain_id"]
        failures = gate.check_consistency(m, c, r, load("operator_roster.template.json"))
        self.assertTrue(any("distinct mainnet Cosmos" in e for e in failures))
        self.assertTrue(any("distinct mainnet EVM" in e for e in failures))
        manifest_failures = gate.preflight.check_manifest(m)
        self.assertTrue(any("non-demo Cosmos" in e for e in manifest_failures))
        self.assertTrue(any("non-demo EVM" in e for e in manifest_failures))
        r.update({"canonical_genesis_sha256": "a"*64,
                  "binary_sha256": "b"*64, "allocations_sha256": "c"*64})
        with self.assertRaisesRegex(ValueError, "unreviewed Cosmos"):
            gate.ceremony.check_release(r)

    def test_existing_test_chain_identifiers_remain_forbidden(self):
        config=load("privi_chain_config.json")
        config["status"]=gate.RELEASE_STATUS
        config["network"]["cosmos_chain_id"]="local-privi-seven-4221"
        config["network"]["evm_chain_id"]=262144
        m=load("manifest.example.json")
        m["network"]["cosmos_chain_id"]="local-privi-seven-4221"
        m["network"]["evm_chain_id"]=262144
        r=load("operator-kit/release.template.json")
        r["cosmos_chain_id"]="local-privi-seven-4221"
        r["evm_chain_id"]=262144
        failures=gate.check_consistency(m,config,r,load("operator_roster.template.json"))
        self.assertTrue(any("distinct mainnet Cosmos" in v for v in failures))
        self.assertTrue(any("distinct mainnet EVM" in v for v in failures))

    def test_same_cosmos_id_must_bind_config_manifest_and_signed_release(self):
        config=load("privi_chain_config.json")
        config["status"]=gate.RELEASE_STATUS
        config["network"]["cosmos_chain_id"]="privi-review-only-1"
        config["network"]["evm_chain_id"]=2026101601
        m=load("manifest.example.json")
        m["network"]["cosmos_chain_id"]="privi-review-only-1"
        m["network"]["evm_chain_id"]=2026101601
        r=load("operator-kit/release.template.json")
        r["cosmos_chain_id"]="privi-other-1"
        r["evm_chain_id"]=2026101601
        failures=gate.check_consistency(m,config,r,load("operator_roster.template.json"))
        self.assertTrue(any("Cosmos chain IDs must agree" in v for v in failures))

    def test_incomplete_genesis_roster_and_ceremony_cannot_pass(self):
        m=load("manifest.example.json")
        config=load("privi_chain_config.json")
        release=load("operator-kit/release.template.json")
        roster=load("operator_roster.template.json")
        attest=load("operator-kit/attestations.template.json")
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            genesis=root/"genesis.json"
            ledger=root/"allocations.json"
            binary=root/"node"
            genesis.write_text('{"chain_id":"local-privi-seven-4221","app_state":{}}')
            ledger.write_text('{"allocations":[]}')
            binary.write_bytes(b"wrong")
            failures=gate.assess(m,config,genesis,ledger,binary,release,roster,attest)
        self.assertGreater(len(failures),10)
        self.assertTrue(any("canonical_genesis_sha256" in v for v in failures))
        self.assertTrue(any("operator" in v.lower() for v in failures))
        self.assertTrue(any("attestation" in v.lower() for v in failures))

    def test_ledger_binary_and_config_cannot_be_self_certified(self):
        m=load("manifest.example.json")
        config=load("privi_chain_config.json")
        config["status"]=gate.RELEASE_STATUS
        r=load("operator-kit/release.template.json")
        r["canonical_genesis_sha256"]="a"*64
        r["binary_sha256"]="b"*64
        r["allocations_sha256"]="c"*64
        m["network"]["canonical_genesis_sha256"]="d"*64
        m["network"]["cosmos_evm_binary_sha256"]="e"*64
        m["distribution"]["allocations_sha256"]="f"*64
        errs=gate.check_consistency(m,config,r,load("operator_roster.template.json"))
        self.assertTrue(any("Release binary_sha256 differs" in v for v in errs))
        self.assertTrue(any("Release canonical_genesis_sha256 differs" in v for v in errs))
        self.assertTrue(any("Release allocation hash differs" in v for v in errs))


if __name__=="__main__":
    unittest.main()
