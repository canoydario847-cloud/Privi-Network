# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Quantum - https://priviflow.us - dariocanoy@priviflow.us
"""MCP tools, HTTP routes and pages for Privi Car (see car.py)."""
from __future__ import annotations

import hashlib
import html
import json
from typing import Annotated, Any

import anyio
from mcp_types import CallToolResult, TextContent, ToolAnnotations
from pydantic import Field
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response

from . import car as carlib
from .car import BOUNDARIES, KEY_SCOPES, RECORD_TYPES, Car, CarError
from .realcheck_web import _STYLE

NOSTORE = {"Cache-Control": "no-store"}
READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)

# Proposed prices (USD per call, x402). Merged into payments.DEFAULT_PRICES_USD; override with QUANTUM_PRICE_CAR_<TOOL>.
PRICES = {"car_info": "0.001", "car_vin_check": "0.001", "car_verify": "0.001", "car_key_check": "0.001",
          "car_record_add": "0.01", "car_key_revoke": "0.01", "car_edge_job": "0.01", "car_key_issue": "0.05",
          "car_charge_plan": "0.10", "car_route": "0.25", "car_fleet_assign": "0.25", "car_register": "1",
          "car_history": "2"}

OWNER_KEY = Field(description="The owner_key (carkey_...) returned by car_register")
VEHICLE = Field(description="vehicle_id (car_...) or the 17-character VIN")


def _result(data: dict[str, Any], is_error: bool = False) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(data))], structured_content=data, is_error=is_error)


def _seed(data: Any) -> int:
    return int(hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()[:8], 16)


def register(mcp, cars: Car, attestor, public_url: str, cpu=None, anchoring: bool = False) -> None:
    route = mcp.custom_route

    def guard(fn, *a, **kw) -> CallToolResult:
        try:
            return _result(fn(*a, **kw))
        except CarError as e:
            return _result({"error": str(e)}, is_error=True)

    async def plan(kind: str, planner, data: dict) -> CallToolResult:
        """Run a planner off the event loop, seal the comparison, and return the plan with its receipt."""
        try:
            out = await anyio.to_thread.run_sync(lambda: planner(data, _seed(data)), limiter=cpu)
        except (CarError, carlib.qaoa.ProblemError) as e:
            return _result({"error": str(e)}, is_error=True)
        sealed = {**out["sealed"],
                  "problem_sha256": hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest(),
                  "honesty": "Privi seals this comparison whichever side wins."}
        att = await anyio.to_thread.run_sync(attestor.issue, kind, sealed)
        return _result({"plan": out["plan"], "verdict": sealed["verdict"], "why": sealed["why"],
                        "quantum": sealed["quantum"], "classical": sealed["classical"],
                        "receipt_id": att["id"], "signatures": "Ed25519 + ML-DSA-87",
                        "attestation_url": f"{public_url}/attestations/{att['id']}",
                        "anchoring": "queued for anchoring on Base" if anchoring else "anchoring not configured",
                        "privacy": "stops, jobs and prices are not stored; only a hash of the problem is sealed"})

    @mcp.tool(title="Privi Car: what it does", annotations=READ)
    def car_info() -> dict[str, Any]:
        """Privi Car in one call: the tools, record types, key scopes, size limits, prices and safety boundaries."""
        return {"service": "Privi Car (part of Privi Quantum)", "page": f"{public_url}/car", "boundaries": BOUNDARIES,
                "tools": {"identity": ["car_vin_check", "car_register"], "records": ["car_record_add", "car_verify", "car_history"],
                          "digital_keys": ["car_key_issue", "car_key_check", "car_key_revoke"],
                          "planning": ["car_route", "car_fleet_assign", "car_charge_plan"], "edge": ["car_edge_job"]},
                "record_types": RECORD_TYPES, "key_scopes": KEY_SCOPES,
                "limits": {"route_stops": carlib.MAX_STOPS, "fleet_jobs": carlib.MAX_FLEET_JOBS,
                           "charging_slots": carlib.MAX_QUBITS, "simulator_qubits": carlib.MAX_QUBITS},
                "prices_usd_per_call": PRICES, "counts": cars.stats(),
                "quantum_note": "Plans are written as QUBOs. Up to 16 qubits run on the CVaR-QAOA simulator and are "
                                "checked against an exact classical solver; the returned plan is always the best found."}

    @mcp.tool(title="Privi Car: check a VIN", annotations=READ)
    def car_vin_check(vin: Annotated[str, Field(description="17-character vehicle identification number")]) -> CallToolResult:
        """Validate a VIN's format and its check digit (position 9, required in North America) and return the
        fingerprint Privi Car stores in place of the VIN. Catches typos and many made-up VINs. It does not look the
        vehicle up in any outside database."""
        def run():
            v = carlib.vin_check(vin)
            return {"format_ok": True, "check_digit_ok": v["check_digit_ok"], "fingerprint": v["fingerprint"],
                    "note": None if v["check_digit_ok"] else "check digit mismatch: a typo, or a vehicle built for a market "
                                                             "that does not use the check digit"}
        return guard(run)

    @mcp.tool(title="Privi Car: register a vehicle (passport)", annotations=WRITE)
    def car_register(
        make: Annotated[str, Field(description="Manufacturer, e.g. Ford")],
        model: Annotated[str, Field(description="Model, e.g. F-150")],
        year: Annotated[int, Field(description="Model year")],
        vin: Annotated[str, Field(description="Optional VIN; stored only as a fingerprint")] = "",
        powertrain: Annotated[str, Field(description="gas | diesel | hybrid | plug_in_hybrid | electric | hydrogen | other")] = "gas",
        service_interval_km: Annotated[float, Field(description="Service every this many km (default 10000)")] = 10000,
        service_interval_months: Annotated[int, Field(description="Service at least every this many months (default 12)")] = 12,
    ) -> CallToolResult:
        """Create a Vehicle Passport: a post-quantum signed (Ed25519 + ML-DSA-87) identity for one vehicle, with a
        public verification page. Returns the vehicle_id and an owner_key (shown once) that controls its records and
        digital keys. One passport per VIN."""
        return guard(cars.register, make, model, year, vin, powertrain, service_interval_km, service_interval_months)

    @mcp.tool(title="Privi Car: add a sealed record", annotations=WRITE)
    def car_record_add(
        vehicle: Annotated[str, VEHICLE], owner_key: Annotated[str, OWNER_KEY],
        type: Annotated[str, Field(description=" | ".join(RECORD_TYPES))],
        data: Annotated[dict[str, Any], Field(description="Any of: odometer, unit (km|mi), distance, duration_min, liters, "
                                                           "kwh, cost_usd, summary, date (YYYY-MM-DD). No location.")] = {},
    ) -> CallToolResult:
        """Append one entry to the vehicle's hash chain: an odometer reading, service, repair, inspection, trip (distance
        and time only), fuel, charge, accident, title change or note. Each entry is hashed with the one before it, so
        history cannot be edited quietly. An odometer reading lower than an earlier one is recorded and flagged as a
        rollback."""
        return guard(cars.add_record, vehicle, owner_key, type, data)

    @mcp.tool(title="Privi Car: verify a vehicle's record chain", annotations=READ)
    def car_verify(vehicle: Annotated[str, VEHICLE]) -> CallToolResult:
        """Recompute the vehicle's hash chain: is it intact, how many records, how many odometer rollback flags, and
        the current head hash. Shows no record contents."""
        return guard(cars.verify_chain, vehicle)

    @mcp.tool(title="Privi Car: signed vehicle history report", annotations=WRITE)
    def car_history(
        vehicle: Annotated[str, VEHICLE],
        access: Annotated[str, Field(description="The owner_key, or a key token (pck_...) with the 'history' scope")],
    ) -> CallToolResult:
        """The full signed history for a buyer, lender, insurer or the owner: every record, chain check, odometer
        timeline with rollback flags, accidents on record, service due, and cost of ownership. Private by default:
        the owner opens it with the owner_key or hands a buyer a 'history' key from car_key_issue. Built from what the
        owner recorded; Privi does not inspect the vehicle."""
        return guard(cars.history, vehicle, access)

    @mcp.tool(title="Privi Car: issue a digital key", annotations=WRITE)
    def car_key_issue(
        vehicle: Annotated[str, VEHICLE], owner_key: Annotated[str, OWNER_KEY],
        grantee: Annotated[str, Field(description="Who the key is for (stored only as a hash)")],
        scopes: Annotated[list[str], Field(description="One or more of: " + ", ".join(KEY_SCOPES))],
        hours: Annotated[float, Field(description="How long the key lasts, in hours (default 24, up to 366 days)")] = 24,
        not_before: Annotated[str, Field(description="Optional ISO 8601 start time; default now")] = "",
    ) -> CallToolResult:
        """Issue a time-limited, scope-limited key for a driver, valet, shop or buyer, signed Ed25519 + ML-DSA-87.
        Returns a token (shown once) for the grantee. A 'history' key opens car_history. unlock / drive / trunk / valet /
        service keys are credentials for hardware that checks them with car_key_check; Privi Car itself never opens
        or starts a vehicle."""
        return guard(cars.issue_key, vehicle, owner_key, grantee, scopes, hours, not_before)

    @mcp.tool(title="Privi Car: check a digital key", annotations=READ)
    def car_key_check(
        token: Annotated[str, Field(description="The key token (pck_...)")],
        scope: Annotated[str, Field(description="Optional scope the holder wants to use")] = "",
    ) -> CallToolResult:
        """Is this key valid right now for this scope? Returns allowed true/false with the reason (expired, revoked, not
        yet valid, wrong scope), the vehicle_id and the signed attestation to verify offline."""
        return guard(cars.check_key, token, scope)

    @mcp.tool(title="Privi Car: revoke a digital key", annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False))
    def car_key_revoke(vehicle: Annotated[str, VEHICLE], owner_key: Annotated[str, OWNER_KEY],
                       key_id: Annotated[str, Field(description="The key_id (ck_...) to revoke")]) -> CallToolResult:
        """Revoke a digital key at once. Every later car_key_check answers 'revoked'."""
        return guard(cars.revoke_key, vehicle, owner_key, key_id)

    @mcp.tool(title="Privi Car: best route for a list of stops", annotations=WRITE)
    async def car_route(
        stops: Annotated[list[dict[str, Any]], Field(description="2-12 stops as {name, lat, lon}; the first is the start")],
        round_trip: Annotated[bool, Field(description="Return to the start at the end (default true)")] = True,
        distances_km: Annotated[list[list[float]] | None, Field(description="Optional n x n road distances or minutes; "
                                                                             "overrides straight-line distance")] = None,
    ) -> CallToolResult:
        """Order the stops for the shortest trip. The exact best order is proven classically (Held-Karp); with five
        stops or fewer the same problem also runs as a QUBO on the CVaR-QAOA quantum simulator, and the signed receipt
        shows both. Returns the order, distance, and how much it saves over the order given. Uses straight-line
        distance unless you pass distances_km. Stops are not stored."""
        data = {"stops": stops, "round_trip": round_trip, **({"distances_km": distances_km} if distances_km is not None else {})}
        return await plan("car_route", carlib.plan_route, data)

    @mcp.tool(title="Privi Car: assign jobs to a fleet", annotations=WRITE)
    async def car_fleet_assign(
        jobs: Annotated[list[dict[str, Any]], Field(description="Jobs as {name, lat, lon} (or {name} with a cost matrix)")],
        vehicles: Annotated[list[dict[str, Any]], Field(description="Vehicles as {name, lat, lon} (or {name})")],
        cost: Annotated[list[list[float]] | None, Field(description="Optional jobs x vehicles cost matrix (km, minutes or dollars)")] = None,
        max_jobs_per_vehicle: Annotated[int | None, Field(description="Default: jobs divided evenly, rounded up")] = None,
    ) -> CallToolResult:
        """Give every job (delivery, pickup, service call) to a vehicle at the lowest total cost, with a limit per
        vehicle. Proven optimal classically (Hungarian method) for up to 60 jobs; small cases (16 qubits or fewer)
        also run on the quantum simulator and the signed receipt shows both."""
        data = {"jobs": jobs, "vehicles": vehicles, **({"cost": cost} if cost is not None else {}),
                **({"max_jobs_per_vehicle": max_jobs_per_vehicle} if max_jobs_per_vehicle is not None else {})}
        return await plan("car_fleet_assign", carlib.plan_fleet, data)

    @mcp.tool(title="Privi Car: cheapest EV charging plan", annotations=WRITE)
    async def car_charge_plan(
        price_per_kwh: Annotated[list[float], Field(description="Electricity price for each time slot before departure (2-16 slots)")],
        charger_kw: Annotated[float, Field(description="Charger power in kW")],
        energy_needed_kwh: Annotated[float, Field(description="Energy to add before departure, in kWh")],
        slot_hours: Annotated[float, Field(description="Length of one slot in hours (default 1)")] = 1,
        switch_penalty_usd: Annotated[float, Field(description="Cost charged for each start/stop, to favor one "
                                                               "continuous session (default 0)")] = 0,
    ) -> CallToolResult:
        """Pick which time slots to charge in so the car has the energy it needs at the lowest cost. Runs on the
        CVaR-QAOA quantum simulator and against exact search; the signed receipt shows both and the plan is the proven
        best. Returns the slots, cost, and savings over charging right away. A plan only: nothing is sent to a charger."""
        data = {"price_per_kwh": price_per_kwh, "charger_kw": charger_kw, "energy_needed_kwh": energy_needed_kwh,
                "slot_hours": slot_hours, "switch_penalty_usd": switch_penalty_usd}
        return await plan("car_charge_plan", carlib.plan_charging, data)

    @mcp.tool(title="Privi Car: parked-car edge job gate (simulation)", annotations=WRITE)
    def car_edge_job(
        job: Annotated[dict[str, Any], Field(description="{tenant, nonce (32 hex), expiresAt (ms, within 60 s), payload (text up to 64 KB)}")],
        policy: Annotated[dict[str, Any], Field(description="{tenant, ownerOptIn, parked, externalPower, thermalSafe}; all four flags must be true")],
    ) -> CallToolResult:
        """Research simulation of the admission gate for compute on a parked car's companion device. A job is admitted
        only with owner opt-in, vehicle parked, external power and safe temperature, a matching tenant, a fresh nonce
        and a short expiry; replays are rejected. Returns a digest receipt with zero credits. No job runs on any
        vehicle and no rewards are paid."""
        return guard(carlib.verify_edge_job, job, policy, cars)

    # ---------------- public pages ----------------

    @route("/car/keys/{key_id}.json", methods=["GET"], include_in_schema=False)
    async def key_json(request: Request) -> Response:
        try:
            return JSONResponse(cars.key_status(request.path_params["key_id"]), headers=NOSTORE)
        except CarError as e:
            return JSONResponse({"error": str(e)}, status_code=e.status, headers=NOSTORE)

    @route("/car/{vehicle_id}.json", methods=["GET"], include_in_schema=False)
    async def vehicle_json(request: Request) -> Response:
        try:
            return JSONResponse(cars.public(request.path_params["vehicle_id"]), headers=NOSTORE)
        except CarError as e:
            return JSONResponse({"error": str(e)}, status_code=e.status, headers=NOSTORE)

    @route("/car/{vehicle_id}", methods=["GET"], include_in_schema=False)
    async def vehicle_page(request: Request) -> Response:
        vid = request.path_params["vehicle_id"]
        if not vid.startswith("car_"):
            return HTMLResponse(_doc("Privi Car", "<h1>Privi Car</h1><p>No passport at this address.</p>"), status_code=404)
        try:
            p = cars.public(vid)
        except CarError:
            return HTMLResponse(_doc("Privi Car", "<h1>Privi Car</h1><p>No passport at this address.</p>"), status_code=404)
        e = html.escape
        ok = p["chain_intact"] and not p["odometer_rollbacks"]
        badge = ("✅ Records intact" if ok else "⚠️ Odometer rollback on record" if p["chain_intact"] else "❌ Record chain broken")
        body = (f"<h1>Privi Car passport</h1><div class=card><h2>{p['year']} {e(p['make'])} {e(p['model'])}</h2>"
                f"<p><b>{badge}</b></p><p class=mute>{p['records']} sealed records · {e(p['powertrain'])} · registered {e(p['registered_at'][:10])}</p>"
                f"<p class=mute>Vehicle ID<br><code>{e(p['vehicle_id'])}</code></p>"
                f"<p class=mute>Chain head<br><code>{e(p['head_hash'])}</code></p>"
                + (f"<p class=mute>VIN fingerprint (SHA-256)<br><code>{e(p['vin_fingerprint'])}</code></p>" if p["vin_fingerprint"] else "")
                + f"<p><a href=\"{e(public_url)}/attestations/{e(p['passport_attestation'])}\">Signed passport (Ed25519 + ML-DSA-87)</a></p></div>"
                "<div class=card><p class=mute>The full history is private. Ask the owner for a history key, then call "
                f"<code>car_history</code>.</p><p class=mute>{e(BOUNDARIES)}</p></div>")
        return HTMLResponse(_doc(f"Privi Car passport {vid}", body), headers=NOSTORE)

    @route("/car", methods=["GET"], include_in_schema=False)
    async def car_home(_: Request) -> Response:
        st = cars.stats()
        rows = "".join(f"<tr><td><code>{t}</code></td><td>${p}</td></tr>" for t, p in PRICES.items())
        body = ("<h1>Privi Car</h1><p>Proof and planning for any vehicle, from Privi Quantum.</p>"
                "<div class=card><h2>What you get</h2><ul>"
                "<li><b>Vehicle Passport.</b> A post-quantum signed identity for one vehicle.</li>"
                "<li><b>Sealed records.</b> Odometer, service, repairs, trips, fuel and charging in a hash chain. "
                "Odometer rollbacks are flagged.</li>"
                "<li><b>Digital keys.</b> Time-limited, revocable credentials for a driver, valet, shop or buyer.</li>"
                "<li><b>History report.</b> A signed report a buyer can check.</li>"
                "<li><b>Route, fleet and charging plans.</b> Written as quantum problems, run on the quantum simulator "
                "when they fit in 16 qubits, and always checked against an exact classical answer.</li></ul></div>"
                f"<div class=card><h2>Prices per call</h2><table>{rows}</table>"
                "<p class=mute>Paid by x402 in USDC on Base, or the PRIVI token. A failed call is not charged.</p></div>"
                f"<div class=card><h2>Limits</h2><p class=mute>{html.escape(BOUNDARIES)}</p>"
                "<p class=mute>At these sizes a classical computer is as good or better; every receipt says which "
                "side won.</p>"
                f"<p class=mute>Vehicles: {st['vehicles']} · Records: {st['records']} · Keys issued: {st['keys_issued']}</p></div>"
                f"<p class=mute>Connect an AI agent: <code>{html.escape(public_url)}/mcp</code>, then call <code>car_info</code>.</p>")
        return HTMLResponse(_doc("Privi Car", body))


def _doc(title: str, body: str) -> str:
    return (f"<!DOCTYPE html><html lang=en><head><meta charset=utf-8><title>{html.escape(title)}</title>{_STYLE}"
            "<style>table{width:100%;border-collapse:collapse}td{padding:6px 4px;border-bottom:1px solid #e2e8f0}"
            "td:last-child{text-align:right}h2{font-size:19px;margin:0 0 8px}ul{padding-left:20px}li{margin:6px 0}</style>"
            f"</head><body>{body}<p class=mute>© 2026 Privi World Co.</p></body></html>")
