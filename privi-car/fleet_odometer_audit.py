"""Offline, privacy-minimizing Privi Car fleet odometer consistency audit.

Local demo only: integrity checks do not authenticate vehicle origin.
Only aggregate counts leave this tool; no vehicle pseudonyms or mileage values
are included in the report. No network, payment, or vehicle access.
"""
import argparse
import datetime
import json
import pathlib
import sys

from verify_receipt import verify_receipt

MAX_RECEIPTS = 10000
MAX_BYTES = 5_000_000


def audit(export):
    if type(export) is not dict or export.get("mode") != "LOCAL_DEMO_NOT_ON_CHAIN":
        raise ValueError("expected local demo fleet export")
    receipts = export.get("receipts")
    rejected = export.get("rejected")
    if type(receipts) is not list or type(rejected) is not list:
        raise ValueError("missing receipts/rejected arrays")
    if len(receipts) > MAX_RECEIPTS or len(rejected) > MAX_RECEIPTS:
        raise ValueError("pilot export too large")
    if type(export.get("accepted")) is not int or export["accepted"] != len(receipts):
        raise ValueError("accepted count does not match receipt list")

    by_vehicle = {}
    invalid = 0
    for receipt in receipts:
        try:
            ok, _ = verify_receipt(receipt)
        except (ValueError, TypeError, KeyError, OverflowError):
            ok = False
        if not ok:
            invalid += 1
            continue
        event = receipt["event"]
        timestamp = datetime.datetime.fromisoformat(
            event["recorded_at"]).astimezone(datetime.timezone.utc)
        by_vehicle.setdefault(event["vehicle_pseudonym"], []).append(
            (timestamp, event["odometer_km"], receipt["sha256"]))

    rollbacks = 0
    conflicting_observations = 0
    exact_duplicates = 0
    vehicles_with_anomalies = 0
    for readings in by_vehicle.values():
        readings.sort(key=lambda row: (row[0], row[1], row[2]))
        seen = set()
        prev_time = None
        prev_km = None
        anomalous = False
        for time, km, digest in readings:
            if digest in seen:
                exact_duplicates += 1
                anomalous = True
                continue
            seen.add(digest)
            if prev_time is not None:
                if time == prev_time and km != prev_km:
                    conflicting_observations += 1
                    anomalous = True
                elif time > prev_time and km < prev_km:
                    rollbacks += 1
                    anomalous = True
            prev_time, prev_km = time, km
        vehicles_with_anomalies += int(anomalous)

    needs_review = any((invalid, rollbacks, conflicting_observations,
                        exact_duplicates, len(rejected)))
    return {
        "mode": "LOCAL_DEMO_NOT_ON_CHAIN",
        "status": "ADVISORY_ONLY_NOT_PROOF_OF_VEHICLE_ORIGIN",
        "receipt_count": len(receipts),
        "verified_receipt_count": len(receipts) - invalid,
        "invalid_receipt_count": invalid,
        "vehicle_pseudonym_count": len(by_vehicle),
        "odometer_decrease_count": rollbacks,
        "same_timestamp_conflict_count": conflicting_observations,
        "duplicate_receipt_count": exact_duplicates,
        "vehicle_pseudonyms_flagged_count": vehicles_with_anomalies,
        "rejected_input_row_count": len(rejected),
        "requires_operator_review": bool(needs_review),
        "production_ready": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export_json", help="Local fleet_batch.py demo export")
    args = parser.parse_args(argv)
    try:
        path = pathlib.Path(args.export_json)
        if path.stat().st_size > MAX_BYTES:
            raise ValueError("demo export exceeds 5 MB")
        export = json.loads(path.read_text(encoding="utf-8"))
        print(json.dumps(audit(export), sort_keys=True, indent=2))
        return 0
    except (OSError, ValueError, TypeError) as exc:
        print(f"Invalid pilot export: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
