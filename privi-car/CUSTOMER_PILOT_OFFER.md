# Privi Car — $19.99 consent-based offline pilot (prelaunch)

**Status:** Human-delivered evaluation offer, not a deployed service, authenticated odometer, automated AI agent, or payment integration. No customer payment or vehicle connectivity is implied.

## Who this helps
Independent repair shops and fleets with 3–20 vehicles that already maintain mileage history and want a second look at internal record consistency.

## Offer and acceptance
Proposed **$19.99 one-time** review of **one consented export**, with an aggregate plain-text report and a short explanation of findings. This is a proposed pilot price, not an active checkout. Do not charge until the operator confirms scope, data handling, and delivery. Obtain feedback on usefulness and willingness to pay; do not claim savings or mileage authentication.

## Safe intake checklist
- [ ] Explain this is an **advisory review of submitted records only**; no direct connection to a car or independent odometer verification.
- [ ] Confirm the requester is authorized to share the data, and record explicit consent, intended use, and contact for delivery **outside the public repository**.
- [ ] Prefer synthetic or de-identified local demo exports. Do not solicit VINs, names, addresses, license plates, location trails, payment credentials, or vehicle secrets.
- [ ] Agree on secure local transfer, access restrictions, and deletion date before receiving any real records. Never commit customer data or consent records to GitHub.
- [ ] Confirm input matches the existing `fleet_batch.py` export format; don't claim arbitrary CSV or telematics compatibility.

## Delivery procedure
1. Review the existing [pilot report instructions](PILOT_REPORT.md) and explain limitations.
2. On an operator-controlled computer, run `python3 -m unittest discover -s privi-car -p 'test_*.py' -v` before handling a pilot export. Stop if tests fail.
3. Run `python3 privi-car/pilot_report.py /path/to/consented-export.json --output /path/to/unique-pilot-report.txt`. Use a fresh output filename; the tool intentionally refuses overwrite.
4. Check the report's result: **insufficient consented records**, **human review recommended**, or **no anomalies found in submitted records**. Never call the latter a clean or verified vehicle history.
5. Deliver only the aggregate report through the agreed channel, explain anomalies as review prompts, collect feedback, and delete local records on the agreed schedule.

## Pilot feedback (do not put identifying responses in GitHub)
- Did the report reveal a recordkeeping question worth investigating?
- Was the language understandable without training?
- Would you pay $19.99 for this exact manual one-time review? If not, what would need to change?
- Would you request another review? What would trigger it?

## Stop conditions
No consent, unauthorized data, missing valid receipts, failing tests, incompatible export, or an expectation of authenticated mileage: do not sell or deliver a conclusive vehicle assessment. Refund or decline as appropriate if payment was taken outside this prototype.

## Future concepts (not available)
Vehicle AI assistant, authorized live telemetry, fuel prepay, pump reservations, and vehicle-mining economics are not included in this pilot.
