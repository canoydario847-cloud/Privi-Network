# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Quantum - https://priviflow.us - dariocanoy@priviflow.us
"""Privi Kingston: run Privi Quantum well on IBM Quantum ibm_kingston (156-qubit Heron r2, CZ gates).

What this module adds on top of plain "transpile and send":

  1. Calibration snapshot. Before each job Privi reads the backend's live calibration (per-qubit
     readout error, T1, T2 and every two-qubit gate error), keeps a plain-JSON copy and hashes it.
     The hash goes into the signed attestation, so anyone can see which calibration a result ran on.
  2. Best-qubit layout. Instead of letting the transpiler start anywhere on the chip, Privi picks the
     connected group of physical qubits with the lowest readout + two-qubit error for the job's size,
     and pins the circuit there (initial_layout, optimization level 3).
  3. Error suppression. Dynamical decoupling (XY4) and gate + measurement twirling on SamplerV2.
  4. Readout-error mitigation. Measured counts are corrected with the per-qubit readout confusion
     matrices from the same calibration (tensored inverse, clipped to a valid distribution). Raw counts
     are kept and sealed too; mitigated numbers are reported next to them, never instead of them.
  5. Open Plan minute guard. IBM's Open Plan gives a fixed number of QPU seconds per rolling window
     (10 minutes per 28 days at the time of writing). Privi keeps its own meter of quantum seconds used,
     refuses a job that would run past the budget, and syncs with IBM's own usage figure when it can.

Nothing here needs qiskit to import: the qiskit-facing helpers take duck-typed objects, so the logic
is tested without IBM credentials.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import threading
import time
from typing import Any, Iterable

import numpy as np

from .attest import now_iso

TWO_QUBIT_GATES = ("cz", "ecr", "cx")
MAX_MITIGATION_QUBITS = 20          # dense 2^n correction beyond this is too big for a web server
UNUSABLE_ERROR = 0.25               # qubits or couplers worse than this are left out of layouts

USAGE_SCHEMA = """
CREATE TABLE IF NOT EXISTS ibm_usage (
    provider_job_id TEXT PRIMARY KEY, backend TEXT NOT NULL, est_s REAL NOT NULL, actual_s REAL,
    status TEXT NOT NULL, ts REAL NOT NULL);
CREATE TABLE IF NOT EXISTS ibm_usage_sync (
    id INTEGER PRIMARY KEY CHECK (id = 1), remaining_s REAL, limit_s REAL, consumed_s REAL, ts REAL NOT NULL);
"""


# ----------------------------------------------------------------- calibration

def _num(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def snapshot_from_backend(backend: Any) -> dict:
    """Read a qiskit BackendV2's calibration into plain JSON.

    Uses backend.target (measure + two-qubit gate errors, qubit T1/T2) and, when present,
    backend.properties() for the asymmetric readout probabilities prob_meas1_prep0 / prob_meas0_prep1.
    """
    target = backend.target
    n = int(getattr(target, "num_qubits", 0) or getattr(backend, "num_qubits", 0))
    names = set(getattr(target, "operation_names", []) or [])
    gate2 = next((g for g in TWO_QUBIT_GATES if g in names), None)
    props = None
    try:
        props = backend.properties()
    except Exception:  # noqa: BLE001  (properties are optional on newer backends)
        props = None
    qubits: dict[str, dict] = {}
    meas = target["measure"] if "measure" in names else {}
    for q in range(n):
        ip = meas.get((q,)) if meas else None
        ro = _num(getattr(ip, "error", None)) if ip is not None else None
        p01 = p10 = None
        if props is not None:
            try:
                p01 = _num(props.qubit_property(q, "prob_meas1_prep0")[0])
                p10 = _num(props.qubit_property(q, "prob_meas0_prep1")[0])
            except Exception:  # noqa: BLE001
                p01 = p10 = None
        if p01 is None or p10 is None:
            p01 = p10 = ro
        if ro is None and p01 is not None:
            ro = (p01 + p10) / 2
        qp = None
        try:
            qp = target.qubit_properties[q] if target.qubit_properties else None
        except (IndexError, TypeError, AttributeError):
            qp = None
        t1, t2 = _num(getattr(qp, "t1", None)), _num(getattr(qp, "t2", None))
        qubits[str(q)] = {"readout_error": ro, "p01": p01, "p10": p10,
                          "t1_us": round(t1 * 1e6, 2) if t1 else None, "t2_us": round(t2 * 1e6, 2) if t2 else None}
    edges = []
    if gate2:
        best: dict[tuple[int, int], float] = {}
        for qargs, ip in (target[gate2] or {}).items():
            if not qargs or len(qargs) != 2:
                continue
            e = _num(getattr(ip, "error", None))
            if e is None:
                continue
            a, b = sorted(int(x) for x in qargs)
            best[(a, b)] = min(e, best.get((a, b), 1.0))
        edges = [[a, b, round(e, 6)] for (a, b), e in sorted(best.items())]
    calibrated = None
    if props is not None:
        lu = getattr(props, "last_update_date", None)
        calibrated = lu.isoformat() if hasattr(lu, "isoformat") else (str(lu) if lu else None)
    return {"backend": getattr(backend, "name", "") if isinstance(getattr(backend, "name", ""), str) else str(backend.name),
            "num_qubits": n, "two_qubit_gate": gate2, "calibrated_at": calibrated, "taken_at": now_iso(),
            "qubits": qubits, "edges": edges}


def calibration_sha256(snap: dict) -> str:
    """Hash of the calibration numbers (not of when Privi read them), so two reads of one calibration match."""
    body = {k: snap.get(k) for k in ("backend", "num_qubits", "two_qubit_gate", "calibrated_at", "qubits", "edges")}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _usable(snap: dict) -> tuple[dict[int, float], dict[int, dict[int, float]]]:
    ro = {}
    for q, d in snap["qubits"].items():
        e = d.get("readout_error")
        if e is not None and e < UNUSABLE_ERROR:
            ro[int(q)] = float(e)
    adj: dict[int, dict[int, float]] = {q: {} for q in ro}
    for a, b, e in snap.get("edges", []):
        if a in ro and b in ro and e < UNUSABLE_ERROR:
            adj[a][b] = adj[b][a] = float(e)
    return ro, adj


def best_layout(snap: dict, n: int) -> dict | None:
    """The connected group of n physical qubits with the lowest error.

    Greedy growth from every usable seed qubit: add the neighbour that adds the least
    (readout error + error of the coupler that joins it). Logical qubit i maps to physical[i]
    in growth order, so consecutive logical qubits sit next to each other on the chip.
    Returns None when the chip has fewer than n usable connected qubits.
    """
    ro, adj = _usable(snap)
    if n <= 0 or len(ro) < n:
        return None
    if n == 1:
        q = min(ro, key=ro.get)
        return {"physical_qubits": [q], "couplers": [], "score": round(ro[q], 6),
                "estimated_fidelity": round(1 - ro[q], 6)}
    best = None
    for seed in ro:
        if not adj[seed]:
            continue
        chosen, used, score = [seed], [], ro[seed]
        inside = {seed}
        while len(chosen) < n:
            pick = None
            for a in chosen:
                for b, e in adj[a].items():
                    if b in inside:
                        continue
                    add = ro[b] + e
                    if pick is None or add < pick[0]:
                        pick = (add, a, b, e)
            if pick is None:
                break
            add, a, b, e = pick
            chosen.append(b)
            inside.add(b)
            used.append([a, b, e])
            score += add
            if best is not None and score >= best["score"]:
                break
        if len(chosen) == n and (best is None or score < best["score"]):
            fid = float(np.prod([1 - ro[q] for q in chosen]) * np.prod([1 - u[2] for u in used]))
            best = {"physical_qubits": chosen, "couplers": [[a, b] for a, b, _ in used], "score": round(score, 6),
                    "estimated_fidelity": round(fid, 6)}
    return best


def summary(snap: dict) -> dict:
    """Medians a person can read: how good the chip is right now."""
    def med(xs):
        xs = [x for x in xs if x is not None]
        return round(float(np.median(xs)), 6) if xs else None
    q = snap["qubits"].values()
    ro, adj = _usable(snap)
    return {"backend": snap["backend"], "num_qubits": snap["num_qubits"], "two_qubit_gate": snap["two_qubit_gate"],
            "calibrated_at": snap.get("calibrated_at"), "read_at": snap.get("taken_at"),
            "calibration_sha256": calibration_sha256(snap),
            "usable_qubits": len(ro), "couplers": len(snap.get("edges", [])),
            "median_readout_error": med([d.get("readout_error") for d in q]),
            "median_two_qubit_error": med([e[2] for e in snap.get("edges", [])]),
            "median_t1_us": med([d.get("t1_us") for d in q]), "median_t2_us": med([d.get("t2_us") for d in q]),
            "best_qubits_by_readout": sorted(ro, key=ro.get)[:10]}


def readout_for(snap: dict, physical: list[int]) -> list[dict]:
    """Readout confusion numbers for the physical qubit each logical qubit was measured on."""
    out = []
    for p in physical:
        d = snap["qubits"].get(str(p), {})
        out.append({"physical": int(p), "p01": d.get("p01"), "p10": d.get("p10")})
    return out


# ----------------------------------------------------------------- readout mitigation

def mitigate_readout(counts: dict[int, int], readout: list[dict], min_prob: float | None = None) -> dict | None:
    """Correct counts {k: c} (bit i of k = logical qubit i) with per-qubit confusion matrices.

    For each qubit, A = [[1-p01, p10], [p01, 1-p10]] maps true -> measured probabilities. Applying
    inv(A) on every axis undoes it (exact for independent readout errors). The result can have small
    negative entries from shot noise; it is clipped to zero and renormalised.
    Returns {"probabilities": {k: p}, "method": ...} or None when it cannot be done.
    """
    n = len(readout)
    shots = sum(counts.values())
    if not n or n > MAX_MITIGATION_QUBITS or not shots:
        return None
    if any(r.get("p01") is None or r.get("p10") is None for r in readout):
        return None
    v = np.zeros(2 ** n)
    for k, c in counts.items():
        v[int(k)] += c
    v = (v / shots).reshape([2] * n)
    for q, r in enumerate(readout):
        p01, p10 = float(r["p01"]), float(r["p10"])
        A = np.array([[1 - p01, p10], [p01, 1 - p10]])
        if abs(np.linalg.det(A)) < 1e-6:
            return None
        ax = n - 1 - q
        v = np.moveaxis(np.tensordot(np.linalg.inv(A), v, axes=([1], [ax])), 0, ax)
    p = np.clip(v.reshape(-1), 0, None)
    tot = p.sum()
    if tot <= 0:
        return None
    p /= tot
    floor = (0.5 / shots) if min_prob is None else min_prob
    probs = {int(k): float(p[k]) for k in np.nonzero(p >= floor)[0]}
    s = sum(probs.values()) or 1.0
    return {"probabilities": {k: round(x / s, 8) for k, x in probs.items()},
            "method": "tensored readout inverse from the job's calibration, clipped and renormalised"}


def as_counts(probs: dict[int, float], shots: int) -> dict[int, int]:
    """Mitigated probabilities as whole counts, for code that expects counts."""
    out = {k: int(round(p * shots)) for k, p in probs.items()}
    return {k: c for k, c in out.items() if c > 0} or {max(probs, key=probs.get): shots}


# ----------------------------------------------------------------- circuit figures

def isa_figures(isa: Any, snap: dict | None) -> dict:
    """Depth, two-qubit gate count and an error-model fidelity estimate for a transpiled circuit."""
    out: dict[str, Any] = {}
    try:
        out["depth"] = int(isa.depth())
        ops = {str(k): int(v) for k, v in dict(isa.count_ops()).items()}
        out["ops"] = ops
        gate2 = (snap or {}).get("two_qubit_gate")
        out["two_qubit_gates"] = sum(v for k, v in ops.items() if k in TWO_QUBIT_GATES)
        if snap and gate2:
            err = {(a, b): e for a, b, e in snap.get("edges", [])}
            f = 1.0
            for inst in isa.data:
                op = getattr(inst, "operation", None)
                if getattr(op, "name", "") != gate2:
                    continue
                qs = sorted(isa.find_bit(q).index for q in inst.qubits)
                f *= 1 - err.get(tuple(qs), 0.01)
            out["estimated_gate_fidelity"] = round(f, 6)
    except Exception:  # noqa: BLE001  (figures are informational)
        pass
    return out


def measured_physical(isa: Any, fallback: list[int] | None) -> list[int] | None:
    """Which physical qubit each logical qubit ended on (routing can move them)."""
    try:
        lay = isa.layout.final_index_layout()
        return [int(x) for x in lay]
    except Exception:  # noqa: BLE001
        return fallback


# ----------------------------------------------------------------- Open Plan minute guard

class OpenPlanMeter:
    """Local meter of IBM QPU seconds over a rolling window.

    est_s is reserved when a job is submitted and replaced by IBM's reported quantum seconds when
    the job finishes; failed or canceled jobs that report no usage free their reservation.
    """

    def __init__(self, db: sqlite3.Connection, lock: threading.Lock | None = None, budget_s: float = 600.0,
                 window_days: float = 28.0, reserve_s: float = 30.0):
        self._db, self._lock = db, lock or threading.Lock()
        self.budget_s, self.window_days, self.reserve_s = float(budget_s), float(window_days), float(reserve_s)
        with self._lock:
            self._db.executescript(USAGE_SCHEMA)
            self._db.commit()

    @staticmethod
    def estimate_seconds(shots: int, two_qubit_gates: int = 0) -> float:
        """Rough QPU time for one Sampler job: fixed overhead plus repetition time per shot.

        Deliberately on the high side so the guard stops early rather than late; the reservation is replaced by
        IBM's billed quantum seconds once the job finishes.
        """
        return round(2.0 + shots * 0.0005 + shots * two_qubit_gates * 2e-6, 3)

    def _since(self) -> float:
        return time.time() - self.window_days * 86400

    def used_s(self) -> float:
        r = self._db.execute("SELECT COALESCE(SUM(COALESCE(actual_s, est_s)),0) AS s FROM ibm_usage WHERE ts>=? AND "
                             "status NOT IN ('released')", (self._since(),)).fetchone()
        return float(r[0] or 0)

    def ibm_reported(self) -> dict | None:
        r = self._db.execute("SELECT remaining_s, limit_s, consumed_s, ts FROM ibm_usage_sync WHERE id=1").fetchone()
        if not r:
            return None
        return {"remaining_s": r[0], "limit_s": r[1], "consumed_s": r[2], "synced_unix": r[3]}

    def remaining_s(self) -> float:
        local = self.budget_s - self.used_s()
        rep = self.ibm_reported()
        if rep and rep["remaining_s"] is not None:
            since = self._db.execute("SELECT COALESCE(SUM(COALESCE(actual_s, est_s)),0) FROM ibm_usage WHERE ts>? AND "
                                     "status NOT IN ('released')", (rep["synced_unix"],)).fetchone()[0] or 0
            local = min(local, float(rep["remaining_s"]) - float(since))
        return round(local, 3)

    def check(self, shots: int, two_qubit_gates: int = 0) -> tuple[bool, str, float]:
        est = self.estimate_seconds(shots, two_qubit_gates)
        left = self.remaining_s() - self.reserve_s
        if est > left:
            return False, (f"IBM Open Plan guard: this job needs about {est}s of QPU time and only {max(0, round(left, 1))}s "
                           f"is left in the {int(self.window_days)}-day window (keeping {self.reserve_s}s in reserve)"), est
        return True, f"about {est}s of {round(left, 1)}s QPU time left", est

    def reserve(self, provider_job_id: str, backend: str, est_s: float) -> None:
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO ibm_usage VALUES (?,?,?,?,?,?)",
                             (provider_job_id, backend, float(est_s), None, "reserved", time.time()))
            self._db.commit()

    def settle(self, provider_job_id: str, actual_s: float | None, status: str) -> None:
        with self._lock:
            if actual_s is None and status in ("failed", "canceled"):
                self._db.execute("UPDATE ibm_usage SET status='released' WHERE provider_job_id=?", (provider_job_id,))
            else:
                self._db.execute("UPDATE ibm_usage SET actual_s=COALESCE(?, actual_s), status=? WHERE provider_job_id=?",
                                 (actual_s, status, provider_job_id))
            self._db.commit()

    def sync(self, remaining_s: float | None, limit_s: float | None = None, consumed_s: float | None = None) -> None:
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO ibm_usage_sync VALUES (1,?,?,?,?)",
                             (remaining_s, limit_s, consumed_s, time.time()))
            self._db.commit()

    def view(self) -> dict:
        jobs = self._db.execute("SELECT COUNT(*) FROM ibm_usage WHERE ts>=? AND status NOT IN ('released')",
                                (self._since(),)).fetchone()[0]
        return {"budget_s": self.budget_s, "window_days": self.window_days, "reserve_s": self.reserve_s,
                "used_s": round(self.used_s(), 3), "remaining_s": self.remaining_s(), "jobs_in_window": int(jobs),
                "ibm_reported": self.ibm_reported()}


def parse_service_usage(u: Any) -> dict:
    """QiskitRuntimeService.usage() -> seconds (field names differ by plan and SDK version)."""
    if not isinstance(u, dict):
        return {}
    def pick(*keys):
        for k in keys:
            if u.get(k) is not None:
                return _num(u[k])
        return None
    return {"remaining_s": pick("usage_remaining_seconds", "remaining_seconds"),
            "limit_s": pick("usage_limit_seconds", "limit_seconds"),
            "consumed_s": pick("usage_consumed_seconds", "consumed_seconds")}


def job_quantum_seconds(job: Any) -> float | None:
    """Quantum seconds IBM billed for a finished job, if the SDK exposes it."""
    try:
        u = job.usage()
        if _num(u) is not None:
            return _num(u)
    except Exception:  # noqa: BLE001
        pass
    try:
        m = job.metrics() or {}
        return _num((m.get("usage") or {}).get("quantum_seconds") or (m.get("usage") or {}).get("seconds"))
    except Exception:  # noqa: BLE001
        return None


def suggested_layouts(snap: dict, sizes: Iterable[int] = (2, 3, 4, 6, 8, 12)) -> list[dict]:
    out = []
    for n in sizes:
        lay = best_layout(snap, n)
        if lay:
            out.append({"qubits": n, **lay})
    return out
