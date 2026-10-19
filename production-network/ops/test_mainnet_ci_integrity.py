"""Safety regression for the exact five-job Privi CI workflow.

No GitHub requests, network, keys or deployment. Guards against accidental
duplicate YAML job sections and silently skipping the costly native cap
performance probe. This is structural lint, not a complete YAML parser.
"""
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github" / "workflows" / "privi-localnet-smoke.yml"
EXPECTED = (
    "offline",
    "custom-app-compile",
    "sdk-prvi-capkeeper",
    "upstream-mint-inventory",
    "four-validator",
)

def inspect(text):
    if not text.startswith("name: Privi EVM four-validator smoke test\n"):
        raise ValueError("workflow header missing")
    if text.count("\njobs:\n") != 1:
        raise ValueError("expected exactly one job map")
    if text.count("\non:\n") != 1:
        raise ValueError("workflow must have exactly one event declaration")
    if "\t" in text or "\r" in text:
        raise ValueError("workflow has unsupported indentation/newlines")
    section = text.split("\njobs:\n", 1)[1]
    found = tuple(re.findall(r"(?m)^  ([a-z][a-z0-9-]*):\s*$", section))
    if found != EXPECTED:
        raise ValueError("job identities/count/order must match independently reviewed baseline")
    jobs = {
        name: section.split(f"  {name}:\n", 1)[1].split(
            f"\n  {EXPECTED[i+1]}:\n", 1
        )[0] if i+1<len(EXPECTED) else section.split(f"  {name}:\n",1)[1]
        for i, name in enumerate(EXPECTED)
    }
    sdk = jobs["sdk-prvi-capkeeper"]
    benchmark = "GOTOOLCHAIN=local go test -mod=mod -p 2 -run '^$' -bench '^BenchmarkNativeReconcileScaling$' -benchtime=3x -benchmem -timeout=20m ./..."
    if sdk.count(benchmark) != 1 or text.count(benchmark) != 1:
        raise ValueError("synthetic PRVI conservation benchmark absent or duplicated")
    sdk_bench = "GOTOOLCHAIN=local go test -mod=mod -p 2 -run '^$' -bench '^BenchmarkActualSDKNativeConservationScan$' -benchtime=3x -benchmem -timeout=20m ./..."
    if sdk.count(sdk_bench) != 1 or text.count(sdk_bench) != 1:
        raise ValueError("real SDK IAVL memory-store PRVI benchmark absent or duplicated")
    if sdk.index(benchmark) > sdk.index(sdk_bench):
        raise ValueError("synthetic benchmark should precede real SDK IAVL baseline")
    mandatory_report = 'python3 "$GITHUB_WORKSPACE/production-network/ops/assert_sdk_benchmark_timings.py" --report "$RUNNER_TEMP/privi-sdk-iavl-bench.log"'
    if sdk.count(mandatory_report) != 1:
        raise ValueError("real SDK/IAVL benchmark timing validator must run exactly once")
    if sdk_bench + ' | tee "$RUNNER_TEMP/privi-sdk-iavl-bench.log"' not in sdk:
        raise ValueError("real SDK/IAVL benchmark output must be captured for timing verification")
    disk_bench = "GOTOOLCHAIN=local go test -mod=mod -p 2 -run '^$' -bench '^BenchmarkDiskBackedSDKNativeConservationScan$' -benchtime=3x -benchmem -timeout=20m ./..."
    disk_log = "$RUNNER_TEMP/privi-sdk-leveldb-bench.log"
    disk_report = 'python3 "$GITHUB_WORKSPACE/production-network/ops/assert_sdk_benchmark_timings.py" --profile disk --report "' + disk_log + '"'
    if sdk.count(disk_bench) != 1 or text.count(disk_bench) != 1:
        raise ValueError("committed disk-backed SDK PRVI benchmark absent or duplicated")
    if disk_bench + ' | tee "' + disk_log + '"' not in sdk:
        raise ValueError("disk-backed SDK benchmark output must be captured")
    if sdk.count(disk_report) != 1:
        raise ValueError("disk-backed SDK benchmark validation must run")
    if not sdk.index(mandatory_report) < sdk.index(disk_bench) < sdk.index(disk_report):
        raise ValueError("real bank benchmark ordering must stay enforced")
    if "still NOT disk-backed consensus or production throughput evidence" not in sdk:
        raise ValueError("real SDK benchmark limitations must remain explicit")
    if sdk.count("GOTOOLCHAIN=local go test -mod=mod -p 2 -count=1 -timeout=20m ./...") != 1:
        raise ValueError("real SDK cap tests must precede benchmark")
    if sdk.index("-count=1 -timeout=20m") > sdk.index(benchmark):
        raise ValueError("SDK real tests must run before benchmark")
    if "NOT IAVL or real-host capacity" not in sdk:
        raise ValueError("benchmark limitations must remain explicit")
    for marker in ("GOTOOLCHAIN=local go", "bash production-network/testnet/bootstrap-local-4.sh",
                   "actions/checkout@v4"):
        if marker not in text:
            raise ValueError("missing required build or smoke test action")
    for forbidden in ("actions/upload-artifact", "docker push", "kubectl apply",
                      "scp ", "ssh root@", "terraform apply", "evmd start --home"):
        if forbidden in text:
            raise ValueError("financial deployment/publishing must not be introduced into this CI")
    return jobs


class MainnetCIStructureTests(unittest.TestCase):
    def test_current_five_job_workflow_is_intact(self):
        jobs = inspect(WORKFLOW.read_text(encoding="utf-8"))
        self.assertEqual(set(jobs), set(EXPECTED))

    def test_duplicate_job_sections_fail_closed(self):
        original = WORKFLOW.read_text(encoding="utf-8")
        copied = original + "\n  upstream-mint-inventory:\n    runs-on: ubuntu-24.04\n"
        with self.assertRaisesRegex(ValueError, "job identities"):
            inspect(copied)

    def test_loss_of_benchmark_is_detected(self):
        original = WORKFLOW.read_text(encoding="utf-8")
        modified = original.replace("BenchmarkNativeReconcileScaling", "BenchmarkOther", 1)
        with self.assertRaisesRegex(ValueError, "benchmark"):
            inspect(modified)

    def test_missing_real_sdk_benchmark_is_detected(self):
        original = WORKFLOW.read_text(encoding="utf-8")
        modified = original.replace("BenchmarkActualSDKNativeConservationScan",
                                    "BenchmarkUnreviewedReplacement",1)
        with self.assertRaisesRegex(ValueError, "real SDK IAVL memory-store"):
            inspect(modified)

    def test_skipped_sdk_timing_validator_is_rejected(self):
        original = WORKFLOW.read_text(encoding="utf-8")
        modified = original.replace("assert_sdk_benchmark_timings.py", "skipped_validator.py",1)
        with self.assertRaisesRegex(ValueError, "timing validator"):
            inspect(modified)

    def test_disk_backed_benchmark_cannot_be_silently_removed(self):
        original = WORKFLOW.read_text(encoding="utf-8")
        for replaced in ("BenchmarkDiskBackedSDKNativeConservationScan",
                         "--profile disk"):
            altered = original.replace(replaced, "DISABLED", 1)
            with self.assertRaises(ValueError):
                inspect(altered)

    def test_unexpected_financial_release_action_is_refused(self):
        original = WORKFLOW.read_text(encoding="utf-8")
        modified = original + "\n# actions/upload-artifact"
        with self.assertRaisesRegex(ValueError, "deployment/publishing"):
            inspect(modified)


if __name__ == "__main__":
    unittest.main()
