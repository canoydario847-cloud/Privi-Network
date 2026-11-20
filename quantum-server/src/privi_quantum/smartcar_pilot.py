# Copyright (c) 2026 Privi World Co. All rights reserved.
"""One-vehicle, on-demand Smartcar v3 mileage pilot. No vehicle commands."""
import json
import math
import os
import re
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler
from .car import CarError, vin_check

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def request_json(url, headers=None, form=None):
    data = urlencode(form).encode() if form else None
    req = Request(url, data=data, headers=headers or {})
    try:
        with build_opener(NoRedirect).open(req, timeout=15) as response:
            raw = response.read(262145)
            if len(raw) > 262144:
                raise ValueError()
            return json.loads(raw)
    except Exception:
        # Do not return upstream bodies, URLs, tokens or credentials.
        raise CarError("Smartcar request failed; check consent, permissions, quota and server configuration", 502) from None

def config():
    names = ("CLIENT_ID", "CLIENT_SECRET", "VEHICLE_ID", "USER_ID", "PASSPORT_ID", "ODOMETER_SIGNAL")
    c = {n: os.environ.get("SMARTCAR_" + n, "") for n in names}
    if not all(c.values()):
        raise CarError("Smartcar pilot is not configured", 503)
    for n in ("VEHICLE_ID", "USER_ID", "PASSPORT_ID", "ODOMETER_SIGNAL"):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", c[n]):
            raise CarError("Invalid Smartcar server configuration", 503)
    c["MODE"] = os.environ.get("SMARTCAR_MODE", "simulated")
    if c["MODE"] not in ("simulated", "live"):
        raise CarError("SMARTCAR_MODE must be simulated or live", 503)
    return c

def parse_signal(payload, code):
    d = payload["data"]
    a = d["attributes"]
    if a["code"] != code or a["status"]["value"] != "SUCCESS":
        raise ValueError()
    stamp = d["meta"]["retrievedAt"]
    when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    if when.tzinfo is None or when < now - timedelta(days=7) or when > now + timedelta(minutes=5):
        raise ValueError()
    return a["body"], when

def sync(cars, vehicle, owner_key, consent=False):
    if consent is not True:
        raise CarError("Explicit consent=true is required for this mileage import", 403)
    passport = cars._owner(vehicle, owner_key)
    c = config()
    if passport["vehicle_id"] != c["PASSPORT_ID"]:
        raise CarError("This passport is not enrolled in the Smartcar pilot", 403)
    if not passport["vin_fp"]:
        raise CarError("Register the passport with its VIN before connecting Smartcar")
    token = request_json("https://iam.smartcar.com/oauth2/token", form={
        "grant_type": "client_credentials", "client_id": c["CLIENT_ID"], "client_secret": c["CLIENT_SECRET"]})
    access = token.get("access_token")
    if not isinstance(access, str) or not access or "\r" in access or "\n" in access:
        raise CarError("Smartcar returned an invalid access token", 502)
    headers = {"Authorization": "Bearer " + access, "sc-user-id": c["USER_ID"]}
    root = "https://vehicle.api.smartcar.com/v3/vehicles/" + c["VEHICLE_ID"]
    info = request_json(root, headers)
    vin = request_json(root + "/signals/vehicleidentification-vin", headers)
    odo = request_json(root + "/signals/" + c["ODOMETER_SIGNAL"], headers)
    try:
        if info["data"]["attributes"]["mode"] != c["MODE"]:
            raise ValueError()
        vbody, _ = parse_signal(vin, "vehicleidentification-vin")
        if vin_check(vbody["value"])["fingerprint"] != passport["vin_fp"]:
            raise ValueError()
        body, when = parse_signal(odo, c["ODOMETER_SIGNAL"])
        units = {"kilometers": "km", "km": "km", "miles": "mi", "mi": "mi"}
        unit = units[body["unit"]]
        value = body["value"]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError()
    except (KeyError, TypeError, ValueError, CarError):
        raise CarError("Smartcar vehicle, VIN, signal, units or freshness validation failed", 502) from None
    # Never mix simulated readings into the real passport's history.
    if c["MODE"] == "simulated":
        return {"status": "simulated", "written": False, "odometer": value, "unit": unit,
                "measured_at": when.isoformat(), "note": "No vehicle record or ledger entry created"}
    result = cars.add_record(vehicle, owner_key, "odometer", {
        "odometer": value, "unit": unit, "date": when.date().isoformat(),
        "summary": "Smartcar v3 mileage import; retrievedAt=" + when.isoformat()})
    return {"status": "imported", "source": "Smartcar", "mode": "live", "record": result}
