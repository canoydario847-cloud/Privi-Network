# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Quantum - https://priviflow.us - dariocanoy@priviflow.us
"""Real quantum hardware routing.

Privi Quantum trains a CVaR-QAOA circuit classically (exact simulator), then runs the
trained circuit on a quantum backend and reads the answer from its measurements. This
module connects the backends and picks one per job:

  local          exact statevector sampler on this server (always on, free)
  ionq:<target>  IonQ Quantum Cloud REST API v0.4 (IONQ_API_KEY). "simulator" is free;
                 "qpu.forte-1" etc. are real trapped-ion QPUs and cost money.
  ibm:<backend>  IBM Quantum via qiskit-ibm-runtime (IBM_QUANTUM_TOKEN, optional extra).
  braket:<name>  Amazon Braket via boto3 (AWS credentials + BRAKET_S3_BUCKET, optional extra).

Routing policies: "cheapest" (lowest estimated price, then fastest), "fastest" (lowest
measured turnaround), "hardware" (real QPUs only, cheapest first).

Money guard: a backend that costs money (or whose price is unknown) is only used when
HARDWARE_DAILY_BUDGET_USD is set, its price is known (HARDWARE_PRICES), and the estimate
fits what is left of today's budget. Callers can also cap a single job (max_cost_usd).

Bit order everywhere: outcome integer k has bit i = measured value of qubit i
(qubit 0 is the least significant bit), matching qaoa.bits_of.
"""
from __future__ import annotations

import json
import math
import os
import re
import secrets
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

import numpy as np

from .attest import now_iso

POLICIES = ("cheapest", "fastest", "hardware")
TERMINAL = ("done", "failed", "canceled")

SCHEMA = """
CREATE TABLE IF NOT EXISTS hw_jobs (
    job_id TEXT PRIMARY KEY, backend_id TEXT NOT NULL, provider_job_id TEXT NOT NULL DEFAULT '',
    problem TEXT NOT NULL, data TEXT NOT NULL, qasm TEXT NOT NULL, qubits INTEGER NOT NULL, shots INTEGER NOT NULL,
    layers INTEGER NOT NULL, training TEXT NOT NULL, status TEXT NOT NULL, error TEXT NOT NULL DEFAULT '',
    est_cost_usd REAL, submitted_at TEXT NOT NULL, submitted_unix REAL NOT NULL, finished_at TEXT,
    turnaround_s REAL, counts TEXT, result TEXT, attestation_id TEXT, receipt_id TEXT, owner TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS hw_stats (
    backend_id TEXT PRIMARY KEY, runs INTEGER NOT NULL DEFAULT 0, failures INTEGER NOT NULL DEFAULT 0,
    ewma_turnaround_s REAL);
CREATE TABLE IF NOT EXISTS hw_spend (day TEXT PRIMARY KEY, usd REAL NOT NULL DEFAULT 0);
"""


class HardwareError(ValueError):
    pass


# ----------------------------------------------------------------- circuits

_GATE = re.compile(r"^(h|rz|rx|cx)(?:\(([^)]*)\))?\s+q\[(\d+)\](?:\s*,\s*q\[(\d+)\])?;$")


def parse_qasm(qasm: str) -> tuple[int, list[tuple]]:
    """Read the OpenQASM 2.0 that qaoa.to_qasm writes: h, rz, rx, cx, measure."""
    n, gates = 0, []
    for raw in qasm.splitlines():
        line = raw.strip()
        if not line or line.startswith(("OPENQASM", "include", "creg", "measure", "//")):
            continue
        m = re.match(r"qreg q\[(\d+)\];", line)
        if m:
            n = int(m.group(1))
            continue
        m = _GATE.match(line)
        if not m:
            raise HardwareError(f"unsupported QASM line: {line[:80]}")
        g, a, q1, q2 = m.groups()
        if g == "cx":
            gates.append(("cx", int(q1), int(q2)))
        elif g == "h":
            gates.append(("h", int(q1)))
        else:
            gates.append((g, int(q1), float(a)))
    if not n:
        raise HardwareError("QASM has no qreg")
    return n, gates


def to_ionq(gates: list[tuple]) -> list[dict]:
    out = []
    for g in gates:
        if g[0] == "h":
            out.append({"gate": "h", "target": g[1]})
        elif g[0] == "cx":
            out.append({"gate": "cnot", "control": g[1], "target": g[2]})
        else:  # rz / rx, radians
            out.append({"gate": g[0], "target": g[1], "rotation": g[2]})
    return out


def to_qasm3(gates: list[tuple], n: int) -> str:
    L = ["OPENQASM 3.0;", 'include "stdgates.inc";', f"qubit[{n}] q;", f"bit[{n}] c;"]
    for g in gates:
        if g[0] == "h":
            L.append(f"h q[{g[1]}];")
        elif g[0] == "cx":
            L.append(f"cnot q[{g[1]}], q[{g[2]}];")
        else:
            L.append(f"{g[0]}({g[2]!r}) q[{g[1]}];")
    L += [f"c[{i}] = measure q[{i}];" for i in range(n)]
    return "\n".join(L) + "\n"


def simulate(gates: list[tuple], n: int) -> np.ndarray:
    """Gate-by-gate statevector simulation; returns outcome probabilities indexed by k (bit i = qubit i)."""
    t = np.zeros(2 ** n, complex)
    t[0] = 1
    t = t.reshape([2] * n)
    ax = lambda q: n - 1 - q  # noqa: E731  (axis 0 = most significant bit)
    H = np.array([[1, 1], [1, -1]]) / math.sqrt(2)

    def one(U, q):
        nonlocal t
        t = np.moveaxis(np.tensordot(U, t, axes=([1], [ax(q)])), 0, ax(q))
    for g in gates:
        if g[0] == "h":
            one(H, g[1])
        elif g[0] == "rz":
            th = g[2]
            one(np.diag([np.exp(-1j * th / 2), np.exp(1j * th / 2)]), g[1])
        elif g[0] == "rx":
            th = g[2]
            c, s = math.cos(th / 2), -1j * math.sin(th / 2)
            one(np.array([[c, s], [s, c]]), g[1])
        else:
            ctl, tgt = g[1], g[2]
            idx = [slice(None)] * n
            idx[ax(ctl)] = 1
            rem = [k for k in range(n) if k != ax(ctl)]
            t[tuple(idx)] = np.flip(t[tuple(idx)], axis=rem.index(ax(tgt))).copy()
    p = np.abs(t.reshape(-1)) ** 2
    return p / p.sum()


def counts_from_bitstrings(counts: dict[str, int], qubit0_first: bool) -> dict[int, int]:
    """Provider bitstrings -> {k: count}. IBM prints c[n-1]..c[0] (qubit0_first=False);
    Braket prints qubit 0 first (qubit0_first=True)."""
    out: dict[int, int] = {}
    for s, c in counts.items():
        s = s.replace(" ", "")
        k = sum(int(b) << i for i, b in enumerate(s)) if qubit0_first else int(s, 2)
        out[k] = out.get(k, 0) + int(c)
    return out


def counts_from_probs(probs: dict[str, float], shots: int) -> dict[int, int]:
    raw = {int(k): float(v) for k, v in probs.items() if float(v) > 0}
    tot = sum(raw.values()) or 1.0
    return {k: max(1, round(v / tot * shots)) for k, v in raw.items()}


# ----------------------------------------------------------------- backends

class Backend:
    id = "base"
    provider = ""
    name = ""
    kind = "simulator"   # simulator | qpu
    library = None       # python module this backend needs, if any

    def __init__(self, price: dict | None = None):
        self.price = price  # {"per_task": x, "per_shot": y} or None (unknown)

    def configured(self) -> tuple[bool, str]:
        return True, "ready"

    def estimate_usd(self, shots: int) -> float | None:
        if self.kind == "simulator" and self.price is None:
            return 0.0
        if self.price is None:
            return None
        return round(float(self.price.get("per_task", 0)) + float(self.price.get("per_shot", 0)) * shots, 4)

    def submit(self, qasm: str, n: int, gates: list[tuple], shots: int, name: str) -> str:
        raise NotImplementedError

    def fetch(self, provider_job_id: str, n: int, shots: int) -> dict:
        """-> {"status": queued|running|done|failed|canceled, "counts": {k: c} when done, "error": str}"""
        raise NotImplementedError

    def info(self) -> dict:
        ok, why = self.configured()
        return {"id": self.id, "provider": self.provider, "name": self.name, "kind": self.kind,
                "available": ok, "status": why, "estimated_usd_per_1000_shots": self.estimate_usd(1000)}


class LocalBackend(Backend):
    id, provider, name, kind = "local", "Privi Quantum", "Exact statevector sampler (this server)", "simulator"

    def __init__(self):
        super().__init__(None)
        self._results: dict[str, dict] = {}

    def submit(self, qasm, n, gates, shots, name):
        p = simulate(gates, n)
        rng = np.random.default_rng()
        ks, cs = np.unique(rng.choice(len(p), size=shots, p=p), return_counts=True)
        jid = "local_" + secrets.token_hex(6)
        self._results[jid] = {k: c for k, c in zip(ks.tolist(), cs.tolist())}
        return jid

    def fetch(self, pid, n, shots):
        c = self._results.pop(pid, None)
        if c is None:
            return {"status": "failed", "error": "local result expired (server restarted)"}
        return {"status": "done", "counts": c}


class IonQBackend(Backend):
    provider = "IonQ"
    base = "https://api.ionq.co/v0.4"
    STATUS = {"submitted": "queued", "ready": "queued", "started": "running", "completed": "done",
              "failed": "failed", "canceled": "canceled"}

    def __init__(self, api_key: str, target: str, price: dict | None, opener=None):
        super().__init__(price)
        self.key, self.target = api_key, target
        self.id = f"ionq:{target}"
        self.kind = "simulator" if target == "simulator" else "qpu"
        self.name = f"IonQ {'cloud simulator' if self.kind == 'simulator' else target + ' (trapped-ion QPU)'}"
        self._open = opener or urllib.request.urlopen

    def configured(self):
        return (True, "ready") if self.key else (False, "set IONQ_API_KEY")

    def _req(self, method: str, path: str, body: dict | None = None) -> Any:
        req = urllib.request.Request(self.base + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": f"apiKey {self.key}", "Content-Type": "application/json"})
        try:
            with self._open(req, timeout=30) as r:
                return json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            raise HardwareError(f"IonQ API {e.code}: {e.read().decode()[:300]}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            raise HardwareError(f"IonQ API unreachable: {e}") from e

    def submit(self, qasm, n, gates, shots, name):
        r = self._req("POST", "/jobs", {"type": "ionq.circuit.v1", "name": re.sub(r"[^A-Za-z0-9 _-]", "-", name)[:60],
                                        "backend": self.target, "shots": shots,
                                        "input": {"qubits": n, "gateset": "qis", "circuit": to_ionq(gates)}})
        if not r.get("id"):
            raise HardwareError(f"IonQ did not return a job id: {str(r)[:200]}")
        return r["id"]

    def fetch(self, pid, n, shots):
        j = self._req("GET", f"/jobs/{pid}")
        st = self.STATUS.get(str(j.get("status")), "running")
        if st != "done":
            fail = j.get("failure") or {}
            return {"status": st, "error": str(fail.get("error") or fail.get("message") or "")[:300]}
        probs = self._req("GET", f"/jobs/{pid}/results/probabilities")
        return {"status": "done", "counts": counts_from_probs(probs, shots)}


class IBMBackend(Backend):
    provider, kind, library = "IBM Quantum", "qpu", "qiskit_ibm_runtime"

    def __init__(self, token: str, instance: str, backend_name: str, price: dict | None):
        super().__init__(price)
        self.token, self.instance, self.backend_name = token, instance, backend_name
        self.id = f"ibm:{backend_name}"
        self.name = f"IBM Quantum {backend_name} (superconducting QPU)"

    def configured(self):
        if not self.token:
            return False, "set IBM_QUANTUM_TOKEN"
        try:
            __import__("qiskit_ibm_runtime")
        except ImportError:
            return False, "install the hardware extra (pip install privi-quantum-mcp[hardware])"
        return True, "ready"

    def _service(self):
        from qiskit_ibm_runtime import QiskitRuntimeService
        kw = {"channel": os.getenv("IBM_QUANTUM_CHANNEL", "ibm_quantum_platform"), "token": self.token}
        if self.instance:
            kw["instance"] = self.instance
        return QiskitRuntimeService(**kw)

    def submit(self, qasm, n, gates, shots, name):
        from qiskit import QuantumCircuit
        from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
        from qiskit_ibm_runtime import SamplerV2
        svc = self._service()
        backend = svc.backend(self.backend_name)
        isa = generate_preset_pass_manager(backend=backend, optimization_level=1).run(QuantumCircuit.from_qasm_str(qasm))
        return SamplerV2(mode=backend).run([isa], shots=shots).job_id()

    def fetch(self, pid, n, shots):
        job = self._service().job(pid)
        st = str(job.status()).split(".")[-1].upper()
        if st in ("QUEUED", "INITIALIZING", "VALIDATING"):
            return {"status": "queued"}
        if st == "RUNNING":
            return {"status": "running"}
        if st in ("ERROR", "CANCELLED"):
            return {"status": "failed" if st == "ERROR" else "canceled", "error": str(job.error_message() or "")[:300]}
        data = job.result()[0].data
        reg = next(iter(data.__dict__.values())) if not hasattr(data, "c") else data.c
        return {"status": "done", "counts": counts_from_bitstrings(reg.get_counts(), qubit0_first=False)}


class BraketBackend(Backend):
    provider, library = "Amazon Braket", "boto3"

    def __init__(self, name: str, device_arn: str, bucket: str, region: str, price: dict | None):
        super().__init__(price)
        self.device_arn, self.bucket, self.region = device_arn, bucket, region
        self.id = f"braket:{name}"
        self.kind = "simulator" if ":device/quantum-simulator/" in device_arn else "qpu"
        self.name = f"Amazon Braket {name}"

    def configured(self):
        if not self.bucket:
            return False, "set BRAKET_S3_BUCKET and AWS credentials"
        try:
            __import__("boto3")
        except ImportError:
            return False, "install the hardware extra (pip install privi-quantum-mcp[hardware])"
        return True, "ready"

    def _client(self, svc="braket"):
        import boto3
        return boto3.client(svc, region_name=self.region)

    def submit(self, qasm, n, gates, shots, name):
        action = {"braketSchemaHeader": {"name": "braket.ir.openqasm.program", "version": "1"},
                  "source": to_qasm3(gates, n)}
        r = self._client().create_quantum_task(action=json.dumps(action), deviceArn=self.device_arn, shots=shots,
                                               outputS3Bucket=self.bucket, outputS3KeyPrefix="privi-quantum")
        return r["quantumTaskArn"]

    def fetch(self, pid, n, shots):
        t = self._client().get_quantum_task(quantumTaskArn=pid)
        st = t["status"]
        if st in ("CREATED", "QUEUED"):
            return {"status": "queued"}
        if st == "RUNNING":
            return {"status": "running"}
        if st in ("FAILED", "CANCELLING", "CANCELLED"):
            return {"status": "failed" if st == "FAILED" else "canceled", "error": str(t.get("failureReason", ""))[:300]}
        obj = self._client("s3").get_object(Bucket=t["outputS3Bucket"], Key=t["outputS3Directory"].rstrip("/") + "/results.json")
        res = json.loads(obj["Body"].read())
        if res.get("measurementCounts"):
            counts = res["measurementCounts"]
        else:
            counts = {}
            for row in res.get("measurements", []):
                s = "".join(str(b) for b in row)
                counts[s] = counts.get(s, 0) + 1
        measured = res.get("measuredQubits") or list(range(n))
        fixed = {}
        for s, c in counts.items():  # reorder so position i is qubit i
            bits = ["0"] * n
            for pos, q in enumerate(measured):
                if q < n and pos < len(s):
                    bits[q] = s[pos]
            fixed["".join(bits)] = fixed.get("".join(bits), 0) + c
        return {"status": "done", "counts": counts_from_bitstrings(fixed, qubit0_first=True)}


def _prices(env: str) -> dict[str, dict]:
    """HARDWARE_PRICES: JSON {"ionq:qpu.forte-1": {"per_task": 0.3, "per_shot": 0.08}, ...} (USD)."""
    if not env.strip():
        return {}
    try:
        p = json.loads(env)
        return {k: {"per_task": float(v.get("per_task", 0)), "per_shot": float(v.get("per_shot", 0))} for k, v in p.items()}
    except (ValueError, AttributeError, TypeError):
        raise HardwareError("HARDWARE_PRICES must be JSON like {\"ionq:qpu.forte-1\": {\"per_task\": 0.3, \"per_shot\": 0.08}}")


def backends_from_env(env: dict | None = None) -> list[Backend]:
    e = env if env is not None else os.environ
    prices = _prices(e.get("HARDWARE_PRICES", ""))
    out: list[Backend] = [LocalBackend()]
    for tgt in [t.strip() for t in e.get("IONQ_TARGETS", "simulator").split(",") if t.strip()]:
        out.append(IonQBackend(e.get("IONQ_API_KEY", ""), tgt, prices.get(f"ionq:{tgt}")))
    for b in [x.strip() for x in e.get("IBM_QUANTUM_BACKENDS", "").split(",") if x.strip()]:
        out.append(IBMBackend(e.get("IBM_QUANTUM_TOKEN", ""), e.get("IBM_QUANTUM_INSTANCE", ""), b, prices.get(f"ibm:{b}")))
    for item in [x.strip() for x in e.get("BRAKET_DEVICES", "").split(",") if x.strip()]:
        name, _, arn = item.partition("=")
        if arn:
            out.append(BraketBackend(name, arn, e.get("BRAKET_S3_BUCKET", ""), e.get("AWS_REGION", "us-east-1"),
                                     prices.get(f"braket:{name}")))
    return out


# ----------------------------------------------------------------- router

class HardwareRouter:
    def __init__(self, db_path: str, backends: list[Backend] | None = None, daily_budget_usd: float = 0.0):
        self._lock = threading.Lock()
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.commit()
        self.backends = {b.id: b for b in (backends if backends is not None else backends_from_env())}
        self.daily_budget = float(daily_budget_usd)

    # -- money
    def _today(self) -> str:
        return datetime.now(timezone.utc).date().isoformat()

    def spent_today(self) -> float:
        r = self._db.execute("SELECT usd FROM hw_spend WHERE day=?", (self._today(),)).fetchone()
        return float(r["usd"]) if r else 0.0

    def _add_spend(self, usd: float) -> None:
        with self._lock:
            self._db.execute("INSERT INTO hw_spend VALUES (?,?) ON CONFLICT(day) DO UPDATE SET usd=usd+?",
                             (self._today(), usd, usd))
            self._db.commit()

    def affordable(self, b: Backend, shots: int, max_cost: float | None) -> tuple[bool, str, float | None]:
        est = b.estimate_usd(shots)
        if est == 0:
            return True, "free", 0.0
        if est is None:
            return False, f"price for {b.id} unknown: set it in HARDWARE_PRICES", None
        if self.daily_budget <= 0:
            return False, "paid quantum hardware is off: set HARDWARE_DAILY_BUDGET_USD", est
        if est > self.daily_budget - self.spent_today():
            return False, f"estimated ${est} exceeds today's remaining hardware budget", est
        if max_cost is not None and est > max_cost:
            return False, f"estimated ${est} exceeds your max_cost_usd ${max_cost}", est
        return True, "within budget", est

    # -- stats
    def stats(self, bid: str) -> dict:
        r = self._db.execute("SELECT * FROM hw_stats WHERE backend_id=?", (bid,)).fetchone()
        return dict(r) if r else {"backend_id": bid, "runs": 0, "failures": 0, "ewma_turnaround_s": None}

    def _observe(self, bid: str, turnaround: float | None, ok: bool) -> None:
        s = self.stats(bid)
        ew = s["ewma_turnaround_s"]
        if ok and turnaround is not None:
            ew = turnaround if ew is None else 0.7 * ew + 0.3 * turnaround
        with self._lock:
            self._db.execute("INSERT INTO hw_stats VALUES (?,?,?,?) ON CONFLICT(backend_id) DO UPDATE SET "
                             "runs=excluded.runs, failures=excluded.failures, ewma_turnaround_s=excluded.ewma_turnaround_s",
                             (bid, s["runs"] + (1 if ok else 0), s["failures"] + (0 if ok else 1), ew))
            self._db.commit()

    def directory(self, shots: int = 1000) -> list[dict]:
        out = []
        for b in self.backends.values():
            ok, why, est = self.affordable(b, shots, None)
            s = self.stats(b.id)
            out.append({**b.info(), "usable_now": b.configured()[0] and ok,
                        "money_guard": why, "measured_turnaround_s": s["ewma_turnaround_s"],
                        "completed_runs": s["runs"], "failures": s["failures"]})
        return out

    def choose(self, backend: str, policy: str, shots: int, max_cost: float | None) -> tuple[Backend, float, list[dict]]:
        if policy not in POLICIES:
            raise HardwareError(f"policy must be one of {', '.join(POLICIES)}")
        considered = []
        if backend and backend != "auto":
            b = self.backends.get(backend)
            if not b:
                raise HardwareError(f"unknown backend {backend}; see quantum_backends")
            ok, why = b.configured()
            if not ok:
                raise HardwareError(f"{backend} is not available: {why}")
            aff, why, est = self.affordable(b, shots, max_cost)
            if not aff:
                raise HardwareError(why)
            return b, est or 0.0, [{"backend": b.id, "chosen": True, "why": "requested"}]
        cands = []
        for b in self.backends.values():
            ok, why = b.configured()
            aff, mwhy, est = self.affordable(b, shots, max_cost) if ok else (False, why, None)
            considered.append({"backend": b.id, "kind": b.kind, "usable": ok and aff, "why": mwhy if ok else why,
                               "estimated_usd": est})
            if ok and aff and (policy != "hardware" or b.kind == "qpu"):
                cands.append((b, est or 0.0))
        if not cands:
            why = "; ".join(f"{c['backend']}: {c['why']}" for c in considered
                            if policy != "hardware" or c["kind"] == "qpu")
            raise HardwareError(("no real quantum hardware is usable right now (connect a provider and set a budget, "
                                 "see quantum_backends)" if policy == "hardware" else "no backend available")
                                + (f" - {why}" if why else ""))
        remote_first = lambda b: 0 if b.id != "local" else 1  # noqa: E731  prefer a real provider over this server

        def speed(b):
            t = self.stats(b.id)["ewma_turnaround_s"]
            return t if t is not None else (1.0 if b.id == "local" else 60.0)
        if policy == "fastest":
            cands.sort(key=lambda c: (speed(c[0]), c[1]))
        else:
            cands.sort(key=lambda c: (c[1], remote_first(c[0]), speed(c[0])))
        chosen = cands[0]
        for c in considered:
            c["chosen"] = c["backend"] == chosen[0].id
        return chosen[0], chosen[1], considered

    # -- jobs
    def submit(self, problem: str, data: dict, qasm: str, shots: int, layers: int, training: dict,
               backend: str = "auto", policy: str = "cheapest", max_cost: float | None = None, owner: str = "") -> dict:
        n, gates = parse_qasm(qasm)
        b, est, considered = self.choose(backend, policy, shots, max_cost)
        jid = "hw_" + secrets.token_hex(8)
        pid = b.submit(qasm, n, gates, shots, f"privi {problem} {jid}")
        if est:
            self._add_spend(est)
        with self._lock:
            self._db.execute("INSERT INTO hw_jobs (job_id, backend_id, provider_job_id, problem, data, qasm, qubits, shots, layers, "
                             "training, status, est_cost_usd, submitted_at, submitted_unix, owner) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                             (jid, b.id, pid, problem, json.dumps(data), qasm, n, shots, layers, json.dumps(training),
                              "queued", est, now_iso(), time.time(), owner))
            self._db.commit()
        return {"job_id": jid, "backend": b.info(), "provider_job_id": pid, "estimated_cost_usd": est,
                "routing": considered}

    def get(self, jid: str) -> dict | None:
        r = self._db.execute("SELECT * FROM hw_jobs WHERE job_id=?", (jid,)).fetchone()
        if not r:
            return None
        d = dict(r)
        for k in ("data", "training", "counts", "result"):
            if d.get(k):
                d[k] = json.loads(d[k])
        if d.get("counts"):
            d["counts"] = {int(k): v for k, v in d["counts"].items()}
        return d

    def refresh(self, jid: str) -> dict | None:
        """Poll the provider if the job is still open; store counts when it finishes."""
        j = self.get(jid)
        if not j or j["status"] in TERMINAL:
            return j
        b = self.backends.get(j["backend_id"])
        if not b:
            return j
        try:
            r = b.fetch(j["provider_job_id"], j["qubits"], j["shots"])
        except HardwareError as e:
            return {**j, "poll_error": str(e)}
        except Exception as e:  # provider SDK errors: keep the job open, report it
            return {**j, "poll_error": f"{type(e).__name__}: {e}"[:300]}
        st = r["status"]
        if st in TERMINAL:
            ta = time.time() - j["submitted_unix"]
            with self._lock:
                self._db.execute("UPDATE hw_jobs SET status=?, error=?, finished_at=?, turnaround_s=?, counts=? WHERE job_id=?",
                                 (st, r.get("error", ""), now_iso(), round(ta, 3),
                                  json.dumps(r.get("counts")) if r.get("counts") else None, jid))
                self._db.commit()
            self._observe(j["backend_id"], ta, st == "done")
        elif st != j["status"]:
            with self._lock:
                self._db.execute("UPDATE hw_jobs SET status=? WHERE job_id=?", (st, jid))
                self._db.commit()
        return self.get(jid)

    def save_result(self, jid: str, result: dict, attestation_id: str, receipt_id: str) -> None:
        with self._lock:
            self._db.execute("UPDATE hw_jobs SET result=?, attestation_id=?, receipt_id=? WHERE job_id=?",
                             (json.dumps(result), attestation_id, receipt_id, jid))
            self._db.commit()

    def finished_with_receipts(self, limit: int = 25) -> list[dict]:
        """Newest finished jobs on a real provider (not this server's simulator) that carry an advantage receipt."""
        rows = self._db.execute(
            "SELECT job_id, backend_id, problem, qubits, shots, finished_at, turnaround_s, receipt_id FROM hw_jobs "
            "WHERE status='done' AND receipt_id IS NOT NULL AND backend_id != 'local' "
            "ORDER BY submitted_unix DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def open_jobs(self, limit: int = 50) -> list[str]:
        return [r["job_id"] for r in self._db.execute(
            "SELECT job_id FROM hw_jobs WHERE status NOT IN ('done','failed','canceled') ORDER BY submitted_unix LIMIT ?", (limit,))]
