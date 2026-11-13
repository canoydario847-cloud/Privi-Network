# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Quantum - https://priviflow.us - dariocanoy@priviflow.us
"""Privi Car: a trust and planning platform for vehicles, built on Privi Quantum.

What it does
  Vehicle Passport   a post-quantum signed (Ed25519 + ML-DSA-87) identity for one vehicle. The VIN is checked
                     (ISO 3779 check digit) and kept only as a fingerprint, never in the clear.
  Sealed records     odometer, service, repair, inspection, trip, fuel and charge entries in a hash chain per vehicle.
                     Editing or removing an old entry breaks the chain; an odometer reading lower than an earlier one
                     is flagged as a rollback.
  Digital keys       time-limited, scope-limited credentials the owner hands to a driver, a valet, a shop or a buyer.
                     Signed with the same post-quantum keys, checkable by anyone, revocable at once.
  History report     a signed vehicle history (chain check, odometer timeline, rollback flags, service due, cost of
                     ownership) for the owner or anyone the owner gave a "history" key.
  Route / fleet /    quantum-style optimization. Each problem is written as a QUBO, the form a quantum computer takes.
  charging plans     Problems of 16 qubits or fewer run on the CVaR-QAOA simulator; every answer is checked against an
                     exact classical solver, and the plan returned is the best one found. The comparison is sealed.
  Edge jobs          the safety gate for running compute on a parked car's companion device: owner opt-in, parked,
                     external power, safe temperature, tenant match, replay protection. Simulated; pays no rewards.

What it does not do
  Privi Car never talks to a vehicle. No CAN bus, OBD writes, immobilizer, steering, braking, battery control or
  firmware. A digital key is a signed credential: a car or lock opens only if its maker (or a lock installer) builds in
  the check. Trips carry distance and time only, never location. Route stops are used for the calculation and are not
  stored; only a hash of the problem is sealed.

Honest note on "quantum": at these sizes a classical solver is as good or better, and the receipts say so. The value
is a tested path to quantum hardware plus proof of how each answer was reached.
"""
from __future__ import annotations

import hashlib
import hmac
import itertools
import json
import math
import re
import secrets
import sqlite3
import threading
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

import numpy as np
from scipy.optimize import linear_sum_assignment

from . import advantage, qaoa
from .qaoa import MAX_QUBITS, Qubo

BOUNDARIES = ("Privi Car never connects to or controls a vehicle: no CAN bus, OBD writes, immobilizer, steering, "
              "braking, battery control or firmware. Records, credentials and planning only.")
RECORD_TYPES = ("odometer", "service", "repair", "inspection", "trip", "fuel", "charge", "accident", "title", "note")
KEY_SCOPES = ("history", "unlock", "drive", "trunk", "valet", "service")
MAX_STOPS = 12            # Held-Karp exact route up to this many stops
MAX_FLEET_JOBS = 60
MAX_KEY_DAYS = 366
MI_TO_KM = 1.609344
EDGE_MAX_BYTES = 65536

SCHEMA = """
CREATE TABLE IF NOT EXISTS car_vehicles (
    vehicle_id TEXT PRIMARY KEY, owner_hash TEXT NOT NULL, make TEXT NOT NULL, model TEXT NOT NULL, year INTEGER NOT NULL,
    vin_fp TEXT, powertrain TEXT NOT NULL, service_km REAL NOT NULL, service_months INTEGER NOT NULL,
    passport_id TEXT NOT NULL, head_hash TEXT NOT NULL, seq INTEGER NOT NULL DEFAULT 0, max_odo_km REAL,
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS car_vin ON car_vehicles (vin_fp) WHERE vin_fp IS NOT NULL;
CREATE TABLE IF NOT EXISTS car_records (
    vehicle_id TEXT NOT NULL, seq INTEGER NOT NULL, type TEXT NOT NULL, body TEXT NOT NULL, prev_hash TEXT NOT NULL,
    entry_hash TEXT NOT NULL, flags TEXT NOT NULL DEFAULT '', recorded_at TEXT NOT NULL, PRIMARY KEY (vehicle_id, seq)
);
CREATE TABLE IF NOT EXISTS car_keys (
    key_id TEXT PRIMARY KEY, vehicle_id TEXT NOT NULL, secret_hash TEXT NOT NULL, scopes TEXT NOT NULL,
    grantee_sha TEXT NOT NULL, not_before TEXT NOT NULL, expires_at TEXT NOT NULL, attestation_id TEXT NOT NULL,
    revoked_at TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS car_edge_seen (id TEXT PRIMARY KEY, seen_at REAL NOT NULL);
"""

_NAME = re.compile(r"^[A-Za-z0-9 .&'/_-]{1,60}$")
_VIN = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")
_VIN_VAL = {**{str(d): d for d in range(10)}, **dict(zip("ABCDEFGH", range(1, 9))), **dict(zip("JKLMN", range(1, 6))),
            "P": 7, "R": 9, **dict(zip("STUVWXYZ", range(2, 10)))}
_VIN_W = (8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2)


class CarError(ValueError):
    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime | None = None) -> str:
    return (d or _now()).isoformat(timespec="seconds")


def _h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _canon(body: Any) -> str:
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _num(v: Any, what: str, lo: float = 0.0, hi: float = 1e9) -> float:
    if isinstance(v, bool):
        raise CarError(f"{what} must be a number")
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise CarError(f"{what} must be a number")
    if not math.isfinite(f) or not lo <= f <= hi:
        raise CarError(f"{what} must be between {lo:g} and {hi:g}")
    return f


def vin_check(vin: str) -> dict:
    """ISO 3779 format plus the North American check digit (position 9)."""
    v = re.sub(r"[\s-]", "", str(vin or "")).upper()
    if not _VIN.match(v):
        raise CarError("VIN must be 17 characters, letters and digits, without I, O or Q")
    r = sum(_VIN_VAL[c] * w for c, w in zip(v, _VIN_W)) % 11
    expect = "X" if r == 10 else str(r)
    return {"vin": v, "check_digit_ok": v[8] == expect, "fingerprint": _h("privi-car-vin-v1:" + v)}


# ------------------------------------------------------------------ optimization

def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371.0088 * math.asin(min(1.0, math.sqrt(h)))


def _point(p: Any, what: str) -> tuple[float, float]:
    if not isinstance(p, dict):
        raise CarError(f"{what} must be an object with lat and lon")
    return _num(p.get("lat"), f"{what}.lat", -90, 90), _num(p.get("lon"), f"{what}.lon", -180, 180)


def _labels(items: list, prefix: str) -> list[str]:
    out = [str(it.get("name") or f"{prefix}{i + 1}")[:80] if isinstance(it, dict) else f"{prefix}{i + 1}"
           for i, it in enumerate(items)]
    if len(set(out)) != len(out):
        raise CarError(f"{prefix} names must be unique")
    return out


def _matrix(m: Any, rows: int, cols: int, what: str) -> np.ndarray:
    if not isinstance(m, list) or len(m) != rows or any(not isinstance(r, list) or len(r) != cols for r in m):
        raise CarError(f"{what} must be a {rows} x {cols} list of lists")
    return np.array([[_num(v, what) for v in r] for r in m], dtype=float)


def tour_length(D: np.ndarray, order: list[int], round_trip: bool) -> float:
    total = sum(D[a, b] for a, b in zip(order, order[1:]))
    return float(total + (D[order[-1], order[0]] if round_trip else 0.0))


def held_karp(D: np.ndarray, round_trip: bool) -> dict:
    """Exact shortest route starting at stop 0 (dynamic programming over subsets)."""
    t0 = time.perf_counter()
    n = D.shape[0]
    m = n - 1
    if m == 0:
        return {"order": [0], "km": 0.0, "runtime_ms": 0.0}
    best: dict[tuple[int, int], tuple[float, int]] = {(1 << j, j): (float(D[0, j + 1]), -1) for j in range(m)}
    for size in range(2, m + 1):
        for subset in itertools.combinations(range(m), size):
            mask = sum(1 << j for j in subset)
            for j in subset:
                prev = mask ^ (1 << j)
                best[(mask, j)] = min((best[(prev, k)][0] + float(D[k + 1, j + 1]), k) for k in subset if k != j)
    full = (1 << m) - 1
    cost, last = min((best[(full, j)][0] + (float(D[j + 1, 0]) if round_trip else 0.0), j) for j in range(m))
    order, mask = [], full
    while last != -1:
        order.append(last + 1)
        mask, last = mask ^ (1 << last), best[(mask, last)][1]
    order = [0] + order[::-1]
    return {"order": order, "km": float(cost), "runtime_ms": round((time.perf_counter() - t0) * 1000, 3)}


def nearest_neighbor(D: np.ndarray, round_trip: bool) -> dict:
    t0 = time.perf_counter()
    order, left = [0], set(range(1, D.shape[0]))
    while left:
        nxt = min(left, key=lambda j: (D[order[-1], j], j))
        order.append(nxt)
        left.discard(nxt)
    return {"order": order, "km": tour_length(D, order, round_trip), "runtime_ms": round((time.perf_counter() - t0) * 1000, 3)}


def route_qubo(D: np.ndarray, round_trip: bool) -> tuple[Qubo, Callable]:
    """x[i,t] = 1 when stop i+1 is visited t-th after the start. (n-1)^2 qubits."""
    m = D.shape[0] - 1
    A = float(D.max()) * (m + 1) + 1.0          # one broken rule costs more than any whole route
    idx = lambda i, t: i * m + t
    Q = np.zeros((m * m, m * m))

    def one_hot(group: list[int]) -> None:      # A * (sum - 1)^2 without the constant
        for a in group:
            Q[a, a] -= A
            for b in group:
                if a < b:
                    Q[a, b] += 2 * A
    for i in range(m):
        one_hot([idx(i, t) for t in range(m)])
    for t in range(m):
        one_hot([idx(i, t) for i in range(m)])
    for i in range(m):
        Q[idx(i, 0), idx(i, 0)] += D[0, i + 1]
        if round_trip:
            Q[idx(i, m - 1), idx(i, m - 1)] += D[i + 1, 0]
        for j in range(m):
            if i != j:
                for t in range(m - 1):
                    a, b = idx(i, t), idx(j, t + 1)
                    Q[min(a, b), max(a, b)] += D[i + 1, j + 1]

    def decode(x: list[int]) -> list[int] | None:
        grid = np.array(x).reshape(m, m)
        if not (np.all(grid.sum(0) == 1) and np.all(grid.sum(1) == 1)):
            return None
        return [0] + [int(np.argmax(grid[:, t])) + 1 for t in range(m)]
    return Qubo(Q, 2 * m * A), decode


def assign_qubo(C: np.ndarray, cap: int) -> tuple[Qubo, Callable]:
    """x[j,v] = 1 when job j goes to vehicle v. Each job exactly once; cap 1 adds one-job-per-vehicle penalties."""
    n, m = C.shape
    A = float(C.max()) * n + 1.0
    Q = np.zeros((n * m, n * m))
    for j in range(n):
        g = [j * m + v for v in range(m)]
        for a in g:
            Q[a, a] += C[j, a - j * m] - A
            for b in g:
                if a < b:
                    Q[a, b] += 2 * A
    if cap == 1:                                 # at most one job per vehicle needs no slack qubits
        for v in range(m):
            for j in range(n):
                for j2 in range(j + 1, n):
                    Q[j * m + v, j2 * m + v] += A

    def decode(x: list[int]) -> list[int] | None:
        grid = np.array(x).reshape(n, m)
        if not np.all(grid.sum(1) == 1) or np.any(grid.sum(0) > cap):
            return None
        return [int(np.argmax(grid[j])) for j in range(n)]
    return Qubo(Q, n * A), decode


def charge_qubo(cost: np.ndarray, k: int, switch: float) -> Qubo:
    """Pick exactly k slots at least cost; `switch` is charged for every start or stop inside the window."""
    n = len(cost)
    A = float(cost.sum()) + 2 * switch * n + 1.0
    Q = np.zeros((n, n))
    for i in range(n):
        Q[i, i] += cost[i] + A * (1 - 2 * k)
        for j in range(i + 1, n):
            Q[i, j] += 2 * A
    for i in range(n - 1):
        Q[i, i] += switch
        Q[i + 1, i + 1] += switch
        Q[i, i + 1] -= 2 * switch
    return Qubo(Q, A * k * k)


def quantum_path(qubo: Qubo, decode: Callable, seed: int, layers: int = 2, shots: int = 2048) -> dict:
    """Run CVaR-QAOA on the simulator and keep the best measured answer that obeys the rules."""
    r = qaoa.solve(qubo, layers=layers, shots=shots, seed=seed)
    answer = decode(r["solution"])
    return {"method": r["algorithm"], "backend": "local", "backend_kind": "simulator", "qubits": qubo.n, "shots": shots,
            "valid_answer": answer is not None, "answer": answer, "runtime_ms": float(r["runtime_ms"]),
            "probability_of_optimum": r["probability_of_optimum"], "amplification": r["amplification"]}


def _verdict(q_cost: float | None, exact_cost: float, skipped: str = "") -> dict:
    if skipped:
        return {"verdict": "classical_only", "why": skipped + " Solved exactly on classical hardware."}
    if q_cost is None:
        return {"verdict": "classical_won", "why": "the quantum samples held no answer that obeyed every rule"}
    if q_cost <= exact_cost + 1e-9 * max(1.0, abs(exact_cost)):
        return {"verdict": "tie", "why": "the quantum path reached the proven optimum; the classical solver was faster"}
    return {"verdict": "classical_won", "why": "the exact classical solver found a better plan than the quantum samples"}


def _too_big(qubits: int) -> str:
    return (f"This problem needs {qubits} qubits and the simulator runs {MAX_QUBITS}; quantum_run_hardware reaches "
            "real quantum computers.")


def plan_route(data: dict, seed: int = 7) -> dict:
    stops = data.get("stops")
    if not isinstance(stops, list) or not 2 <= len(stops) <= MAX_STOPS:
        raise CarError(f"give 2-{MAX_STOPS} stops as [{{name, lat, lon}}]; the first is where the trip starts")
    n = len(stops)
    names = _labels(stops, "stop")
    if data.get("distances_km") is not None:
        D = _matrix(data["distances_km"], n, n, "distances_km")
    else:
        pts = [_point(s, f"stops[{i}]") for i, s in enumerate(stops)]
        D = np.array([[haversine_km(a, b) for b in pts] for a in pts])
    np.fill_diagonal(D, 0.0)
    if float(D.max()) <= 0:
        raise CarError("every stop is in the same place; nothing to plan")
    round_trip = bool(data.get("round_trip", True))
    exact, greedy = held_karp(D, round_trip), nearest_neighbor(D, round_trip)
    given = tour_length(D, list(range(n)), round_trip)
    qubits = (n - 1) ** 2
    quantum, skipped = None, ""
    if n == 2 or (n == 3 and round_trip):
        skipped = "There is only one possible route for these stops."
    elif qubits > MAX_QUBITS:
        skipped = _too_big(qubits)
    else:
        qubo, decode = route_qubo(D, round_trip)
        quantum = quantum_path(qubo, decode, seed)
        order = quantum.pop("answer")
        quantum["km"] = tour_length(D, order, round_trip) if order else None
        quantum["order"] = order
    v = _verdict(quantum["km"] if quantum else None, exact["km"], skipped)
    best = exact["order"]
    return {
        "plan": {"order": [names[i] for i in best], "round_trip": round_trip, "km": round(exact["km"], 3),
                 "km_in_the_order_given": round(given, 3), "km_saved": round(given - exact["km"], 3),
                 "percent_saved": round(100 * (given - exact["km"]) / given, 1) if given > 0 else 0.0,
                 "distance_basis": "your distances_km" if data.get("distances_km") is not None
                 else "straight-line (great-circle) distance between stops, not road distance"},
        "sealed": {"problem": "car_route", "stops": n, "qubits": qubits, "round_trip": round_trip,
                   "quantum": ({k: quantum[k] for k in quantum if k != "order"} if quantum else None),
                   "classical": [{"method": "held_karp_exact", "km": round(exact["km"], 6), "runtime_ms": exact["runtime_ms"]},
                                 {"method": "nearest_neighbor", "km": round(greedy["km"], 6), "runtime_ms": greedy["runtime_ms"]}],
                   **v},
    }


def plan_fleet(data: dict, seed: int = 7) -> dict:
    jobs, vehicles = data.get("jobs"), data.get("vehicles")
    if not isinstance(jobs, list) or not isinstance(vehicles, list) or not jobs or not vehicles:
        raise CarError("give jobs and vehicles as lists")
    n, m = len(jobs), len(vehicles)
    if n > MAX_FLEET_JOBS or m > MAX_FLEET_JOBS:
        raise CarError(f"up to {MAX_FLEET_JOBS} jobs and {MAX_FLEET_JOBS} vehicles")
    jn, vn = _labels(jobs, "job"), _labels(vehicles, "vehicle")
    if data.get("cost") is not None:
        C = _matrix(data["cost"], n, m, "cost")
        basis = "your cost matrix"
    else:
        jp = [_point(j, f"jobs[{i}]") for i, j in enumerate(jobs)]
        vp = [_point(v, f"vehicles[{i}]") for i, v in enumerate(vehicles)]
        C = np.array([[haversine_km(j, v) for v in vp] for j in jp])
        basis = "straight-line km from each vehicle to each job"
    cap = int(_num(data.get("max_jobs_per_vehicle", math.ceil(n / m)), "max_jobs_per_vehicle", 1, n))
    if cap * m < n:
        raise CarError("not enough vehicle capacity for every job; raise max_jobs_per_vehicle or add vehicles")
    t0 = time.perf_counter()
    rows, cols = linear_sum_assignment(np.repeat(C, cap, axis=1))
    assign = [0] * n
    for r, c in zip(rows, cols):
        assign[int(r)] = int(c) // cap
    exact_cost = float(sum(C[j, assign[j]] for j in range(n)))
    exact_ms = round((time.perf_counter() - t0) * 1000, 3)
    greedy = _greedy_assign(C, cap)
    qubits = n * m
    quantum, skipped = None, ""
    if qubits > MAX_QUBITS:
        skipped = _too_big(qubits)
    elif qubits < 2 or float(C.max()) == float(C.min()):
        skipped = "Every plan costs the same; nothing to optimize."
    elif 1 < cap < n:
        skipped = ("A per-vehicle limit between 1 and the job count needs extra slack qubits, which this version does "
                   "not build.")
    else:
        qubo, decode = assign_qubo(C, cap)
        quantum = quantum_path(qubo, decode, seed)
        a = quantum.pop("answer")
        quantum["cost"] = float(sum(C[j, a[j]] for j in range(n))) if a else None
    v = _verdict(quantum["cost"] if quantum else None, exact_cost, skipped)
    per: dict[str, list[str]] = {name: [] for name in vn}
    for j in range(n):
        per[vn[assign[j]]].append(jn[j])
    return {
        "plan": {"assignments": per, "total_cost": round(exact_cost, 3), "cost_basis": basis,
                 "max_jobs_per_vehicle": cap, "first_come_total_cost": round(greedy, 3),
                 "saved_vs_first_come": round(greedy - exact_cost, 3)},
        "sealed": {"problem": "car_fleet_assign", "jobs": n, "vehicles": m, "qubits": qubits, "quantum": quantum,
                   "classical": [{"method": "hungarian_exact", "cost": round(exact_cost, 6), "runtime_ms": exact_ms},
                                 {"method": "first_come_nearest", "cost": round(greedy, 6), "runtime_ms": 0.0}], **v},
    }


def _greedy_assign(C: np.ndarray, cap: int) -> float:
    load, total = [0] * C.shape[1], 0.0
    for j in range(C.shape[0]):
        v = min((v for v in range(C.shape[1]) if load[v] < cap), key=lambda v: (C[j, v], v))
        load[v] += 1
        total += float(C[j, v])
    return total


def plan_charging(data: dict, seed: int = 7) -> dict:
    prices = data.get("price_per_kwh")
    if not isinstance(prices, list) or not 2 <= len(prices) <= MAX_QUBITS:
        raise CarError(f"give price_per_kwh as 2-{MAX_QUBITS} numbers, one per time slot before you leave")
    p = np.array([_num(v, "price_per_kwh", 0, 1000) for v in prices])
    n = len(p)
    slot_h = _num(data.get("slot_hours", 1), "slot_hours", 0.05, 24)
    kw = _num(data.get("charger_kw"), "charger_kw", 0.1, 1000)
    need = _num(data.get("energy_needed_kwh"), "energy_needed_kwh", 0.01, 1000)
    per_slot = kw * slot_h
    k = math.ceil(need / per_slot - 1e-9)
    if k > n:
        raise CarError(f"{need:g} kWh needs {k} slots at {kw:g} kW; only {n} slots before you leave")
    switch = _num(data.get("switch_penalty_usd", 0), "switch_penalty_usd", 0, 1000)
    cost = p * per_slot
    if k == n or float(cost.max()) == float(cost.min()) and switch == 0:
        chosen, quantum, classical = list(range(k)), None, []
        v = _verdict(None, 0.0, "Only one sensible plan exists; nothing to optimize.")
    else:
        qubo = charge_qubo(cost, k, switch)
        classical = [advantage.exhaustive(qubo), advantage.simulated_annealing(qubo)]
        decode = lambda x: list(x) if sum(x) == k else None
        quantum = quantum_path(qubo, decode, seed)
        a = quantum.pop("answer")
        quantum["cost"] = qubo.cost(a) if a else None
        chosen = [i for i, b in enumerate(classical[0]["solution"]) if b]
        v = _verdict(quantum["cost"], classical[0]["cost"])
        classical = [{"method": c["method"], "cost": round(c["cost"], 6), "runtime_ms": c["runtime_ms"]} for c in classical]
    energy_cost = float(sum(cost[i] for i in chosen))
    asap = float(sum(cost[:k]))
    blocks = 1 + sum(1 for a, b in zip(chosen, chosen[1:]) if b != a + 1)
    return {
        "plan": {"charge_in_slots": chosen, "slots_needed": k, "slot_hours": slot_h,
                 "energy_delivered_kwh": round(k * per_slot, 3), "energy_cost_usd": round(energy_cost, 4),
                 "cost_if_charged_right_away_usd": round(asap, 4), "saved_usd": round(asap - energy_cost, 4),
                 "charging_blocks": blocks},
        "sealed": {"problem": "car_charge_plan", "slots": n, "slots_needed": k, "qubits": n, "quantum": quantum,
                   "classical": classical, **v},
    }


# ------------------------------------------------------------------ edge job gate

def verify_edge_job(job: Any, policy: Any, seen, now_ms: int | None = None) -> dict:
    """Admission gate for compute on a parked car's companion device (Python port of privi-car/worker.cjs).
    Fails closed. Simulated: no remote authentication, no rewards."""
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    if not isinstance(job, dict):
        raise CarError("invalid job")
    if not isinstance(policy, dict) or any(policy.get(k) is not True for k in ("ownerOptIn", "parked", "externalPower", "thermalSafe")):
        raise CarError("worker disabled: needs owner opt-in, parked, external power and safe temperature")
    tenant = job.get("tenant")
    if not isinstance(tenant, str) or tenant != policy.get("tenant") or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", tenant):
        raise CarError("tenant mismatch")
    nonce = job.get("nonce")
    if not isinstance(nonce, str) or not re.fullmatch(r"[a-f0-9]{32}", nonce):
        raise CarError("invalid nonce: 32 lowercase hex characters")
    exp = job.get("expiresAt")
    if isinstance(exp, bool) or not isinstance(exp, int) or exp < now_ms or exp > now_ms + 60000:
        raise CarError("invalid expiry: must be within the next 60 seconds")
    payload = job.get("payload")
    if not isinstance(payload, str) or len(payload.encode()) > EDGE_MAX_BYTES:
        raise CarError("invalid payload: text up to 64 KB")
    jid = f"{tenant}:{nonce}"
    if not seen.add_once(jid):
        raise CarError("replay")
    return {"status": "simulated", "tenant": tenant, "nonce": nonce, "digest": hashlib.sha256(payload.encode()).hexdigest(),
            "credits": 0}


class MemorySeen:
    def __init__(self):
        self._s: set[str] = set()

    def add_once(self, jid: str) -> bool:
        if jid in self._s:
            return False
        self._s.add(jid)
        return True


# ------------------------------------------------------------------ registry

class Car:
    def __init__(self, db_path: str, attestor, public_url: str):
        self._lock = threading.Lock()
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.commit()
        self.attestor, self.public_url = attestor, public_url.rstrip("/")

    # ---- replay store for edge jobs
    def add_once(self, jid: str) -> bool:
        with self._lock:
            self._db.execute("DELETE FROM car_edge_seen WHERE seen_at < ?", (time.time() - 3600,))
            try:
                self._db.execute("INSERT INTO car_edge_seen VALUES (?,?)", (_h(jid), time.time()))
                self._db.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    # ---- vehicles
    def register(self, make: str, model: str, year: int, vin: str = "", powertrain: str = "gas",
                 service_km: float = 10000, service_months: int = 12) -> dict:
        make, model = str(make or "").strip(), str(model or "").strip()
        if not _NAME.match(make) or not _NAME.match(model):
            raise CarError("make and model: 1-60 letters, digits, spaces or . & ' / _ -")
        year = int(_num(year, "year", 1886, _now().year + 2))
        if powertrain not in ("gas", "diesel", "hybrid", "plug_in_hybrid", "electric", "hydrogen", "other"):
            raise CarError("powertrain: gas | diesel | hybrid | plug_in_hybrid | electric | hydrogen | other")
        service_km = _num(service_km, "service_interval_km", 500, 100000)
        service_months = int(_num(service_months, "service_interval_months", 1, 60))
        v = vin_check(vin) if vin else None
        vid, key = "car_" + secrets.token_hex(8), "carkey_" + secrets.token_urlsafe(24)
        genesis = _h(f"privi-car-genesis-v1:{vid}")
        att = self.attestor.issue("car_passport", {
            "vehicle_id": vid, "make": make, "model": model, "year": year, "powertrain": powertrain,
            "vin_fingerprint": v["fingerprint"] if v else None, "vin_check_digit_ok": v["check_digit_ok"] if v else None,
            "chain_genesis": genesis, "boundaries": BOUNDARIES})
        with self._lock:
            try:
                self._db.execute("INSERT INTO car_vehicles VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                 (vid, _h(key), make, model, year, v["fingerprint"] if v else None, powertrain, service_km,
                                  service_months, att["id"], genesis, 0, None, _iso()))
                self._db.commit()
            except sqlite3.IntegrityError:
                raise CarError("a vehicle with this VIN already has a Privi Car passport", 409)
        return {"vehicle_id": vid, "owner_key": key,
                "owner_key_note": "shown once; whoever holds it controls this vehicle's records and keys",
                "passport": {"attestation_id": att["id"], "signatures": "Ed25519 + ML-DSA-87",
                             "url": f"{self.public_url}/car/{vid}"},
                "vin": ({"fingerprint": v["fingerprint"], "check_digit_ok": v["check_digit_ok"],
                         "note": None if v["check_digit_ok"] else
                         "check digit does not match: normal for many vehicles built for markets outside North America, "
                         "otherwise re-read the VIN"} if v else None),
                "boundaries": BOUNDARIES}

    def _vehicle(self, ref: str) -> dict:
        ref = str(ref or "").strip()
        with self._lock:
            if ref.startswith("car_"):
                r = self._db.execute("SELECT * FROM car_vehicles WHERE vehicle_id=?", (ref,)).fetchone()
            else:
                try:
                    fp = vin_check(ref)["fingerprint"]
                except CarError:
                    raise CarError("give a vehicle_id (car_...) or a 17-character VIN")
                r = self._db.execute("SELECT * FROM car_vehicles WHERE vin_fp=?", (fp,)).fetchone()
        if not r:
            raise CarError("no Privi Car passport for that vehicle", 404)
        return dict(r)

    def _owner(self, ref: str, owner_key: str) -> dict:
        v = self._vehicle(ref)
        if not hmac.compare_digest(v["owner_hash"], _h(str(owner_key or ""))):
            raise CarError("owner_key does not match this vehicle", 403)
        return v

    # ---- records
    def add_record(self, ref: str, owner_key: str, rtype: str, data: dict | None = None) -> dict:
        v = self._owner(ref, owner_key)
        if rtype not in RECORD_TYPES:
            raise CarError(f"type must be one of: {', '.join(RECORD_TYPES)}")
        d = dict(data or {})
        body: dict[str, Any] = {"type": rtype}
        unit = str(d.get("unit", "km")).lower()
        if unit not in ("km", "mi"):
            raise CarError("unit: km or mi")
        f = MI_TO_KM if unit == "mi" else 1.0
        if d.get("odometer") is not None:
            body["odometer_km"] = round(_num(d["odometer"], "odometer", 0, 5e6) * f, 1)
        elif rtype == "odometer":
            raise CarError("an odometer record needs data.odometer")
        if d.get("distance") is not None:
            body["distance_km"] = round(_num(d["distance"], "distance", 0, 1e5) * f, 2)
        for k, hi in (("duration_min", 1e5), ("liters", 2000), ("kwh", 2000), ("cost_usd", 1e7)):
            if d.get(k) is not None:
                body[k] = round(_num(d[k], k, 0, hi), 3)
        if d.get("summary"):
            body["summary"] = str(d["summary"])[:500]
        on = str(d.get("date") or _now().date().isoformat())
        try:
            when = date.fromisoformat(on)
        except ValueError:
            raise CarError("date must be YYYY-MM-DD")
        if when > _now().date() + timedelta(days=1):
            raise CarError("date cannot be in the future")
        body["date"] = when.isoformat()
        if any(k in d for k in ("lat", "lon", "location", "address", "route")):
            raise CarError("Privi Car does not store location; remove lat, lon, location, address and route")
        with self._lock:
            cur = dict(self._db.execute("SELECT * FROM car_vehicles WHERE vehicle_id=?", (v["vehicle_id"],)).fetchone())
            seq, flags = cur["seq"] + 1, []
            odo, top = body.get("odometer_km"), cur["max_odo_km"]
            if odo is not None and top is not None and odo < top:
                flags.append("odometer_rollback")
            rec_at = _iso()
            entry = _h(_canon({"vehicle_id": cur["vehicle_id"], "seq": seq, "prev_hash": cur["head_hash"], "body": body,
                               "recorded_at": rec_at}))
            self._db.execute("INSERT INTO car_records VALUES (?,?,?,?,?,?,?,?)",
                             (cur["vehicle_id"], seq, rtype, _canon(body), cur["head_hash"], entry, ",".join(flags), rec_at))
            self._db.execute("UPDATE car_vehicles SET seq=?, head_hash=?, max_odo_km=? WHERE vehicle_id=?",
                             (seq, entry, max(odo, top) if odo is not None and top is not None else (odo if odo is not None else top),
                              cur["vehicle_id"]))
            self._db.commit()
        return {"vehicle_id": cur["vehicle_id"], "seq": seq, "entry_hash": entry, "prev_hash": cur["head_hash"],
                "flags": flags, "recorded": body,
                "warning": ("this odometer reading is lower than an earlier one; it is recorded and flagged as a rollback"
                            if flags else None)}

    def _records(self, vid: str) -> list[dict]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM car_records WHERE vehicle_id=? ORDER BY seq", (vid,)).fetchall()
        return [dict(r) for r in rows]

    def verify_chain(self, ref: str) -> dict:
        v = self._vehicle(ref)
        prev, broken = _h(f"privi-car-genesis-v1:{v['vehicle_id']}"), None
        recs = self._records(v["vehicle_id"])
        for i, r in enumerate(recs, 1):
            want = _h(_canon({"vehicle_id": v["vehicle_id"], "seq": r["seq"], "prev_hash": prev, "body": json.loads(r["body"]),
                              "recorded_at": r["recorded_at"]}))
            if r["seq"] != i or r["prev_hash"] != prev or r["entry_hash"] != want:
                broken = r["seq"]
                break
            prev = r["entry_hash"]
        ok = broken is None and prev == v["head_hash"] and len(recs) == v["seq"]
        return {"vehicle_id": v["vehicle_id"], "records": len(recs), "chain_intact": ok, "first_broken_seq": broken,
                "head_hash": v["head_hash"], "rollback_flags": sum(1 for r in recs if "odometer_rollback" in r["flags"])}

    # ---- digital keys
    def issue_key(self, ref: str, owner_key: str, grantee: str, scopes: list[str], hours: float = 24,
                  not_before: str = "") -> dict:
        v = self._owner(ref, owner_key)
        scopes = sorted({str(s) for s in (scopes or [])})
        if not scopes or any(s not in KEY_SCOPES for s in scopes):
            raise CarError(f"scopes: one or more of {', '.join(KEY_SCOPES)}")
        grantee = str(grantee or "").strip()
        if not 1 <= len(grantee) <= 120:
            raise CarError("grantee: who the key is for (1-120 characters)")
        hours = _num(hours, "hours", 0.05, MAX_KEY_DAYS * 24)
        start = _now()
        if not_before:
            try:
                start = datetime.fromisoformat(not_before.replace("Z", "+00:00"))
                start = start if start.tzinfo else start.replace(tzinfo=timezone.utc)
            except ValueError:
                raise CarError("not_before must be an ISO 8601 time")
        end = start + timedelta(hours=hours)
        kid, secret = "ck_" + secrets.token_hex(8), secrets.token_urlsafe(24)
        g_sha = _h("privi-car-grantee-v1:" + grantee)
        att = self.attestor.issue("car_key", {
            "key_id": kid, "vehicle_id": v["vehicle_id"], "scopes": scopes, "grantee_sha256": g_sha,
            "not_before": _iso(start), "expires_at": _iso(end),
            "status_url": f"{self.public_url}/car/keys/{kid}.json",
            "note": "a credential, not a remote control: a car or lock honors it only if built to check it"})
        with self._lock:
            self._db.execute("INSERT INTO car_keys VALUES (?,?,?,?,?,?,?,?,?,?)",
                             (kid, v["vehicle_id"], _h(secret), ",".join(scopes), g_sha, _iso(start), _iso(end), att["id"],
                              None, _iso()))
            self._db.commit()
        return {"key_id": kid, "token": f"pck_{kid}.{secret}", "token_note": "shown once; give it only to the grantee",
                "vehicle_id": v["vehicle_id"], "scopes": scopes, "not_before": _iso(start), "expires_at": _iso(end),
                "attestation_id": att["id"], "signatures": "Ed25519 + ML-DSA-87"}

    def _key_row(self, kid: str) -> dict:
        with self._lock:
            r = self._db.execute("SELECT * FROM car_keys WHERE key_id=?", (kid,)).fetchone()
        if not r:
            raise CarError("no such key", 404)
        return dict(r)

    def key_status(self, kid: str) -> dict:
        r = self._key_row(kid)
        now = _now()
        state = ("revoked" if r["revoked_at"] else "expired" if now >= datetime.fromisoformat(r["expires_at"])
                 else "not_yet_valid" if now < datetime.fromisoformat(r["not_before"]) else "valid")
        return {"key_id": kid, "vehicle_id": r["vehicle_id"], "state": state, "scopes": r["scopes"].split(","),
                "not_before": r["not_before"], "expires_at": r["expires_at"], "revoked_at": r["revoked_at"],
                "attestation_id": r["attestation_id"]}

    def check_key(self, token: str, scope: str = "") -> dict:
        m = re.fullmatch(r"pck_(ck_[0-9a-f]{16})\.([A-Za-z0-9_-]{20,80})", str(token or ""))
        if not m:
            return {"allowed": False, "reason": "not a Privi Car key token"}
        try:
            r = self._key_row(m.group(1))
        except CarError:
            return {"allowed": False, "reason": "unknown key"}
        if not hmac.compare_digest(r["secret_hash"], _h(m.group(2))):
            return {"allowed": False, "reason": "unknown key"}
        st = self.key_status(r["key_id"])
        if st["state"] != "valid":
            return {"allowed": False, "reason": st["state"], **st}
        if scope and scope not in st["scopes"]:
            return {"allowed": False, "reason": f"this key does not carry the '{scope}' scope", **st}
        return {"allowed": True, **st}

    def revoke_key(self, ref: str, owner_key: str, kid: str) -> dict:
        v = self._owner(ref, owner_key)
        r = self._key_row(kid)
        if r["vehicle_id"] != v["vehicle_id"]:
            raise CarError("that key belongs to another vehicle", 403)
        with self._lock:
            self._db.execute("UPDATE car_keys SET revoked_at=COALESCE(revoked_at, ?) WHERE key_id=?", (_iso(), kid))
            self._db.commit()
        return self.key_status(kid)

    # ---- history
    def history(self, ref: str, access: str) -> dict:
        v = self._vehicle(ref)
        access = str(access or "")
        if access.startswith("pck_"):
            c = self.check_key(access, "history")
            if not c["allowed"] or c["vehicle_id"] != v["vehicle_id"]:
                raise CarError("that key does not open this vehicle's history: " + c.get("reason", "wrong vehicle"), 403)
            viewer = "history key " + c["key_id"]
        elif hmac.compare_digest(v["owner_hash"], _h(access)):
            viewer = "owner"
        else:
            raise CarError("give the owner_key, or a key token with the 'history' scope from the owner", 403)
        chain = self.verify_chain(v["vehicle_id"])
        recs = self._records(v["vehicle_id"])
        entries, odo, spend, by_type = [], [], {}, {}
        last_service = None
        for r in recs:
            b = json.loads(r["body"])
            entries.append({"seq": r["seq"], **b, "flags": [f for f in r["flags"].split(",") if f], "entry_hash": r["entry_hash"]})
            by_type[r["type"]] = by_type.get(r["type"], 0) + 1
            if "odometer_km" in b:
                odo.append({"date": b["date"], "km": b["odometer_km"], "rollback": "odometer_rollback" in r["flags"]})
            if "cost_usd" in b:
                spend[r["type"]] = round(spend.get(r["type"], 0.0) + b["cost_usd"], 2)
            if r["type"] == "service":
                last_service = b
        service = {"interval_km": v["service_km"], "interval_months": v["service_months"], "last": last_service}
        if last_service:
            due_date = _add_months(date.fromisoformat(last_service["date"]), v["service_months"])
            service["next_due_date"] = due_date.isoformat()
            overdue = _now().date() > due_date
            if last_service.get("odometer_km") is not None and v["max_odo_km"] is not None:
                service["next_due_km"] = last_service["odometer_km"] + v["service_km"]
                service["km_until_due"] = round(service["next_due_km"] - v["max_odo_km"], 1)
                overdue = overdue or service["km_until_due"] < 0
            service["overdue"] = overdue
        else:
            service["note"] = "no service on record"
        summary = {"vehicle_id": v["vehicle_id"], "make": v["make"], "model": v["model"], "year": v["year"],
                   "powertrain": v["powertrain"], "records": len(recs), "records_by_type": by_type,
                   "chain_intact": chain["chain_intact"], "head_hash": chain["head_hash"],
                   "odometer_rollbacks": chain["rollback_flags"], "highest_odometer_km": v["max_odo_km"],
                   "accidents_on_record": by_type.get("accident", 0), "spend_usd_by_type": spend,
                   "spend_usd_total": round(sum(spend.values()), 2)}
        att = self.attestor.issue("car_history_report", {
            **summary, "passport_attestation": v["passport_id"], "entries_sha256": _h(_canon(entries)), "viewer": viewer,
            "limits": "built from what the owner recorded; Privi does not inspect the vehicle or query outside databases"})
        return {"report_id": att["id"], "summary": summary, "service": service, "odometer_timeline": odo, "entries": entries,
                "signatures": "Ed25519 + ML-DSA-87", "attestation_url": f"{self.public_url}/attestations/{att['id']}",
                "limits": "built from what the owner recorded; Privi does not inspect the vehicle or query outside databases"}

    def public(self, ref: str) -> dict:
        v = self._vehicle(ref)
        c = self.verify_chain(v["vehicle_id"])
        return {"vehicle_id": v["vehicle_id"], "make": v["make"], "model": v["model"], "year": v["year"],
                "powertrain": v["powertrain"], "vin_fingerprint": v["vin_fp"], "passport_attestation": v["passport_id"],
                "registered_at": v["created_at"], "records": c["records"], "chain_intact": c["chain_intact"],
                "head_hash": c["head_hash"], "odometer_rollbacks": c["rollback_flags"],
                "history": "private: the owner shares it with a 'history' key"}

    def stats(self) -> dict:
        with self._lock:
            n = self._db.execute("SELECT COUNT(*) FROM car_vehicles").fetchone()[0]
            r = self._db.execute("SELECT COUNT(*) FROM car_records").fetchone()[0]
            k = self._db.execute("SELECT COUNT(*) FROM car_keys").fetchone()[0]
        return {"vehicles": n, "records": r, "keys_issued": k}


def _add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    y, m = d.year + y, m + 1
    last = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)).day
    return date(y, m, min(d.day, last))
