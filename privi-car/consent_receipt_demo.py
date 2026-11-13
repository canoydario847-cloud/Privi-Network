"""Privi Car consent-gated telemetry receipt demo (stdlib only).

Local/offline proof of concept. Does not access a vehicle, network, wallet or chain.
Usage: python3 privi_car_receipt.py --consent --vehicle-id demo-car-1 --odometer-km 12000
Without --consent, exits without collecting or writing telemetry.
"""
import argparse
import datetime
import hashlib
import json
import sys

def make_receipt(vehicle_id, odometer_km, consent):
    if not consent:
        raise PermissionError("Explicit consent required before processing telemetry")
    if not isinstance(vehicle_id, str) or not (1 <= len(vehicle_id) <= 80):
        raise ValueError("vehicle-id must be 1..80 characters")
    if not isinstance(odometer_km, int) or not (0 <= odometer_km <= 3000000):
        raise ValueError("odometer-km must be an integer from 0 to 3000000")
    # Do not put VIN, location, driver identity, or raw telemetry in the receipt.
    pseudonym = hashlib.sha256(("privi-car-demo-v1:" + vehicle_id).encode()).hexdigest()
    event = {
        "schema": "privi-car-consent-receipt-v1",
        "vehicle_pseudonym": pseudonym,
        "event_type": "odometer_observation",
        "odometer_km": odometer_km,
        "consent": {"granted": True, "purpose": "maintenance_demo", "scope": ["odometer_km"]},
        "recorded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "mode": "LOCAL_DEMO_NOT_ON_CHAIN",
    }
    canonical = json.dumps(event, sort_keys=True, separators=(",", ":"))
    return {"event": event, "sha256": hashlib.sha256(canonical.encode()).hexdigest()}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--consent", action="store_true", help="Explicit opt-in")
    parser.add_argument("--vehicle-id", required=True, help="Demo identifier; do not use VIN")
    parser.add_argument("--odometer-km", required=True, type=int)
    args = parser.parse_args()
    try:
        receipt = make_receipt(args.vehicle_id, args.odometer_km, args.consent)
    except (PermissionError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(receipt, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
