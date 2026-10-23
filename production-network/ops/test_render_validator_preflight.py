"""Adversarial, offline-only tests for the Render validator candidate gate.

All mock Render IDs, fingerprints, regions and workspace values are fictional.
No Render API calls, paid deployment, signing keys, or financial activation.
"""
import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "render_validator_preflight", HERE / "render_validator_preflight.py"
)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)
CANDIDATE = HERE / "render-validator-candidates.NONLIVE.json"


def complete_mock():
    candidate = checker.read_json(CANDIDATE)
    candidate["workspace_id"] = "tea-synthetic-not-a-real-workspace"
    candidate["release_sha256"] = "a" * 64
    candidate["genesis_sha256"] = "b" * 64
    candidate["cross_region_p2p_security_review"] = "FICTIONAL_REVIEW_ONLY"
    candidate["failure_domain_review"] = "FICTIONAL_REVIEW_ONLY"
    services = []
    for i, item in enumerate(candidate["validators"]):
        region = "virginia" if i % 2 == 0 else "ohio"
        item.update({
            "service_id": f"srv-example-only-{i+1}",
            "region": region,
            "fault_domain": f"sample-domain-{i+1}",
            "consensus_pubkey_sha256": f"{i+1:x}" * 64,
            "signer_security_review": "FICTIONAL_REVIEW_ONLY",
        })
        services.append({
            "id": item["service_id"],
            "ownerId": candidate["workspace_id"],
            "name": item["service_name"],
            "type": "private_service",
            "autoDeploy": "no",
            "suspended": "not_suspended",
            "serviceDetails": {
                "region": region,
                "runtime": "docker",
                "plan": "starter",
                "numInstances": 1,
                "disk": {"id": f"dsk-test-only-{i+1}",
                         "mountPath": "/data", "sizeGB": 20},
            },
        })
    return candidate, services


class RenderValidatorPreflightTests(unittest.TestCase):
    def test_current_manifest_never_claims_production_ready(self):
        manifest = checker.read_json(CANDIDATE)
        errors, blockers, matched = checker.assess(manifest)
        self.assertEqual([], errors)
        self.assertGreater(len(blockers), 10)
        self.assertEqual(matched, 0)
        self.assertFalse(manifest["financial_launch_enabled"])
        self.assertFalse(manifest["production_ready"])
        self.assertEqual("RENDER_PRODUCTION_VALIDATOR_CANDIDATE_NOT_DEPLOYED",
                         manifest["purpose"])

    def test_synthetic_provider_metadata_still_never_approves_financial_launch(self):
        manifest, observations = complete_mock()
        errors, blocks, matches = checker.assess(manifest, observations)
        self.assertEqual([], errors)
        self.assertEqual(matches, 4)
        self.assertTrue(any("mandatory human security" in b for b in blocks))
        # No real signer/host review can ever be inferred from four REST rows.
        self.assertFalse(manifest["production_ready"])

    def test_public_web_service_with_disk_is_never_validator(self):
        manifest, observed = complete_mock()
        observed[0]["type"] = "web_service"
        observed[0]["serviceDetails"]["url"] = "https://sample.onrender.com"
        err, _, _ = checker.assess(manifest, observed)
        self.assertTrue(any("public/non-validator" in x for x in err), err)
        self.assertTrue(any("public onrender.com" in x for x in err), err)

    def test_automatic_deploy_disallowed_both_in_manifest_and_provider(self):
        manifest, observed = complete_mock()
        manifest["validators"][0]["manual_deploy"] = False
        err, _, _ = checker.assess(manifest, observed)
        self.assertTrue(any("auto-deploy forbidden" in x for x in err), err)
        manifest, observed = complete_mock()
        observed[2]["autoDeploy"] = "yes"
        err, _, _ = checker.assess(manifest, observed)
        self.assertTrue(any("auto-deploy must be disabled" in x for x in err), err)

    def test_duplicate_consensus_pubkey_or_render_service_denied(self):
        manifest, observed = complete_mock()
        manifest["validators"][1]["consensus_pubkey_sha256"] = (
            manifest["validators"][0]["consensus_pubkey_sha256"])
        self.assertTrue(any("duplicate consensus_pubkey" in x for x in
                            checker.assess(manifest, observed)[0]))
        manifest, observed = complete_mock()
        manifest["validators"][1]["service_id"] = manifest["validators"][0]["service_id"]
        self.assertTrue(any("duplicate service_id" in x for x in
                            checker.assess(manifest, observed)[0]))

    def test_shared_disk_unsupported_and_unbounded_instances(self):
        manifest, observed = complete_mock()
        observed[1]["serviceDetails"]["disk"]["id"] = (
            observed[0]["serviceDetails"]["disk"]["id"])
        err, _, _ = checker.assess(manifest, observed)
        self.assertTrue(any("share a Render persistent disk" in x for x in err), err)
        manifest, observed = complete_mock()
        observed[3]["serviceDetails"]["numInstances"] = 2
        err, _, _ = checker.assess(manifest, observed)
        self.assertTrue(any("one service instance" in x for x in err), err)

    def test_missing_or_wrong_disk_is_rejected(self):
        for change in (
            lambda d: d.pop("disk"),
            lambda d: d["disk"].update(mountPath="/tmp"),
            lambda d: d["disk"].update(sizeGB=1),
            lambda d: d.update(plan="free"),
            lambda d: d.update(runtime="python"),
        ):
            with self.subTest(change=str(change)):
                manifest, observed = complete_mock()
                change(observed[0]["serviceDetails"])
                err, _, _ = checker.assess(manifest, observed)
                self.assertTrue(err, "unreviewed Render host metadata passed")

    def test_provider_workspace_region_and_service_identity_must_match(self):
        for key, value in (
            ("ownerId", "tea-foreign-workspace"),
            ("name", "privi-ledger"),
            ("type", "static_site"),
        ):
            with self.subTest(key=key):
                manifest, observed = complete_mock()
                observed[0][key] = value
                self.assertTrue(checker.assess(manifest, observed)[0])
        manifest, observed = complete_mock()
        observed[2]["serviceDetails"]["region"] = "oregon"
        self.assertTrue(any("actual region mismatches" in x for x in
                            checker.assess(manifest, observed)[0]))

    def test_rejects_single_region_and_missing_cross_region_review(self):
        manifest, observed = complete_mock()
        for n, svc in enumerate(observed):
            svc["serviceDetails"]["region"] = "virginia"
            manifest["validators"][n]["region"] = "virginia"
        _, blockers, _ = checker.assess(manifest, observed)
        self.assertTrue(any("lack cross-region" in x for x in blockers))
        manifest, observed = complete_mock()
        manifest["cross_region_p2p_security_review"] = "UNASSIGNED"
        _, blockers, _ = checker.assess(manifest, observed)
        self.assertTrue(any("cross-region secure P2P" in x for x in blockers))

    def test_secrets_and_live_state_are_forbidden(self):
        for key, value in (
            ("financial_launch_enabled", True),
            ("production_ready", True),
            ("purpose", "LIVE"),
            ("private_key", "value-redacted"),
        ):
            with self.subTest(key=key):
                manifest, observed = complete_mock()
                manifest[key] = value
                self.assertTrue(checker.assess(manifest, observed)[0])

    def test_provider_id_missing_and_duplicate_provider_rows_fail(self):
        manifest, observed = complete_mock()
        observed.pop()
        _, blockers, _ = checker.assess(manifest, observed)
        self.assertTrue(any("not found in provider" in x for x in blockers))
        manifest, observed = complete_mock()
        observed.append(copy.deepcopy(observed[0]))
        self.assertTrue(any("duplicate Render provider" in x for x in
                            checker.assess(manifest, observed)[0]))

    def test_json_duplicate_keys_fail(self):
        with self.assertRaisesRegex(checker.InvalidCandidate, "duplicate JSON key"):
            json.loads('{"workspace_id":"a","workspace_id":"b"}',
                       object_pairs_hook=checker.unique_json)

    def test_cli_draft_accepts_structure_not_launch(self):
        out = subprocess.run(
            [sys.executable, str(HERE / "render_validator_preflight.py"),
             str(CANDIDATE), "--mode", "draft"],
            capture_output=True, text=True, check=False)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("NONLIVE DRAFT STRUCTURE ACCEPTED", out.stdout)
        self.assertIn("FINANCIAL MAINNET: NOT LIVE", out.stdout)

    def test_cli_provider_observations_and_production_always_no_go(self):
        manifest, observed = complete_mock()
        with tempfile.TemporaryDirectory() as td:
            p1, p2 = Path(td) / "candidate.json", Path(td) / "services.json"
            p1.write_text(json.dumps(manifest), encoding="utf-8")
            p2.write_text(json.dumps(observed), encoding="utf-8")
            for mode in ("observe", "production"):
                args = [
                    sys.executable, str(HERE / "render_validator_preflight.py"),
                    str(p1), "--mode", mode, "--render-services", str(p2),
                ]
                out = subprocess.run(args, capture_output=True, text=True)
                self.assertEqual(out.returncode, 3, out.stdout + out.stderr)
                self.assertIn("provider_matches=4/4", out.stdout)
                self.assertIn("NO-GO", out.stdout)

    def test_cli_observe_requires_explicit_provider_snapshot(self):
        out = subprocess.run(
            [sys.executable, str(HERE / "render_validator_preflight.py"),
             str(CANDIDATE), "--mode", "observe"], capture_output=True, text=True)
        self.assertEqual(out.returncode, 2)
        self.assertIn("explicit Render provider JSON", out.stdout)


if __name__ == "__main__":
    unittest.main()
