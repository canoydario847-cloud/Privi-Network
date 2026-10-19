#!/usr/bin/env python3
"""Verify SDK/IAVL benchmark actually reports nonzero timed operations.

A prior build passed while the Go benchmark called StopTimer and ResetTimer
without StartTimer, producing 0 B/op and no ns/op. This parser is offline;
it is NOT a performance pass threshold, an IAVL disk stress test, or
financial mainnet authorization.
"""
import argparse
import math
import re
from pathlib import Path

CASES = (100, 1000, 5000)
LINE = re.compile(
    r"^BenchmarkActualSDKNativeConservationScan/"
    r"iavl-account-records-(?P<records>\d+)-(?P<parallelism>\d+)"
    r"\s+(?P<iterations>\d+)\s+(?P<time>\d+(?:\.\d+)?)\s+ns/op(?:\s|$)"
)


def verify(output: str):
    if not isinstance(output, str) or len(output) > 2_000_000:
        raise ValueError("SDK benchmark output absent or oversized")
    results = {}
    for raw in output.splitlines():
        if not raw.startswith("BenchmarkActualSDKNativeConservationScan/"):
            continue
        found = LINE.match(raw)
        if found is None:
            raise ValueError("SDK benchmark has no valid ns/op measurement")
        size = int(found.group("records"))
        if size not in CASES or size in results:
            raise ValueError("unexpected or duplicate SDK benchmark case")
        count = int(found.group("iterations"))
        duration = float(found.group("time"))
        if count < 1 or not math.isfinite(duration) or duration <= 0:
            raise ValueError("SDK benchmark was not timed with positive iterations")
        results[size] = duration
    if set(results) != set(CASES):
        raise ValueError("missing SDK/IAVL benchmark timing cases")
    # Variation by runner/GC/cache is expected. NO thresholds on ns/op here.
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report", required=True, type=Path)
    ns = ap.parse_args()
    try:
        if ns.report.is_symlink() or not ns.report.is_file():
            raise ValueError("expected existing non-symlink benchmark log")
        if ns.report.stat().st_size > 2_000_000:
            raise ValueError("benchmark log exceeds offline review bound")
        measured = verify(ns.report.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        print("BENCHMARK TIMING NO-GO:", type(exc).__name__, str(exc))
        return 2
    print("PASS: all three actual SDK/IAVL memory-store benchmark variants")
    for size in CASES:
        print(f"  {size} unrelated token balances: {measured[size]:g} ns/op")
    print("Synthetic in-memory measurement only; NO financial mainnet capacity claim.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
