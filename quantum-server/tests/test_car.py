# Copyright (c) 2026 Privi World Co. All rights reserved.
"""Privi Car: passport, sealed records, digital keys, history report, route / fleet / charging plans, edge gate."""
import itertools
import json
import sqlite3

import anyio
import numpy as np
import pytest
from mcp import Client

from privi_quantum import car
from privi_quantum.attest import Attestor
from privi_quantum.car import Car, CarError, MemorySeen
from privi_quantum.car_web import PRICES
from privi_quantum.hardware import HardwareRouter, LocalBackend
from privi_quantum.payments import DEFAULT_PRICES_USD, PaySettings
from privi_quantum.server import Settings, build_server, http_app

VIN = "1HGCM82633A004352"          # textbook valid check digit
MICH = [{"name": "Port Huron", "lat": 42.97, "lon": -82.42}, {"name": "Detroit", "lat": 42.33, "lon": -83.05},
        {"name": "Flint", "lat": 43.01, "lon": -83.69}, {"name": "Ann Arbor", "lat": 42.28, "lon": -83.74},
        {"name": "Lansing", "lat": 42.73, "lon": -84.56}]


@pytest.fixture
def cars(tmp_path):
    db = str(tmp_path / "c.db")
    return Car(db, Attestor(db), "https://example.test")


def test_vin_check_digit():
    assert car.vin_check(VIN)["check_digit_ok"] and car.vin_check(" 1hgcm82633a004352 ")["vin"] == VIN
    assert not car.vin_check("1HGCM82633A004353")["check_digit_ok"]          # one digit off
    assert car.vin_check("11111111111111111")["check_digit_ok"]
    for bad in ("", "1HGCM82633A00435", "1HGCM82633A0O4352", "IHGCM82633A004352"):
        with pytest.raises(CarError):
            car.vin_check(bad)
    assert VIN not in json.dumps(car.vin_check(VIN)["fingerprint"])


def test_passport_records_and_rollback(cars, tmp_path):
    reg = cars.register("Ford", "F-150", 2021, VIN, "gas")
    vid, key = reg["vehicle_id"], reg["owner_key"]
    assert reg["vin"]["check_digit_ok"] and cars.attestor.get(reg["passport"]["attestation_id"])["body"]["kind"] == "car_passport"
    with pytest.raises(CarError) as e:
        cars.register("Ford", "F-150", 2021, VIN)                           # one passport per VIN
    assert e.value.status == 409
    with pytest.raises(CarError):
        cars.register("<script>", "x", 2021)
    with pytest.raises(CarError):
        cars.add_record(vid, "carkey_wrong", "odometer", {"odometer": 10})
    a = cars.add_record(vid, key, "odometer", {"odometer": 40000, "unit": "mi", "date": "2026-01-05"})
    assert a["recorded"]["odometer_km"] == 64373.8 and a["seq"] == 1 and not a["flags"]
    b = cars.add_record(VIN, key, "service", {"odometer": 65000, "cost_usd": 89.5, "summary": "oil + filter", "date": "2026-02-01"})
    assert b["prev_hash"] == a["entry_hash"]
    c = cars.add_record(vid, key, "odometer", {"odometer": 52000})          # lower than before
    assert c["flags"] == ["odometer_rollback"] and c["warning"]
    cars.add_record(vid, key, "trip", {"distance": 12.5, "duration_min": 20})
    for bad in ({"lat": 1.0}, {"address": "1 Main St"}, {"date": "2999-01-01"}, {"odometer": -1}, {"unit": "leagues"}):
        with pytest.raises(CarError):
            cars.add_record(vid, key, "note", bad)
    with pytest.raises(CarError):
        cars.add_record(vid, key, "odometer", {})
    with pytest.raises(CarError):
        cars.add_record(vid, key, "teleport", {})
    v = cars.verify_chain(vid)
    assert v == {**v, "records": 4, "chain_intact": True, "rollback_flags": 1, "first_broken_seq": None}

    # tampering with a stored record breaks the chain
    db = sqlite3.connect(str(tmp_path / "c.db"))
    db.execute("UPDATE car_records SET body=? WHERE vehicle_id=? AND seq=1",
               (json.dumps({"date": "2026-01-05", "odometer_km": 1000.0, "type": "odometer"}), vid))
    db.commit()
    t = cars.verify_chain(vid)
    assert not t["chain_intact"] and t["first_broken_seq"] == 1
    assert not cars.public(vid)["chain_intact"]


def test_keys_and_history(cars):
    reg = cars.register("Tesla", "Model 3", 2023, powertrain="electric", service_km=20000, service_months=24)
    vid, key = reg["vehicle_id"], reg["owner_key"]
    other = cars.register("Honda", "Civic", 2019)
    cars.add_record(vid, key, "odometer", {"odometer": 10000, "date": "2026-01-01"})
    cars.add_record(vid, key, "service", {"odometer": 10500, "cost_usd": 120, "date": "2026-01-10"})
    cars.add_record(vid, key, "charge", {"kwh": 42, "cost_usd": 9.87})
    cars.add_record(vid, key, "odometer", {"odometer": 32000})

    with pytest.raises(CarError):
        cars.issue_key(vid, key, "buyer", ["fly"])
    with pytest.raises(CarError):
        cars.issue_key(vid, "nope", "buyer", ["history"])
    valet = cars.issue_key(vid, key, "Valet at Blue Water Inn", ["valet", "unlock"], hours=2)
    buyer = cars.issue_key(vid, key, "Pat Buyer", ["history"], hours=72)
    assert cars.check_key(valet["token"], "unlock")["allowed"]
    assert cars.check_key(valet["token"], "drive") == {**cars.check_key(valet["token"], "drive"), "allowed": False}
    assert not cars.check_key(valet["token"][:-2] + "zz")["allowed"] and not cars.check_key("garbage")["allowed"]
    att = cars.attestor.get(valet["attestation_id"])
    assert att["body"]["kind"] == "car_key" and "Blue Water" not in json.dumps(att)          # grantee only as a hash
    assert Attestor.verify(att, cars.attestor.public_keys()["ed25519"], cars.attestor.public_keys()["ml_dsa_87"])["valid"]

    for bad in ("", "carkey_wrong", valet["token"]):                         # valet key has no history scope
        with pytest.raises(CarError) as e:
            cars.history(vid, bad)
        assert e.value.status == 403
    with pytest.raises(CarError):
        cars.history(other["vehicle_id"], buyer["token"])                    # a key opens only its own vehicle
    h = cars.history(vid, buyer["token"])
    s = h["summary"]
    assert s["records"] == 4 and s["chain_intact"] and s["odometer_rollbacks"] == 0 and s["spend_usd_total"] == 129.87
    assert h["service"]["next_due_km"] == 30500 and h["service"]["km_until_due"] == -1500 and h["service"]["overdue"]
    assert [o["km"] for o in h["odometer_timeline"]] == [10000, 10500, 32000]
    assert cars.attestor.get(h["report_id"])["body"]["kind"] == "car_history_report"
    assert cars.history(vid, key)["summary"]["records"] == 4

    with pytest.raises(CarError):
        cars.revoke_key(other["vehicle_id"], other["owner_key"], buyer["key_id"])   # not your vehicle's key
    assert cars.revoke_key(vid, key, buyer["key_id"])["state"] == "revoked"
    assert cars.check_key(buyer["token"])["reason"] == "revoked"
    with pytest.raises(CarError):
        cars.history(vid, buyer["token"])
    future = cars.issue_key(vid, key, "shop", ["service"], hours=1, not_before="2999-01-01T00:00:00Z")
    assert cars.check_key(future["token"])["reason"] == "not_yet_valid"
    short = cars.issue_key(vid, key, "shop", ["service"], hours=1, not_before="2020-01-01T00:00:00Z")
    assert cars.check_key(short["token"])["reason"] == "expired"


def _brute_route(D, round_trip):
    n = len(D)
    return min(car.tour_length(D, [0, *p], round_trip) for p in itertools.permutations(range(1, n)))


def test_route_exact_and_quantum():
    rng = np.random.default_rng(3)
    for n in (2, 3, 4, 6, 7):
        for rt in (True, False):
            D = rng.uniform(1, 50, (n, n))
            np.fill_diagonal(D, 0)
            hk = car.held_karp(D, rt)
            assert abs(hk["km"] - _brute_route(D, rt)) < 1e-9 and abs(car.tour_length(D, hk["order"], rt) - hk["km"]) < 1e-9
            assert sorted(hk["order"]) == list(range(n)) and hk["order"][0] == 0
    # every feasible QUBO assignment costs exactly the route length
    D = rng.uniform(1, 50, (4, 4))
    np.fill_diagonal(D, 0)
    for rt in (True, False):
        qubo, decode = car.route_qubo(D, rt)
        costs = qubo.all_costs()
        k = int(np.argmin(costs))
        best = decode([(k >> i) & 1 for i in range(qubo.n)])
        assert best is not None and abs(costs[k] - _brute_route(D, rt)) < 1e-6
        assert decode([1] * qubo.n) is None

    r = car.plan_route({"stops": MICH[:4]})
    assert r["plan"]["order"][0] == "Port Huron" and r["plan"]["km_saved"] > 0
    q = r["sealed"]["quantum"]
    assert q["qubits"] == 9 and r["sealed"]["verdict"] in ("tie", "classical_won")
    if q["valid_answer"]:
        assert q["km"] >= r["plan"]["km"] - 1e-6                             # quantum never beats the proven optimum
    assert "Port Huron" not in json.dumps(r["sealed"]) and "42.97" not in json.dumps(r["sealed"])   # no stops sealed
    big = car.plan_route({"stops": MICH + [{"name": "Saginaw", "lat": 43.42, "lon": -83.95}]})
    assert big["sealed"]["verdict"] == "classical_only" and big["sealed"]["quantum"] is None and "25 qubits" in big["sealed"]["why"]
    assert car.plan_route({"stops": MICH[:3]})["sealed"]["verdict"] == "classical_only"
    assert car.plan_route({"stops": MICH[:3], "round_trip": False})["sealed"]["quantum"]["qubits"] == 4
    m = car.plan_route({"stops": [{"name": "a"}, {"name": "b"}, {"name": "c"}, {"name": "d"}],
                        "distances_km": [[0, 9, 1, 9], [9, 0, 9, 1], [1, 9, 0, 1], [9, 1, 1, 0]], "round_trip": False})
    assert m["plan"]["order"] == ["a", "c", "d", "b"] and m["plan"]["km"] == 3
    for bad in ({"stops": MICH[:1]}, {"stops": MICH * 3}, {"stops": [{"name": "x", "lat": 99, "lon": 0}, MICH[0]]},
                {"stops": [MICH[0], MICH[0]]}, {"stops": [{"name": "a", "lat": 1, "lon": 1}, {"name": "b", "lat": 1, "lon": 1}]},
                {"stops": MICH[:3], "distances_km": [[0, 1], [1, 0]]}):
        with pytest.raises(CarError):
            car.plan_route(bad)


def test_fleet_assignment():
    r = car.plan_fleet({"jobs": [{"name": "a"}, {"name": "b"}, {"name": "c"}], "vehicles": [{"name": "v1"}, {"name": "v2"}, {"name": "v3"}],
                        "cost": [[1, 2, 9], [1, 9, 9], [9, 9, 1]]})
    assert r["plan"]["total_cost"] == 4 and r["plan"]["assignments"] == {"v1": ["b"], "v2": ["a"], "v3": ["c"]}
    assert r["plan"]["saved_vs_first_come"] == 7 and r["sealed"]["quantum"]["qubits"] == 9
    if r["sealed"]["quantum"]["valid_answer"]:
        assert r["sealed"]["quantum"]["cost"] >= 4 - 1e-9
    # the QUBO's best feasible answer is the Hungarian optimum (capacity 1)
    C = np.array([[1, 2, 9], [1, 9, 9], [9, 9, 1]], dtype=float)
    qubo, decode = car.assign_qubo(C, 1)
    k = int(np.argmin(qubo.all_costs()))
    a = decode([(k >> i) & 1 for i in range(9)])
    assert a == [1, 0, 2] and abs(qubo.all_costs()[k] - 4) < 1e-9
    cap = car.plan_fleet({"jobs": [{"name": f"j{i}"} for i in range(6)], "vehicles": [{"name": "v1"}, {"name": "v2"}],
                          "cost": [[1, 5], [2, 1], [9, 3], [4, 4], [1, 8], [7, 2]]})
    assert cap["plan"]["total_cost"] == 12 and all(len(v) == 3 for v in cap["plan"]["assignments"].values())
    assert cap["sealed"]["verdict"] == "classical_only"
    geo = car.plan_fleet({"jobs": MICH[1:4], "vehicles": [MICH[0], MICH[4]], "max_jobs_per_vehicle": 3})
    assert sum(len(v) for v in geo["plan"]["assignments"].values()) == 3
    for bad in ({"jobs": [], "vehicles": [{"name": "v"}]}, {"jobs": [{"name": "a"}, {"name": "b"}], "vehicles": [{"name": "v"}], "cost": [[1], [2]],
                "max_jobs_per_vehicle": 1}, {"jobs": [{"name": "a"}], "vehicles": [{"name": "v"}]},
                {"jobs": [{"name": "a"}, {"name": "a"}], "vehicles": [{"name": "v"}], "cost": [[1], [2]]}):
        with pytest.raises(CarError):
            car.plan_fleet(bad)


def test_charging_plan():
    prices = [0.30, 0.28, 0.22, 0.12, 0.10, 0.11, 0.15, 0.25]
    r = car.plan_charging({"price_per_kwh": prices, "charger_kw": 7.2, "energy_needed_kwh": 20})
    assert r["plan"]["slots_needed"] == 3 and r["plan"]["charge_in_slots"] == [3, 4, 5]
    assert r["plan"]["energy_cost_usd"] == round(7.2 * 0.33, 4) and r["plan"]["saved_usd"] == round(7.2 * (0.80 - 0.33), 4)
    assert r["sealed"]["quantum"]["qubits"] == 8 and r["sealed"]["classical"][0]["method"] == "exhaustive"
    # a switch penalty pulls the plan into one block
    split = car.plan_charging({"price_per_kwh": [0.1, 0.5, 0.1, 0.5, 0.11, 0.12], "charger_kw": 10, "energy_needed_kwh": 20})
    joined = car.plan_charging({"price_per_kwh": [0.1, 0.5, 0.1, 0.5, 0.11, 0.12], "charger_kw": 10, "energy_needed_kwh": 20,
                                "switch_penalty_usd": 5})
    assert split["plan"]["charge_in_slots"] == [0, 2] and split["plan"]["charging_blocks"] == 2
    assert joined["plan"]["charge_in_slots"] == [4, 5] and joined["plan"]["charging_blocks"] == 1
    full = car.plan_charging({"price_per_kwh": [0.1, 0.2], "charger_kw": 5, "energy_needed_kwh": 10})
    assert full["plan"]["charge_in_slots"] == [0, 1] and full["sealed"]["verdict"] == "classical_only"
    for bad in ({"price_per_kwh": [0.1], "charger_kw": 7, "energy_needed_kwh": 5}, {"price_per_kwh": [0.1] * 17, "charger_kw": 7, "energy_needed_kwh": 5},
                {"price_per_kwh": [0.1, 0.2], "charger_kw": 1, "energy_needed_kwh": 50}, {"price_per_kwh": [0.1, "x"], "charger_kw": 1, "energy_needed_kwh": 1},
                {"price_per_kwh": [0.1, 0.2], "energy_needed_kwh": 1}):
        with pytest.raises(CarError):
            car.plan_charging(bad)


def test_edge_gate_matches_worker_cjs(cars):
    now = 1_700_000_000_000
    policy = {"ownerOptIn": True, "parked": True, "externalPower": True, "thermalSafe": True, "tenant": "owner1"}
    job = lambda **kw: {"tenant": "owner1", "nonce": "a" * 32, "expiresAt": now + 30000, "payload": "hello", **kw}
    r = car.verify_edge_job(job(), policy, MemorySeen(), now)
    assert r["credits"] == 0 and r["status"] == "simulated" and len(r["digest"]) == 64
    seen = MemorySeen()
    car.verify_edge_job(job(), policy, seen, now)
    with pytest.raises(CarError, match="replay"):
        car.verify_edge_job(job(), policy, seen, now)
    car.verify_edge_job(job(), policy, cars, now)                            # the database-backed replay store
    with pytest.raises(CarError, match="replay"):
        car.verify_edge_job(job(), policy, cars, now)
    with pytest.raises(CarError, match="tenant"):
        car.verify_edge_job(job(tenant="other"), policy, MemorySeen(), now)
    for k in ("parked", "ownerOptIn", "externalPower", "thermalSafe"):
        with pytest.raises(CarError, match="disabled"):
            car.verify_edge_job(job(), {**policy, k: False}, MemorySeen(), now)
        with pytest.raises(CarError, match="disabled"):
            car.verify_edge_job(job(), {**policy, k: 1}, MemorySeen(), now)   # truthy is not True
    for bad in (job(expiresAt=now - 1), job(expiresAt=now + 60001), job(expiresAt=True), job(payload="x" * 65537),
                job(nonce="A" * 32), job(payload=5), None, []):
        with pytest.raises(CarError):
            car.verify_edge_job(bad, policy, MemorySeen(), now)


def test_every_car_tool_is_priced():
    assert {t: DEFAULT_PRICES_USD[t] for t in PRICES} == PRICES


def test_mcp_tools_pages_and_paywall(tmp_path, monkeypatch):
    from starlette.testclient import TestClient
    db = str(tmp_path / "s.db")
    srv = build_server(Settings(db_path=db, rate_per_min=1000), Attestor(db))

    async def go():
        async with Client(srv) as c:
            names = {t.name for t in (await c.list_tools()).tools}
            assert set(PRICES) <= names
            info = (await c.call_tool("car_info", {})).structured_content
            assert "never connects" in info["boundaries"]
            reg = (await c.call_tool("car_register", {"make": "Jeep", "model": "Wrangler", "year": 2020, "vin": VIN})).structured_content
            vid, key = reg["vehicle_id"], reg["owner_key"]
            bad = await c.call_tool("car_record_add", {"vehicle": vid, "owner_key": "x", "type": "note"})
            assert bad.is_error and "owner_key" in bad.structured_content["error"]
            ok = await c.call_tool("car_record_add", {"vehicle": vid, "owner_key": key, "type": "odometer", "data": {"odometer": 1200}})
            assert ok.structured_content["seq"] == 1
            k = (await c.call_tool("car_key_issue", {"vehicle": vid, "owner_key": key, "grantee": "buyer", "scopes": ["history"]})).structured_content
            h = (await c.call_tool("car_history", {"vehicle": VIN, "access": k["token"]})).structured_content
            assert h["summary"]["make"] == "Jeep" and h["summary"]["records"] == 1
            assert (await c.call_tool("car_key_check", {"token": k["token"], "scope": "drive"})).structured_content["allowed"] is False
            assert (await c.call_tool("car_key_revoke", {"vehicle": vid, "owner_key": key, "key_id": k["key_id"]})).structured_content["state"] == "revoked"
            assert (await c.call_tool("car_verify", {"vehicle": vid})).structured_content["chain_intact"]
            assert (await c.call_tool("car_vin_check", {"vin": VIN})).structured_content["check_digit_ok"]
            rt = (await c.call_tool("car_route", {"stops": MICH[:4]})).structured_content
            assert rt["plan"]["order"][0] == "Port Huron" and rt["receipt_id"].startswith("qa_") and rt["quantum"]["qubits"] == 9
            sealed = srv._car.attestor.get(rt["receipt_id"])["body"]
            assert sealed["kind"] == "car_route" and len(sealed["problem_sha256"]) == 64 and "Detroit" not in json.dumps(sealed)
            assert (await c.call_tool("car_route", {"stops": MICH[:1]})).is_error
            fl = (await c.call_tool("car_fleet_assign", {"jobs": MICH[1:3], "vehicles": [MICH[0], MICH[4]]})).structured_content
            assert fl["verdict"] in ("tie", "classical_won") and sum(len(v) for v in fl["plan"]["assignments"].values()) == 2
            ch = (await c.call_tool("car_charge_plan", {"price_per_kwh": [0.3, 0.1, 0.2, 0.1], "charger_kw": 7, "energy_needed_kwh": 14})).structured_content
            assert ch["plan"]["charge_in_slots"] == [1, 3]
            import time
            job = {"tenant": "t1", "nonce": "b" * 32, "expiresAt": int(time.time() * 1000) + 20000, "payload": "p"}
            pol = {"tenant": "t1", "ownerOptIn": True, "parked": True, "externalPower": True, "thermalSafe": True}
            assert (await c.call_tool("car_edge_job", {"job": job, "policy": pol})).structured_content["credits"] == 0
            assert (await c.call_tool("car_edge_job", {"job": job, "policy": pol})).is_error                # replay
            assert (await c.call_tool("car_edge_job", {"job": {**job, "nonce": "c" * 32}, "policy": {**pol, "parked": False}})).is_error
            return vid, k["key_id"]
    vid, kid = anyio.run(go)

    with TestClient(http_app(srv)) as http:
        home = http.get("/car")
        assert home.status_code == 200 and "Privi Car" in home.text and "car_history" in home.text
        page = http.get(f"/car/{vid}")
        assert page.status_code == 200 and "2020 Jeep Wrangler" in page.text and VIN not in page.text and "Records intact" in page.text
        pub = http.get(f"/car/{vid}.json").json()
        assert pub["records"] == 1 and "owner" not in json.dumps(pub).replace("the owner shares", "") and VIN not in json.dumps(pub)
        assert http.get(f"/car/keys/{kid}.json").json()["state"] == "revoked"
        assert http.get("/car/car_missing").status_code == 404 and http.get("/car/car_missing.json").status_code == 404
        assert http.get("/car/keys/ck_missing.json").status_code == 404
        assert http.get("/car/%3Cscript%3E").status_code == 404

    # with payments on, every car tool asks for payment and a failed call is not charged
    class Fac:
        calls: list = []

        async def verify(self, payload, req):
            self.calls.append("verify")
            return {"isValid": True}

        async def settle(self, payload, req):
            self.calls.append("settle")
            return {"success": True, "transaction": "0x" + "cd" * 32, "network": req["network"]}

    db2 = str(tmp_path / "p.db")
    pay = PaySettings(payments_enabled=True, pay_to="0x1990589FD200E043b8C6FD9ec5956c61b3071048", cdp_key_id="k", cdp_key_secret="s", db_path=db2)
    fac = Fac()
    paid = build_server(Settings(db_path=db2), Attestor(db2), None, None, HardwareRouter(db2, [LocalBackend()]), None,
                        pay_settings=pay, facilitator=fac)

    async def pay_flow():
        async with Client(paid) as c:
            for tool in PRICES:
                assert (await c.call_tool(tool, {})).is_error, tool
            args = {"make": "Kia", "model": "EV6", "year": 2024, "powertrain": "electric"}
            need = await c.call_tool("car_register", args)
            body = need.structured_content
            assert need.is_error and body["accepts"][0]["amount"] == "1000000" and fac.calls == []
            pm = {"x402Version": 2, "resource": body["resource"], "accepted": body["accepts"][0], "payload": {}}
            ok = await c.call_tool("car_register", args, meta={"x402/payment": pm})
            assert not ok.is_error and ok.structured_content["vehicle_id"].startswith("car_") and fac.calls == ["verify", "settle"]
            need2 = (await c.call_tool("car_route", {"stops": MICH[:1]})).structured_content
            pm2 = {"x402Version": 2, "resource": need2["resource"], "accepted": need2["accepts"][0], "payload": {}}
            failed = await c.call_tool("car_route", {"stops": MICH[:1]}, meta={"x402/payment": pm2})
            assert failed.is_error and "settle" not in fac.calls[2:]          # bad input: verified, never settled
    anyio.run(pay_flow)

    monkeypatch.setenv("QUANTUM_PRICE_CAR_HISTORY", "9")
    assert PaySettings.from_env().prices_usd["car_history"] == "9"
