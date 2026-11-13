"""Verify an offline Privi Car fleet export before sharing with a pilot customer.

Usage: python verify_fleet_export.py receipts.json
This checks structural integrity and receipt hashes, not vehicle authenticity,
operator authorization, or blockchain anchoring.
"""
import json
import pathlib
import sys
from verify_receipt import verify_receipt


def verify_export(document):
    if not isinstance(document, dict) or set(document) != {"mode", "accepted", "rejected", "receipts"}:
        return False, "Invalid fleet export structure"
    if document["mode"] != "LOCAL_DEMO_NOT_ON_CHAIN":
        return False, "Unsupported export mode"
    receipts, rejected, count = document["receipts"], document["rejected"], document["accepted"]
    if not isinstance(receipts, list) or not isinstance(rejected, list):
        return False, "Invalid receipt or rejection list"
    if type(count) is not int or count != len(receipts):
        return False, "Accepted count mismatch"
    if any(not isinstance(item, dict) or set(item) != {"line", "reason"} or type(item["line"]) is not int or item["line"] < 2 or not isinstance(item["reason"], str) for item in rejected):
        return False, "Invalid rejected row metadata"
    for index, receipt in enumerate(receipts, 1):
        valid, reason = verify_receipt(receipt)
        if not valid:
            return False, f"Receipt {index} invalid: {reason}"
    return True, f"Verified {count} local-demo receipts; {len(rejected)} rejected rows"


def main():
    if len(sys.argv) != 2:
        print("Usage: python verify_fleet_export.py receipts.json", file=sys.stderr)
        return 2
    try:
        document = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
        valid, reason = verify_export(document)
    except (OSError, ValueError) as exc:
        print(f"Invalid input: {exc}", file=sys.stderr)
        return 2
    print(reason)
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
