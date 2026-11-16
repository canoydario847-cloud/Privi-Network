from datetime import datetime, timezone
from unittest.mock import Mock
import pytest
from privi_quantum import smartcar_pilot as s
from privi_quantum.car import CarError, vin_check

VIN = "1HGCM82633A004352"

def setup(monkeypatch, mode="simulated"):
    for k, v in {"CLIENT_ID":"id", "CLIENT_SECRET":"secret", "VEHICLE_ID":"vehicle1",
                 "USER_ID":"user1", "PASSPORT_ID":"car_1", "ODOMETER_SIGNAL":"odometer-distance",
                 "MODE":mode}.items():
        monkeypatch.setenv("SMARTCAR_" + k, v)
    cars = Mock()
    cars._owner.return_value = {"vehicle_id":"car_1", "vin_fp":vin_check(VIN)["fingerprint"]}
    def signal(code, body):
        return {"data":{"attributes":{"code":code, "status":{"value":"SUCCESS"}, "body":body},
                        "meta":{"retrievedAt":datetime.now(timezone.utc).isoformat()}}}
    responses = [{"access_token":"secret-token"}, {"data":{"attributes":{"mode":mode}}},
                 signal("vehicleidentification-vin", {"value":VIN}),
                 signal("odometer-distance", {"value":1234, "unit":"kilometers"})]
    transport = Mock(side_effect=responses)
    monkeypatch.setattr(s, "request_json", transport)
    return cars, responses, transport

def test_simulated_does_not_write(monkeypatch):
    cars, _, transport = setup(monkeypatch)
    assert s.sync(cars, "car_1", "key", True)["written"] is False
    cars.add_record.assert_not_called()
    assert transport.call_count == 4

def test_live_import(monkeypatch):
    cars, _, _ = setup(monkeypatch, "live")
    assert s.sync(cars, "car_1", "key", True)["status"] == "imported"
    assert cars.add_record.call_args.args[3]["odometer"] == 1234

def test_consent_and_ownership_before_network(monkeypatch):
    cars, _, transport = setup(monkeypatch)
    with pytest.raises(CarError):
        s.sync(cars, "car_1", "key", False)
    transport.assert_not_called()
    cars._owner.side_effect = CarError("denied", 403)
    with pytest.raises(CarError):
        s.sync(cars, "car_1", "wrong", True)
    transport.assert_not_called()

@pytest.mark.parametrize("bad", ["vin", "unit", "status", "stale", "mode", "nan", "code"])
def test_invalid_data_never_written(monkeypatch, bad):
    cars, r, _ = setup(monkeypatch, "live")
    if bad == "vin": r[2]["data"]["attributes"]["body"]["value"] = "5YJSA1CN5DFP00101"
    if bad == "unit": r[3]["data"]["attributes"]["body"]["unit"] = "unknown"
    if bad == "status": r[3]["data"]["attributes"]["status"]["value"] = "ERROR"
    if bad == "stale": r[3]["data"]["meta"]["retrievedAt"] = "2000-01-01T00:00:00Z"
    if bad == "mode": r[1]["data"]["attributes"]["mode"] = "simulated"
    if bad == "nan": r[3]["data"]["attributes"]["body"]["value"] = float("nan")
    if bad == "code": r[3]["data"]["attributes"]["code"] = "wrong"
    with pytest.raises(CarError):
        s.sync(cars, "car_1", "key", True)
    cars.add_record.assert_not_called()
