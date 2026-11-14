# Copyright (c) 2026 Privi World Corp.
"""Bounded single-node quantum circuit job API. Simulator only; no physical QPU access."""
from __future__ import annotations
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from starlette.responses import JSONResponse
from starlette.routing import Route
from . import circuits
from .hardware import simulate

MAX_QUBITS = 12
MAX_SHOTS = 4096
MAX_GATES = 500
MAX_PENDING = 32
MAX_BODY = 24_000

def utcnow():
    return datetime.now(timezone.utc).isoformat()

class QuantumCloud:
    def __init__(self, db_path: str, workers: int = 2):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self.lock = threading.Lock()
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="privi-qcloud")
        with self.conn() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS quantum_cloud_jobs (
                id TEXT PRIMARY KEY, owner_hash TEXT NOT NULL, state TEXT NOT NULL,
                qubits INTEGER NOT NULL, shots INTEGER NOT NULL, circuit_hash TEXT NOT NULL,
                result TEXT, error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )""")
            # Unfinished jobs cannot silently be reported as running after restart.
            db.execute("UPDATE quantum_cloud_jobs SET state='failed', error='worker restarted before completion', updated_at=? WHERE state IN ('queued','running')", (utcnow(),))

    def conn(self):
        db = sqlite3.connect(self.db_path, timeout=5)
        db.row_factory = sqlite3.Row
        return db

    def submit(self, owner_hash: str, source: str, shots: int) -> dict:
        if not isinstance(source, str) or len(source) > MAX_BODY or not source.strip():
            raise ValueError("qasm must be a nonempty string of at most 24 KB")
        if type(shots) is not int or not 1 <= shots <= MAX_SHOTS:
            raise ValueError("shots must be an integer between 1 and 4096")
        parsed = circuits.parse(source)
        n, gates = parsed["qubits"], parsed["gates"]
        if not 1 <= n <= MAX_QUBITS or len(gates) > MAX_GATES:
            raise ValueError("simulator limit: 1-12 qubits and at most 500 basis gates")
        for gate in gates:
            if any(isinstance(v, int) and not 0 <= v < n for v in gate[1:3] if not isinstance(v, bool)) and gate[0] in ("h", "cx"):
                raise ValueError("invalid qubit index")
        jid = "qj_" + secrets.token_hex(16)
        now = utcnow()
        with self.lock:
            with self.conn() as db:
                pending = db.execute("SELECT COUNT(*) FROM quantum_cloud_jobs WHERE state IN ('queued','running')").fetchone()[0]
                if pending >= MAX_PENDING:
                    raise RuntimeError("quantum job queue is full")
                db.execute("INSERT INTO quantum_cloud_jobs (id,owner_hash,state,qubits,shots,circuit_hash,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                           (jid, owner_hash, "queued", n, shots, hashlib.sha256(source.encode()).hexdigest(), now, now))
            self.pool.submit(self._execute, jid, n, gates, shots)
        return {"job_id": jid, "status": "queued", "backend": "local_statevector_simulator", "qubits": n, "shots": shots, "physical_qpu": False}

    def _execute(self, jid, n, gates, shots):
        try:
            with self.conn() as db:
                db.execute("UPDATE quantum_cloud_jobs SET state='running',updated_at=? WHERE id=?", (utcnow(), jid))
            import numpy as np
            probabilities = simulate(gates, n)
            samples = np.random.default_rng().multinomial(shots, probabilities)
            counts = {format(k, "0%db" % n): int(c) for k,c in enumerate(samples) if c}
            result = json.dumps({"counts": counts, "shots": shots, "qubits": n, "backend": "local_statevector_simulator", "physical_qpu": False})
            with self.conn() as db:
                db.execute("UPDATE quantum_cloud_jobs SET state='completed',result=?,updated_at=? WHERE id=?", (result, utcnow(), jid))
        except Exception:
            with self.conn() as db:
                db.execute("UPDATE quantum_cloud_jobs SET state='failed',error='simulation failed',updated_at=? WHERE id=?", (utcnow(), jid))

    def get(self, jid: str, owner_hash: str):
        with self.conn() as db:
            row = db.execute("SELECT * FROM quantum_cloud_jobs WHERE id=? AND owner_hash=?", (jid, owner_hash)).fetchone()
        if not row:
            return None
        result = {"job_id": row["id"], "status": row["state"], "backend": "local_statevector_simulator",
                  "physical_qpu": False, "created_at": row["created_at"], "updated_at": row["updated_at"]}
        if row["state"] == "completed":
            result["result"] = json.loads(row["result"])
        if row["state"] == "failed":
            result["error"] = row["error"]
        return result

def auth(request):
    configured = [k.strip() for k in os.environ.get("QUANTUM_CLOUD_API_KEYS", "").split(",") if k.strip()]
    if not configured:
        return None, 503
    header = request.headers.get("authorization", "")
    candidate = header[7:] if header.startswith("Bearer ") else ""
    if not candidate or not any(hmac.compare_digest(candidate, key) for key in configured):
        return None, 401
    return hashlib.sha256(candidate.encode()).hexdigest(), 200

def routes():
    cloud = QuantumCloud(os.getenv("QUANTUM_CLOUD_DB_PATH", "/data/quantum-cloud.sqlite3"))
    async def info(request):
        return JSONResponse({"service": "Privi Quantum Cloud", "mode": "simulator_only", "physical_qpu": False,
                             "max_qubits": MAX_QUBITS, "max_shots": MAX_SHOTS, "jobs": "/v1/quantum/cloud/jobs",
                             "authentication": "Bearer API key; disabled without QUANTUM_CLOUD_API_KEYS",
                             "shared_queue": False, "durability": "single_instance_sqlite_volume"})
    async def submit(request):
        owner, status = auth(request)
        if not owner:
            return JSONResponse({"error": "not configured" if status == 503 else "unauthorized"}, status_code=status)
        if int(request.headers.get("content-length", "0") or "0") > MAX_BODY:
            return JSONResponse({"error":"payload too large"},status_code=413)
        raw = await request.body()
        if len(raw) > MAX_BODY:
            return JSONResponse({"error": "payload too large"}, status_code=413)
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("JSON object required")
            job = cloud.submit(owner, data.get("qasm"), data.get("shots", 1024))
            return JSONResponse(job, status_code=202, headers={"cache-control": "no-store"})
        except (ValueError, TypeError, circuits.CircuitError) as exc:
            return JSONResponse({"error": str(exc)[:180]}, status_code=400)
        except RuntimeError:
            return JSONResponse({"error":"queue full"}, status_code=429)
    async def result(request):
        owner, status = auth(request)
        if not owner:
            return JSONResponse({"error": "not configured" if status == 503 else "unauthorized"}, status_code=status)
        item = cloud.get(request.path_params["job_id"], owner)
        return JSONResponse(item if item is not None else {"error":"not found"},
                            status_code=200 if item else 404, headers={"cache-control":"no-store"})
    return [Route("/v1/quantum/cloud", info, methods=["GET"]),
            Route("/v1/quantum/cloud/jobs", submit, methods=["POST"]),
            Route("/v1/quantum/cloud/jobs/{job_id}", result, methods=["GET"])]
