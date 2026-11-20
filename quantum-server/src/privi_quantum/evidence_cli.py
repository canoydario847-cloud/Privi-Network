# Copyright (c) 2026 Privi World Corp. All rights reserved.
# Made by Dario Canoy.
"""Offline, no-credentials Quantum Evidence Lab CLI.

Usage:
  PYTHONPATH=quantum-server/src python -m privi_quantum.evidence_cli \
      quantum-server/examples/evidence-demo.json

This uses only classical simulation, never connects to IBM or any paid QPU.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .evidence_lab import evaluate
from .qaoa import Qubo, ProblemError


def main(argv=None):
    parser = argparse.ArgumentParser(description="Verify QAOA against independent QASM simulation")
    parser.add_argument("input", help="JSON file containing Q, offset, gammas, betas, optional qasm and counts")
    parser.add_argument("--output", help="Optional JSON evidence-report destination")
    args = parser.parse_args(argv)
    try:
        path = Path(args.input)
        if not path.is_file() or path.stat().st_size > 65536:
            raise ProblemError("Input must be a local JSON file smaller than 64 KB")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ProblemError("Input must be a JSON object")
        q = Qubo(data["Q"], data.get("offset", 0.0))
        report = evaluate(q, data["gammas"], data["betas"],
                          qasm=data.get("qasm"), counts=data.get("counts"))
    except (KeyError, ValueError, TypeError, OSError) as exc:
        print(f"Evidence Lab rejected input: {exc}", file=sys.stderr)
        return 2
    output = json.dumps(report, sort_keys=True, indent=2, allow_nan=False)
    if args.output:
        try:
            dest = Path(args.output)
            dest.write_text(output + "\n", encoding="utf-8")
        except OSError as exc:
            print(f"Cannot write report: {exc}", file=sys.stderr)
            return 2
    else:
        print(output)
    # Never signal success for an altered circuit.
    return 0 if report["verification"]["passed"] else 3


if __name__ == "__main__":
    sys.exit(main())
