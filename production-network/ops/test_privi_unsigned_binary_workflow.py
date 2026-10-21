"""Guard the unsigned Privi binary review artifact workflow against release drift.

This has no cloud, signing or deployment actions. It checks only the
reviewed workflow layout; it is not a Go binary security certification.
"""
from pathlib import Path
import unittest

WF = Path(__file__).resolve().parents[2] / ".github/workflows/privi-unsigned-binary.yml"

REQUIRED_ORDER = (
    "git clone --depth 1 --branch v0.7.3",
    'test "$(git -C "$RUNNER_TEMP/.upstream-capbuild" rev-parse HEAD)"',
    "production-network/mainnet/custom-app/apply_prvi_cap.py",
    "production-network/mainnet/custom-app/patch_pinned_erc20_mutations.py",
    "production-network/mainnet/custom-app/patch_sdk_bank_source.py",
    "GOTOOLCHAIN=local go list -m -json github.com/cosmos/cosmos-sdk",
    "GOTOOLCHAIN=local go test",
    "cmp \"$RUNNER_TEMP/privi-unsigned-test-binary/privi-evmd-UNSIGNED-TEST-ONLY\"",
    "privi_cap_genesis_probe_main.go",
    "privi_cap_genesis_positive_probe_main.go",
    "PRIVI_ERC20_NEGATIVE_PROBE=permissionless",
    "PRIVI_ERC20_NEGATIVE_PROBE=native-pair",
    "production-network/mainnet/custom-app/verify_privi_sdk_binary.py",
    "sha256sum -c SHA256SUMS",
    "uses: actions/upload-artifact@v4",
)


def validate_workflow(text):
    if not isinstance(text, str) or len(text) > 30000:
        raise ValueError("binary workflow is absent or oversized")
    if "  pull_request:\n" not in text or "  workflow_dispatch:\n" not in text:
        raise ValueError("unsigned build requires reviewed PR or manual dispatch")
    if "  push:\n" in text or "schedule:" in text:
        raise ValueError("unreviewed automatic unsigned binary release")
    if "permissions:\n  contents: read" not in text:
        raise ValueError("workflow must have read-only GitHub permissions")
    if text.count("uses: actions/upload-artifact@v4") != 1:
        raise ValueError("exactly one bounded artifact uploader required")
    if "retention-days: 3" not in text or "if-no-files-found: error" not in text:
        raise ValueError("artifact expiration or existence checks missing")
    if "name: privi-unsigned-custom-node-TEST-ONLY" not in text:
        raise ValueError("unsigned artifact classification changed")
    if "NOT A PRODUCTION RELEASE" not in text or "known supply-neutral unauthorized-account mutation gap" not in text:
        raise ValueError("security warning may not be removed")
    for forbidden in ("docker push", "kubectl apply", "terraform apply",
                      "ssh root@", "git push", "mainnet start", "evmd start",
                      "PRIVI_BOOTSTRAP_TOKENS_JSON", "priv_validator_key.json",
                      "actions/download-artifact", "curl -X POST"):
        if forbidden in text:
            raise ValueError("unexpected deployment or signing credentials in build workflow")
    positions=[]
    for marker in REQUIRED_ORDER:
        if text.count(marker) != 1:
            raise ValueError("missing or duplicated release dependency: " + marker)
        positions.append(text.index(marker))
    if positions != sorted(positions):
        raise ValueError("artifact uploaded before all required build/security checks")
    return True


class UnsignedNodeWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.good = WF.read_text(encoding="utf-8")

    def test_reviewed_workflow_structure(self):
        self.assertTrue(validate_workflow(self.good))

    def test_negative_genesis_tests_cannot_be_omitted(self):
        with self.assertRaises(ValueError):
            validate_workflow(self.good.replace("privi_cap_genesis_probe_main.go",
                                                "disabled-negative-test.go", 1))

    def test_hardened_sdk_and_artifact_proof_are_mandatory(self):
        for marker in ("production-network/mainnet/custom-app/patch_sdk_bank_source.py",
                       "GOTOOLCHAIN=local go list -m -json github.com/cosmos/cosmos-sdk",
                       "production-network/mainnet/custom-app/verify_privi_sdk_binary.py"):
            with self.subTest(marker=marker):
                with self.assertRaises(ValueError):
                    validate_workflow(self.good.replace(marker,"SECURITY_BYPASS",1))

    def test_checksum_validation_cannot_be_removed(self):
        with self.assertRaises(ValueError):
            validate_workflow(self.good.replace("sha256sum -c SHA256SUMS",
                                                "echo checksum-skipped", 1))

    def test_no_long_lived_download(self):
        with self.assertRaises(ValueError):
            validate_workflow(self.good.replace("retention-days: 3", "retention-days: 90", 1))

    def test_unreviewed_upstream_mutation_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_workflow(self.good.replace("git clone --depth 1 --branch v0.7.3",
                                                "git clone --depth 1 --branch main", 1))

    def test_duplicate_artifact_uploader_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_workflow(self.good + "\n      - uses: actions/upload-artifact@v4")

    def test_unexpected_financial_network_start_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_workflow(self.good + "\n# evmd start")

    def test_write_permission_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_workflow(self.good.replace("contents: read", "contents: write", 1))


if __name__ == "__main__":
    unittest.main()
