"""No-network synthetic unsigned review bundle and validator gate regressions."""
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sp = importlib.util.spec_from_file_location("verify_render_release_bundle", HERE / "verify_render_release_bundle.py")
verifier = importlib.util.module_from_spec(sp)
sp.loader.exec_module(verifier)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class ReleaseGateTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.bundle = self.root / "bundle"
        self.bundle.mkdir()
        self.manifest_path = self.root / "release.json"
        self.genesis = self.root / "genesis.json"
        self.source = "a" * 40
        self.records = {
            "privi-evmd-UNSIGNED-TEST-ONLY": b"synthetic disposable ELF only - not executable",
            "GO-BUILD-INFO.txt": b"sample pinned Go module report\n",
            "BUILD-PROVENANCE.txt": (
                f"privi_source_commit={self.source}\n"
                "upstream_cosmos_evm_tag=v0.7.3\n"
                "upstream_cosmos_evm_commit=c3ae9067a7eadcdea55a5192226916deb44c71c4\n"
            ).encode(),
            "READ-ME-FIRST.txt": b"UNSIGNED REVIEW ONLY; NOT A PRODUCTION RELEASE",
        }
        self.genesis_data = {"chain_id": "privi-ci-stage-1", "app_state": {"bank": {}}}
        self.manifest = {
            "schema_version": 1,
            "stage": "UNSIGNED_CI_REVIEW_ONLY",
            "operator": "Privi World Corp",
            "node_binary_sha256": sha(self.records["privi-evmd-UNSIGNED-TEST-ONLY"]),
            "genesis_sha256": "",
            "privi_source_commit": self.source,
            "cosmos_chain_id": "privi-ci-stage-1",
            "evm_chain_id": 900900,
            "native_denom": "aprvi",
            "financial_launch_enabled": False,
            "production_ready": False,
            "validator_service_id": "UNASSIGNED",
        }
        self.save()

    def save(self):
        genesis_bytes = (json.dumps(self.genesis_data, sort_keys=True) + "\n").encode()
        self.genesis.write_bytes(genesis_bytes)
        self.manifest["genesis_sha256"] = self.manifest.get("genesis_sha256") or sha(genesis_bytes)
        self.manifest_path.write_text(json.dumps(self.manifest, sort_keys=True) + "\n")
        for name, payload in self.records.items():
            (self.bundle / name).write_bytes(payload)
        self.rehash_bundle()

    def rehash_bundle(self):
        entries = [f"{sha(raw)}  {name}" for name, raw in self.records.items()]
        (self.bundle / "SHA256SUMS").write_text("\n".join(entries) + "\n")

    def verify(self):
        return verifier.verify(self.bundle, self.genesis, self.manifest_path)

    def denied(self, part):
        with self.assertRaisesRegex(verifier.UnsafeRelease, part):
            self.verify()

    def test_valueless_bundle_exact_hashes_and_provenance(self):
        result = self.verify()
        self.assertEqual(result["financial_launch"], "NO_GO")
        self.assertEqual(result["source_commit"], self.source)

    def test_binary_tamper_rejected(self):
        (self.bundle / "privi-evmd-UNSIGNED-TEST-ONLY").write_bytes(b"backdoored bytes")
        self.denied("checksum mismatch")

    def test_binary_changed_with_recomputed_bundle_hash_rejected(self):
        self.records["privi-evmd-UNSIGNED-TEST-ONLY"] = b"other binary"
        self.save()
        self.denied("approved CI hash")

    def test_genesis_tamper_rejected(self):
        self.genesis.write_text('{"chain_id":"wrong-chain","app_state":{}}')
        self.denied("genesis does not match")

    def test_genesis_changed_with_recomputed_hash_still_checks_chain(self):
        self.genesis_data["chain_id"] = "another-chain"
        self.manifest["genesis_sha256"] = ""
        self.save()
        self.denied("genesis chain identity mismatch")

    def test_missing_genesis_application_state_rejected(self):
        del self.genesis_data["app_state"]
        self.manifest["genesis_sha256"] = ""
        self.save()
        self.denied("genesis must carry application state")

    def test_unknown_hashsum_filename_and_path_traversal_rejected(self):
        (self.bundle / "SHA256SUMS").write_text("0" * 64 + "  ../../bad\n")
        self.denied("SHA256SUMS entry")

    def test_duplicate_hashsum_entry_rejected(self):
        path = self.bundle / "SHA256SUMS"
        path.write_text(path.read_text() + path.read_text().splitlines()[0] + "\n")
        self.denied("duplicate SHA256SUMS")

    def test_missing_hashsum_entry_rejected(self):
        path = self.bundle / "SHA256SUMS"
        path.write_text("\n".join(path.read_text().splitlines()[:3]) + "\n")
        self.denied("artifact is incomplete")

    def test_symlinked_unsigned_binary_rejected(self):
        target = self.root / "unsigned.bin"
        target.write_bytes(self.records["privi-evmd-UNSIGNED-TEST-ONLY"])
        binary = self.bundle / "privi-evmd-UNSIGNED-TEST-ONLY"
        binary.unlink()
        binary.symlink_to(target)
        self.denied("regular file")

    def test_provenance_source_mismatch_rejected(self):
        self.manifest["privi_source_commit"] = "b" * 40
        self.save()
        self.denied("source commit differs")

    def test_pinned_upstream_cannot_be_substituted(self):
        self.records["BUILD-PROVENANCE.txt"] = self.records["BUILD-PROVENANCE.txt"].replace(
            b"c3ae9067a7eadcdea55a5192226916deb44c71c4", b"b" * 40
        )
        self.save()
        self.denied("upstream Cosmos EVM commit changed")

    def test_unsigned_warning_required(self):
        self.records["READ-ME-FIRST.txt"] = b"looks good for mainnet!"
        self.save()
        self.denied("warning absent")

    def test_unsafe_production_flags_rejected(self):
        for key, value in (
            ("production_ready", True),
            ("financial_launch_enabled", True),
            ("stage", "PRODUCTION"),
            ("validator_service_id", "srv-production-service"),
            ("native_denom", "atest"),
            ("evm_chain_id", 56),
            ("cosmos_chain_id", "privi-mainnet-1"),
        ):
            with self.subTest(key=key):
                self.manifest[key] = value
                self.save()
                self.denied("denied|test chain|EVM chain")
                self.manifest[key] = {
                    "production_ready": False,
                    "financial_launch_enabled": False,
                    "stage": "UNSIGNED_CI_REVIEW_ONLY",
                    "validator_service_id": "UNASSIGNED",
                    "native_denom": "aprvi",
                    "evm_chain_id": 900900,
                    "cosmos_chain_id": "privi-ci-stage-1",
                }[key]

    def test_extra_sensitive_manifest_field_rejected(self):
        self.manifest["validator_private_key"] = "not-for-github"
        self.save()
        self.denied("missing/unknown fields")

    def test_duplicate_manifest_field_rejected(self):
        p = self.manifest_path
        data = p.read_text()
        p.write_text(data.replace('"operator": "Privi World Corp"',
                                  '"operator": "Privi World Corp", "operator": "other"'))
        self.denied("duplicate JSON property")

    def test_json_nonfinite_rejected(self):
        p = self.manifest_path
        p.write_text(p.read_text().replace('"evm_chain_id": 900900', '"evm_chain_id": NaN'))
        self.denied("nonfinite JSON")

    def test_cli_success_remains_explicitly_no_go(self):
        cmd = [sys.executable, str(HERE / "verify_render_release_bundle.py"),
               "--bundle", str(self.bundle), "--genesis", str(self.genesis),
               "--manifest", str(self.manifest_path)]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn('"financial_launch": "NO_GO"', result.stdout)
        self.assertIn("NONLIVE EVIDENCE ONLY", result.stdout)


if __name__ == "__main__":
    unittest.main()
