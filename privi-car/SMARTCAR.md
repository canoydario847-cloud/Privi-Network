# Privi Car + Smartcar: one-vehicle mileage pilot

Status: implementation for review; not a verified live connection. Uses Smartcar v3.
The Free plan allows one live vehicle, but confirm VIN and odometer signal availability
in your account. No paid plan or subscription is activated by this code.

## Setup
1. Create a free Smartcar application at https://dashboard.smartcar.com/signup.
2. Configure only VIN and odometer read permissions in Vehicle Access.
3. Use the dashboard's Share Connect Link to obtain the vehicle owner's consent.
   Never collect their automaker password in Privi.
4. Register a Privi Car passport using that same VIN; keep the returned owner key.
5. Identify the connected vehicle and Smartcar user in the dashboard / Connections API.
   Use List signals to obtain the exact odometer signal code for that vehicle.
6. Set server secrets SMARTCAR_CLIENT_ID and SMARTCAR_CLIENT_SECRET. Never commit them.
   Set SMARTCAR_VEHICLE_ID, SMARTCAR_USER_ID, SMARTCAR_PASSPORT_ID,
   SMARTCAR_ODOMETER_SIGNAL, and SMARTCAR_MODE=simulated initially.
7. Call car_smartcar_sync(vehicle, owner_key, consent=true) through the existing Privi Car MCP.
   Simulated mode reports mileage without writing records. Use a matching simulated VIN.
8. After testing, enroll the consented live vehicle and its matching passport, then set
   SMARTCAR_MODE=live. Verify the imported record with car_history / car_verify.

This is an operator-enrolled single-vehicle pilot, not self-service onboarding.
Configuration must be updated explicitly when changing the enrolled vehicle.
Keep credentials in the host's secret settings; do not paste them into chat.

## Behavior and limits
- Passport ownership is checked before any upstream request.
- Matching VIN, mode, successful signals, recognized units and readings no older than
  seven days are required. The import records Smartcar's retrieval date, not a claim
  of current physical inspection or real-time mileage.
- Access tokens are used transiently and are not persisted or returned.
- No location, lock, start, charging or driving controls.
- On-demand requests only; no recurring polling or background charges.
- Repeating a live import appends another record; it is not idempotent.
- Smartcar consent revocation/unsupported signals/quota errors stop the import.
- Existing Privi Car record storage is used; this does not implement a new ledger.
  Existing ledger architecture and retention requirements still apply.
- Multi-vehicle onboarding, durable consent mappings, webhook deduplication and
  deployment credentials remain follow-up work.

## Validation
Run: python -m pytest tests/test_smartcar_pilot.py tests/test_car.py
Tests use mocked Smartcar responses; a consented live vehicle test is still required.

References:
- https://smartcar.com/docs/api-reference/authorization/request-access-token
- https://smartcar.com/docs/api-reference/get-signal
- https://smartcar.com/docs/connect/redirect-to-connect
