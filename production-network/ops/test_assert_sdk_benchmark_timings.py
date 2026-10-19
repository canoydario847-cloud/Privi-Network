"""Offline adversarial tests of actual SDK benchmark timing report validation."""
import unittest

from assert_sdk_benchmark_timings import verify


def row(size, nanos, n=3):
    return (
        "BenchmarkActualSDKNativeConservationScan/"
        f"iavl-account-records-{size}-4\t{n}\t{nanos} ns/op"
        "\t512 B/op\t3 allocs/op\n"
    )


class SDKBenchmarkTimingTests(unittest.TestCase):
    def setUp(self):
        self.valid = "".join(row(n, dur) for n, dur in
                             ((100, 1000), (1000, 3000), (5000, 50000)))

    def test_all_three_nonzero_timings(self):
        self.assertEqual(verify(self.valid), {100: 1000, 1000: 3000, 5000: 50000})

    def test_missing_any_result_is_failure(self):
        for size in (100, 1000, 5000):
            trimmed = "".join(line + "\n" for line in self.valid.splitlines()
                              if f"records-{size}-" not in line)
            with self.assertRaisesRegex(ValueError, "missing SDK"):
                verify(trimmed)

    def test_go_zero_timer_bug_is_failure(self):
        invalid = "".join(
            "BenchmarkActualSDKNativeConservationScan/"
            f"iavl-account-records-{n}-4\t3\t0 B/op\t0 allocs/op\n"
            for n in (100, 1000, 5000)
        )
        with self.assertRaisesRegex(ValueError, "no valid ns/op"):
            verify(invalid)

    def test_zero_duration_or_zero_repetitions(self):
        for bad in (row(100, 0), row(100, 10, n=0), row(100, "NaN")):
            edited = self.valid.replace(row(100, 1000), bad)
            with self.assertRaises(ValueError):
                verify(edited)

    def test_duplicate_and_extra_case_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            verify(self.valid + row(100, 88))
        with self.assertRaisesRegex(ValueError, "unexpected"):
            verify(self.valid + row(9000, 88))

    def test_generic_go_pass_is_not_measurement(self):
        with self.assertRaisesRegex(ValueError, "missing SDK"):
            verify("PASS\nok \tgithub.com/cosmos/evm/evmd/prvicap\t0.02s\n")

    def test_extra_warning_and_synthetic_results_not_interpreted(self):
        report = (
            "PASS\n"
            "BenchmarkNativeReconcileScaling/balance-records-100000-4 3 833 ns/op\n"
            + self.valid
        )
        self.assertEqual(len(verify(report)), 3)

    def test_disk_profile_reports_real_timed_committed_state(self):
        report = "".join(
            f"BenchmarkDiskBackedSDKNativeConservationScan/committed-accounts-{count}-4\\t3\\t{duration} ns/op\\t4096 B/op\\t30 allocs/op\\n"
            for count, duration in ((100, 30000), (1000, 100000), (5000, 900000))
        )
        self.assertEqual(verify(report, profile="disk"), {
            100: 30000, 1000: 100000, 5000: 900000,
        })
        with self.assertRaisesRegex(ValueError, "missing SDK"):
            verify(report, profile="memory")
        with self.assertRaisesRegex(ValueError, "unrecognized"):
            verify(report, profile="unknown")

    def test_disk_profile_rejects_missing_or_stopped_timer(self):
        sample = "".join(
            f"BenchmarkDiskBackedSDKNativeConservationScan/committed-accounts-{n}-4\\t3\\t0 B/op\\t0 allocs/op\\n"
            for n in (100, 1000, 5000)
        )
        with self.assertRaisesRegex(ValueError, "no valid ns/op"):
            verify(sample, profile="disk")

    def test_no_benchmark_data_and_oversized_input_fail(self):
        for value in ("", 123, "X" * 2_000_001):
            with self.assertRaises(ValueError):
                verify(value)


if __name__ == "__main__":
    unittest.main()
