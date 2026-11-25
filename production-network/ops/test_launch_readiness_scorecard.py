#!/usr/bin/env python3
"""Tests for launch_readiness_scorecard.py — expects NO-GO verdict."""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

SCORECARD = Path(__file__).resolve().parent / "launch_readiness_scorecard.py"


class LaunchReadinessScorecardTests(unittest.TestCase):
    def test_scorecard_reports_no_go(self):
        proc = subprocess.run(
            [sys.executable, str(SCORECARD)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["verdict"], "NO_GO")
        self.assertIs(data["production_mainnet_activated"], False)
        self.assertIs(data["financial_prvi_issued"], False)
        self.assertEqual(data["blocked_gate_count"], 8)
        for key, gate in data["gates"].items():
            self.assertEqual(gate["status"], "BLOCKED", key)

    def test_engineering_artifacts_counted(self):
        proc = subprocess.run(
            [sys.executable, str(SCORECARD)],
            capture_output=True,
            text=True,
            check=False,
        )
        data = json.loads(proc.stdout)
        self.assertGreaterEqual(data["engineering_artifacts_present"], 1)
        self.assertIn("pop_engine", data["engineering_artifacts"])


if __name__ == "__main__":
    unittest.main()
