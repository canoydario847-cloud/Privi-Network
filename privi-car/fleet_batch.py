"""Privi Car offline fleet receipt batch export (stdlib only).

CSV headers: vehicle_id,odometer_km,consent. Only explicit 'yes' rows are
processed. Use demo- prefixed identifiers, never VINs or driver identities.
Output is local-demo receipts, not blockchain attestations.
Usage: python3 privi-car/fleet_batch.py input.csv receipts.json
"""
import csv
import json
import pathlib
import sys
from consent_receipt_demo import make_receipt
from verify_receipt import verify_receipt


def process_rows(rows):
    receipts, rejected = [], []
    for line, row in enumerate(rows, start=2):
        if set(row) != {"vehicle_id", "odometer_km", "consent"}:
            raise ValueError("CSV must have exactly vehicle_id,odometer_km,consent columns")
        if row["consent"].strip().lower() != "yes":
            rejected.append({"line": line, "reason": "no explicit consent"})
            continue
        try:
            vehicle_id = row["vehicle_id"].strip()
            if not vehicle_id.startswith("demo-") or len(vehicle_id) <= len("demo-") or len(vehicle_id) > 80:
                raise ValueError("use a nonempty demo- prefixed pseudonymous ID of at most 80 characters")
            if not row["odometer_km"].strip().isdigit():
                raise ValueError("odometer must be a nonnegative integer")
            receipt = make_receipt(vehicle_id, int(row["odometer_km"]), True)
            if not verify_receipt(receipt)[0]:
                raise ValueError("receipt failed verification")
            receipts.append(receipt)
        except (ValueError, PermissionError) as exc:
            rejected.append({"line": line, "reason": str(exc)})
    return {"mode": "LOCAL_DEMO_NOT_ON_CHAIN", "accepted": len(receipts), "rejected": rejected, "receipts": receipts}


def main():
    if len(sys.argv) != 3:
        print("Usage: python fleet_batch.py input.csv receipts.json", file=sys.stderr)
        return 2
    src, dest = map(pathlib.Path, sys.argv[1:])
    if src.resolve() == dest.resolve():
        print("Input and output paths must differ", file=sys.stderr)
        return 2
    try:
        with src.open(newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            expected = {"vehicle_id", "odometer_km", "consent"}
            if reader.fieldnames is None or len(reader.fieldnames) != 3 or set(reader.fieldnames) != expected:
                raise ValueError("CSV header must contain exactly one each of vehicle_id,odometer_km,consent")
            result = process_rows(reader)
        dest.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError, csv.Error) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"Accepted {result['accepted']}; rejected {len(result['rejected'])}; saved {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
