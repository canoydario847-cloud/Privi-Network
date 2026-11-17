# Privi Car: local pilot report

**Status:** Offline demo only. Not a live vehicle service, vehicle data authentication, blockchain transaction, or paid integration.

This pilot-friendly report converts the existing local fleet mileage audit into a plain-language text summary for a consenting mechanic or fleet operator. It intentionally includes only aggregate counts and an advisory human-review recommendation. It never includes a vehicle pseudonym, raw odometer reading, owner identifier, or original receipt.

Run locally (Python standard library; no paid API):

    python3 privi-car/pilot_report.py /path/to/consented-fleet-demo-export.json
    python3 privi-car/pilot_report.py /path/to/consented-fleet-demo-export.json --output /path/to/pilot.txt

The input is a local demo export from fleet_batch.py, not arbitrary vehicle data. The audit validates receipt integrity, checks for duplicate or conflicting mileage observations and flags suspected odometer decreases. A passing report means only that **no anomaly was detected in the submitted records**; it does not prove the records came from a real car or that the odometer is accurate.

To verify the implementation:

    python3 -m unittest discover -s privi-car -p 'test_*.py' -v

**Pilot offer:** Ask a consenting independent repair shop or small fleet for a locally exported, synthetic or permissioned mileage-history sample. Provide the offline aggregate report and gather feedback on usefulness and willingness to pay. Keep raw data local, obtain explicit consent, and do not claim live integrations, automated payments, or authenticated telemetry. Fuel pump prepay and reservations remain future concepts.
