"""Offline privacy-minimizing Privi Car pilot report; never vehicle proof.

Generates an operator-facing text summary from an existing local fleet export.
No network calls, API keys, payments, or raw mileage/vehicle identifiers in output.
"""
import argparse
import json
import pathlib
import sys

from fleet_odometer_audit import MAX_BYTES, audit


def render_report(summary):
    """Render only audited aggregate counters; never echo untrusted raw fields."""
    if type(summary) is not dict or summary.get("status") != (
            "ADVISORY_ONLY_NOT_PROOF_OF_VEHICLE_ORIGIN"):
        raise ValueError("verified offline audit summary required")
    fields = (
        ("Receipts reviewed", "receipt_count"),
        ("Receipts with valid integrity hashes", "verified_receipt_count"),
        ("Invalid receipts", "invalid_receipt_count"),
        ("Vehicle pseudonyms in valid receipts", "vehicle_pseudonym_count"),
        ("Decreasing odometer observations", "odometer_decrease_count"),
        ("Conflicting readings at one timestamp", "same_timestamp_conflict_count"),
        ("Duplicate receipts", "duplicate_receipt_count"),
        ("Vehicle pseudonyms with anomalies", "vehicle_pseudonyms_flagged_count"),
        ("Rejected input rows", "rejected_input_row_count"),
    )
    for _, key in fields:
        value = summary.get(key)
        if type(value) is not int or value < 0:
            raise ValueError("invalid aggregate audit count")
    if type(summary.get("requires_operator_review")) is not bool:
        raise ValueError("invalid audit review flag")
    lines = [
        "PRIVI CAR | OFFLINE MILEAGE RECORD REVIEW",
        "Advisory pilot report — not verified vehicle telemetry",
        "",
        "Result: " + (
            "HUMAN REVIEW RECOMMENDED" if summary["requires_operator_review"]
            else "NO ANOMALIES FOUND IN SUBMITTED RECORDS"
        ),
        "",
    ]
    lines.extend(f"{label}: {summary[key]}" for label, key in fields)
    lines.extend([
        "",
        "Suggested next step: " + (
            "Ask the consenting owner or fleet operator to check original "
            "maintenance logs and correct or explain flagged records."
            if summary["requires_operator_review"] else
            "Keep the source records and obtain the owner's permission "
            "before any additional sharing."
        ),
        "",
        "LIMITATIONS: Hash integrity does not authenticate vehicle origin, "
        "mileage accuracy, odometer hardware, ownership, or consent history.",
        "No live vehicle connection, payment processing, or blockchain write.",
        "This report contains aggregate counts only; keep raw records local.",
    ])
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export_json", help="Local Privi Car fleet demo export")
    parser.add_argument("--output", help="Optional local .txt report path")
    args = parser.parse_args(argv)
    try:
        path = pathlib.Path(args.export_json)
        if path.stat().st_size > MAX_BYTES:
            raise ValueError("demo export exceeds 5 MB")
        summary = audit(json.loads(path.read_text(encoding="utf-8")))
        report = render_report(summary)
        if args.output:
            destination = pathlib.Path(args.output)
            if destination.suffix.lower() != ".txt":
                raise ValueError("report destination must end in .txt")
            if destination.resolve() == path.resolve():
                raise ValueError("cannot overwrite source export")
            # Exclusive creation: never overwrite an existing customer report,
            # source export, or symlink target. Operators must choose a new name.
            with destination.open("x", encoding="utf-8") as handle:
                handle.write(report)
        else:
            print(report, end="")
        return 0
    except (OSError, ValueError, TypeError) as exc:
        print(f"Pilot report rejected: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
