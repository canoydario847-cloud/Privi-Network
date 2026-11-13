"""Offline Privi Car receipt verifier; no network, vehicle, or blockchain access.

Usage: python3 privi-car/verify_receipt.py receipt.json
Input: JSON object emitted by consent_receipt_demo.py.
Checks canonical SHA-256 integrity and minimal schema constraints.
A matching hash is NOT an authenticated signature or proof of actual mileage.
"""
import argparse
import hashlib
import json
import sys

REQUIRED_EVENT_KEYS = {
    "schema", "vehicle_pseudonym", "event_type", "odometer_km",
    "consent", "recorded_at", "mode",
}


def verify_receipt(receipt):
    if not isinstance(receipt, dict) or set(receipt) != {"event", "sha256"}:
        return False, "Invalid receipt envelope"
    event, digest = receipt["event"], receipt["sha256"]
    if not isinstance(event, dict) or set(event) != REQUIRED_EVENT_KEYS:
        return False, "Unexpected event fields"
    if (event["schema"] != "privi-car-consent-receipt-v1"
            or event["mode"] != "LOCAL_DEMO_NOT_ON_CHAIN"
            or event["event_type"] != "odometer_observation"):
        return False, "Unsupported receipt type"
    if (not isinstance(event["odometer_km"], int)
            or isinstance(event["odometer_km"], bool)
            or not 0 <= event["odometer_km"] <= 3000000):
        return False, "Invalid odometer"
    consent = event["consent"]
    if (not isinstance(consent, dict)
            or consent != {"granted": True, "purpose": "maintenance_demo", "scope": ["odometer_km"]}):
        return False, "Invalid consent declaration"
    pseudonym = event["vehicle_pseudonym"]
    if not isinstance(pseudonym, str) or len(pseudonym) != 64 or any(c not in "0123456789abcdef" for c in pseudonym):
        return False, "Invalid pseudonym"
    if not isinstance(event["recorded_at"], str) or not event["recorded_at"]:
        return False, "Missing timestamp"
    if not isinstance(digest, str) or len(digest) != 64:
        return False, "Invalid hash"
    canonical = json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    expected = hashlib.sha256(canonical.encode()).hexdigest()
    if not __import__("hmac").compare_digest(expected, digest):
        return False, "Receipt contents do not match SHA-256"
    return True, "Integrity verified (local demo only; not proof of vehicle origin)"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipt_json")
    args = parser.parse_args()
    try:
        with open(args.receipt_json, encoding="utf-8") as stream:
            receipt = json.load(stream)
        ok, message = verify_receipt(receipt)
    except (OSError, ValueError) as exc:
        print(f"Invalid input: {exc}", file=sys.stderr)
        return 2
    print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
