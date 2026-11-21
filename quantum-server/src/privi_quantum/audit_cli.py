# Copyright (c) 2026 Privi World Corp. All rights reserved.
# Made by Dario Canoy.
"""Offline Privi Quantum certificate-audit CLI: zero network and no IBM keys.

Example from repo root:
 PYTHONPATH=quantum-server/src python -m privi_quantum.audit_cli \
   --bundle certificate.json --pins independently_verified_keys.json \
   --hardware hardware_receipt.json --readback ibm_readback.json \
   --binding ibm_input_binding.json --qasm compiled.qasm

Exit 0 = valid scoped Privi signature and hash consistency ONLY.
Exit 1 = verification failure. Exit 2 = invalid file/options.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .offline_audit import audit_evidence_chain

MAX_FILE=300_000


def _load(path):
    p=Path(path)
    if not p.is_file() or p.stat().st_size>MAX_FILE:
        raise ValueError("Input JSON file absent or exceeds size limit")
    obj=json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(obj,dict):
        raise ValueError("Every evidence input must be a JSON object")
    return obj


def main(argv=None):
    parser=argparse.ArgumentParser(description="Audit an existing Privi-signed IBM evidence chain offline")
    parser.add_argument("--bundle",required=True)
    parser.add_argument("--pins",required=True,help="Public keys independently obtained and verified")
    parser.add_argument("--hardware",required=True)
    parser.add_argument("--readback",required=True)
    parser.add_argument("--binding",required=True)
    parser.add_argument("--qasm",help="Optional compiled OpenQASM file for digest verification")
    parser.add_argument("--synthetic-demo",action="store_true",help="Explicitly allow disposable synthetic test certificates; never grants production trust")
    args=parser.parse_args(argv)
    try:
        evidence={
            "bundle":_load(args.bundle),
            "pinned_issuer_keys":_load(args.pins),
            "hardware_receipt":_load(args.hardware),
            "ibm_readback":_load(args.readback),
            "input_binding":_load(args.binding),
            "allow_synthetic_demo":args.synthetic_demo,
        }
        if args.qasm:
            p=Path(args.qasm)
            if not p.is_file() or p.stat().st_size>200_000:
                raise ValueError("Compiled QASM missing or oversized")
            evidence["compiled_qasm"]=p.read_bytes().decode("utf-8")
        result=audit_evidence_chain(**evidence)
    except (OSError,ValueError,UnicodeError,TypeError) as exc:
        print("Offline audit input error: "+str(exc),file=sys.stderr)
        return 2
    print(json.dumps(result,sort_keys=True,indent=2))
    return 0 if result["valid"] else 1


if __name__=="__main__":
    sys.exit(main())
