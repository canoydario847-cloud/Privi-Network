"""Privi Car offline fleet pilot summary; no vehicle identities leave this process.

Usage: python3 privi-car/fleet_pilot_summary.py receipts.json
Reads the LOCAL_DEMO_NOT_ON_CHAIN JSON export from fleet_batch.py.
This is not an attestation of actual vehicle mileage or customer billing.
"""
import json
import pathlib
import sys
from verify_receipt import verify_receipt


def summarize(export):
    if not isinstance(export, dict) or export.get("mode") != "LOCAL_DEMO_NOT_ON_CHAIN":
        raise ValueError("expected a local Privi Car demo export")
    receipts = export.get("receipts")
    rejected = export.get("rejected")
    if not isinstance(receipts, list) or not isinstance(rejected, list):
        raise ValueError("missing receipt or rejection lists")
    if type(export.get("accepted")) is not int or export["accepted"] != len(receipts):
        raise ValueError("accepted count does not match receipts")
    if len(receipts) > 10000 or len(rejected) > 10000:
        raise ValueError("pilot export exceeds 10,000 entries per category")
    valid = 0
    for receipt in receipts:
        if not isinstance(receipt, dict):
            continue
        try:
            ok, _ = verify_receipt(receipt)
        except (ValueError, TypeError, KeyError):
            ok = False
        valid += bool(ok)
    # Pilot triage is advisory only: a clean local export is not proof of genuine telemetry.
    failed = len(receipts) - valid
    needs_review = failed > 0 or len(rejected) > 0
    return {
        "mode": "LOCAL_DEMO_NOT_ON_CHAIN",
        "submitted": len(receipts) + len(rejected),
        "consented_receipts": len(receipts),
        "verified_receipts": valid,
        "failed_verification": failed,
        "requires_operator_review": needs_review,
        "review_reasons": ([ "receipt_integrity_failure" ] if failed else []) + ([ "rejected_input_rows" ] if rejected else []),
        "rejected_rows": len(rejected),
        "production_ready": False,
    }


def main():
    if len(sys.argv) != 2:
        print("Usage: python fleet_pilot_summary.py receipts.json", file=sys.stderr)
        return 2
    try:
        path = pathlib.Path(sys.argv[1])
        if path.stat().st_size > 5_000_000:
            raise ValueError("export exceeds 5 MB demo limit")
        export = json.loads(path.read_text(encoding="utf-8"))
        print(json.dumps(summarize(export), indent=2))
        return 0
    except (OSError, ValueError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
