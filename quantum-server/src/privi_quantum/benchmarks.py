# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Quantum - https://priviflow.us - dariocanoy@priviflow.us
"""Public, signed benchmarks: Privi's quantum solver against classical baselines, problem by problem.

Why this exists: a quantum claim nobody can check is worth nothing to a buyer. This suite runs a fixed,
seeded set of factory problems from 6 to 16 qubits, races CVaR-QAOA (exact statevector simulation)
against exhaustive search (the proven optimum) and simulated annealing, and publishes every result,
including the ones classical wins. Each suite run is signed (Ed25519 + ML-DSA-87) and anchored like
any other Privi attestation, so the numbers on the page cannot be edited afterwards.

Two numbers matter and are reported separately:
  verdict       answer quality first, then wall-clock time (advantage.verdict). At these sizes classical
                is expected to win or tie on time; we say so.
  lift          how much more often the trained circuit lands on the optimum than a random guess
                (probability_of_optimum / random_guess_probability). This is what the quantum circuit
                actually contributes, measured on an ideal simulator.
Real-hardware runs (IonQ, IBM, Braket) appear in their own section with their own receipts.
"""
from __future__ import annotations

import html
import json
import sqlite3
import threading
import time
from datetime import datetime, timezone
from typing import Any

import numpy as np

from . import advantage, qaoa

SCHEMA = """
CREATE TABLE IF NOT EXISTS benchmark_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  attestation_id TEXT,
  body TEXT NOT NULL
);
"""

SUITE_VERSION = "2026.10-1"
LAYERS = 2
SHOTS = 2048


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def suite_cases() -> list[dict[str, Any]]:
    """The fixed problem set. Seeded, so every run benchmarks exactly the same problems."""
    rng = np.random.default_rng(20261028)
    cases: list[dict[str, Any]] = []
    for n in (6, 10, 14, 16):
        jobs = [{"name": f"job-{i + 1}", "minutes": int(rng.integers(8, 90))} for i in range(n)]
        cases.append({"id": f"balance_lines-{n}", "problem": "balance_lines", "data": {"jobs": jobs},
                      "story": f"split {n} jobs across two lines so both finish together"})
    for n in (8, 12, 16):
        lots = [{"name": f"lot-{i + 1}", "risk": round(float(rng.uniform(0.05, 0.95)), 3)} for i in range(n)]
        linked = [[f"lot-{a + 1}", f"lot-{a + 2}"] for a in range(0, n - 1, 3)]
        cases.append({"id": f"select_lots-{n}", "problem": "select_lots",
                      "data": {"lots": lots, "k": max(2, n // 3), "linked": linked},
                      "story": f"pick {max(2, n // 3)} of {n} lots to inspect by risk, avoiding linked pairs"})
    for n in (10, 14):
        items = [f"part-{i + 1}" for i in range(n)]
        conflicts = []
        for a in range(n):
            for b in range(a + 1, n):
                if rng.random() < 0.35:
                    conflicts.append({"a": items[a], "b": items[b], "weight": int(rng.integers(1, 10))})
        cases.append({"id": f"split_conflicts-{n}", "problem": "split_conflicts",
                      "data": {"items": items, "conflicts": conflicts},
                      "story": f"split {n} parts into two shifts keeping conflicting parts apart"})
    return cases


def run_case(case: dict[str, Any], layers: int = LAYERS, shots: int = SHOTS, seed: int = 7) -> dict[str, Any]:
    qubo, _ = qaoa.build(case["problem"], case["data"])
    r = qaoa.solve(qubo, layers=layers, shots=shots, seed=seed)
    exact = advantage.exhaustive(qubo)
    sa = advantage.simulated_annealing(qubo)
    quantum = {"method": r["algorithm"], "backend": "local", "backend_kind": "simulator", "cost": r["cost"],
               "found_optimum": r["found_optimum"], "runtime_ms": float(r["runtime_ms"])}
    v = advantage.verdict(quantum, [exact, sa])
    p_opt, p_rand = r["probability_of_optimum"], r["random_guess_probability_of_optimum"]
    sa_opt = sa["cost"] <= exact["cost"] + 1e-9 * max(1.0, abs(exact["cost"]))
    return {
        "id": case["id"], "problem": case["problem"], "story": case["story"], "qubits": qubo.n, "layers": layers,
        "shots": shots,
        "quantum": {"cost": r["cost"], "found_optimum": r["found_optimum"], "probability_of_optimum": p_opt,
                    "approximation_ratio": r["approximation_ratio"], "runtime_ms": round(float(r["runtime_ms"]), 3)},
        "exhaustive": {"cost": exact["cost"], "runtime_ms": exact["runtime_ms"]},
        "simulated_annealing": {"cost": sa["cost"], "found_optimum": sa_opt, "runtime_ms": sa["runtime_ms"]},
        "random_guess_probability_of_optimum": p_rand,
        "lift_over_random": round(p_opt / p_rand, 2) if p_rand > 0 else None,
        "verdict": v["verdict"], "why": v["why"],
    }


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(results)
    counts = {k: sum(1 for r in results if r["verdict"] == k) for k in advantage.VERDICTS}
    found = sum(1 for r in results if r["quantum"]["found_optimum"])
    lifts = [r["lift_over_random"] for r in results if r["lift_over_random"]]
    geo = float(np.exp(np.mean(np.log(lifts)))) if lifts else None
    headline = (f"Quantum found the proven optimum in {found} of {n} problems. On time, classical won {counts['classical_won']}, "
                f"quantum won {counts['quantum_won']}, tied {counts['tie']}. The trained circuit lands on the optimum "
                f"{geo:.0f}x more often than random guessing (geometric mean)." if geo else
                f"Quantum found the proven optimum in {found} of {n} problems.")
    return {"problems": n, "quantum_found_optimum": found, "verdicts": counts,
            "lift_over_random_geomean": round(geo, 2) if geo else None, "headline": headline,
            "what_this_means": ("At 6-16 qubits a laptop finds the exact answer quickly, so classical wins on time. "
                                "That is expected and stated on every receipt. What the suite proves is that Privi's "
                                "circuits are trained correctly and concentrate probability on the best answer, and that "
                                "the same pipeline sends them to real quantum hardware with a signed, checkable result. "
                                "Privi will claim a quantum advantage only when a receipt here shows one.")}


class Benchmarks:
    def __init__(self, db_path: str, attestor, router=None, public_url: str = ""):
        self.attestor, self.router, self.public_url = attestor, router, public_url.rstrip("/")
        self._lock = threading.Lock()
        self._running = threading.Lock()
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.commit()

    def run(self, cases: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
        """Run the suite, sign it, store it. Returns None if a run is already in progress."""
        if not self._running.acquire(blocking=False):
            return None
        try:
            t0 = time.perf_counter()
            results = [run_case(c) for c in (cases or suite_cases())]
            body = {"suite_version": SUITE_VERSION, "ran_at": _now(), "engine": "exact statevector simulator",
                    "layers": LAYERS, "shots": SHOTS, "results": results, "summary": summarize(results),
                    "suite_runtime_s": round(time.perf_counter() - t0, 2),
                    "honesty": "Every problem is published, whichever side wins."}
            att = self.attestor.issue("benchmark_suite", body)
            with self._lock:
                self._db.execute("INSERT INTO benchmark_runs (created_at, attestation_id, body) VALUES (?, ?, ?)",
                                 (body["ran_at"], att["id"], json.dumps(body)))
                self._db.commit()
            return {**body, "attestation_id": att["id"]}
        finally:
            self._running.release()

    def running(self) -> bool:
        if self._running.acquire(blocking=False):
            self._running.release()
            return False
        return True

    def latest(self) -> dict[str, Any] | None:
        r = self._db.execute("SELECT * FROM benchmark_runs ORDER BY id DESC LIMIT 1").fetchone()
        if not r:
            return None
        return {**json.loads(r["body"]), "attestation_id": r["attestation_id"]}

    def age_s(self) -> float | None:
        last = self.latest()
        if not last:
            return None
        return (datetime.now(timezone.utc) - datetime.fromisoformat(last["ran_at"])).total_seconds()

    def hardware_runs(self, limit: int = 25) -> list[dict[str, Any]]:
        """Finished real-backend jobs that carry an advantage receipt (never the problem data)."""
        if self.router is None:
            return []
        out = []
        for j in self.router.finished_with_receipts(limit):
            rc = self.attestor.get(j["receipt_id"]) if j.get("receipt_id") else None
            b = (rc or {}).get("body", {})
            out.append({"job_id": j["job_id"], "backend": j["backend_id"], "problem": j["problem"], "qubits": j["qubits"],
                        "shots": j["shots"], "finished_at": j.get("finished_at"), "turnaround_s": j.get("turnaround_s"),
                        "found_optimum": (b.get("quantum") or {}).get("found_optimum"),
                        "verdict": b.get("verdict"), "receipt_id": j.get("receipt_id"),
                        "receipt_url": f"{self.public_url}/receipts/{j['receipt_id']}" if j.get("receipt_id") else None})
        return out

    def report(self) -> dict[str, Any]:
        last = self.latest()
        out: dict[str, Any] = {"suite": last, "hardware_runs": self.hardware_runs(), "running": self.running()}
        if last:
            out["verify"] = {"attestation_id": last["attestation_id"],
                             "attestation_url": f"{self.public_url}/attestations/{last['attestation_id']}",
                             "how": "quantum_verify with this id checks both signatures and the on-chain anchor"}
        return out


def render_page(rep: dict[str, Any], public_url: str, copyright_line: str) -> str:
    e = html.escape
    suite = rep.get("suite")
    if not suite:
        body = ("<p class='muted'>The first benchmark run is in progress. This page fills in within a few minutes."
                "</p>" if rep.get("running") else "<p class='muted'>No benchmark run yet.</p>")
        rows_html = hw_html = ""
        head = ""
    else:
        s = suite["summary"]
        head = (f"<p class='lead'>{e(s['headline'])}</p><p>{e(s['what_this_means'])}</p>"
                f"<p class='muted'>Suite {e(suite['suite_version'])}, run {e(suite['ran_at'])} on an "
                f"{e(suite['engine'])}, p={suite['layers']}, {suite['shots']} shots. Signed attestation "
                f"<a href='{e(public_url)}/attestations/{e(suite['attestation_id'])}'>{e(suite['attestation_id'])}</a>.</p>")
        body = ""
        rows = []
        for r in suite["results"]:
            q, sa = r["quantum"], r["simulated_annealing"]
            badge = {"quantum_won": "q", "classical_won": "c", "tie": "t"}[r["verdict"]]
            rows.append(
                f"<tr><td><b>{e(r['id'])}</b><div class='muted'>{e(r['story'])}</div></td><td class='n'>{r['qubits']}</td>"
                f"<td class='n'>{'yes' if q['found_optimum'] else 'no'}</td>"
                f"<td class='n'>{q['probability_of_optimum'] * 100:.1f}%</td>"
                f"<td class='n'>{(str(r['lift_over_random']) + 'x') if r['lift_over_random'] else '-'}</td>"
                f"<td class='n'>{q['runtime_ms']:.0f}</td><td class='n'>{r['exhaustive']['runtime_ms']:.1f}</td>"
                f"<td class='n'>{'yes' if sa['found_optimum'] else 'no'} / {sa['runtime_ms']:.0f}</td>"
                f"<td><span class='v {badge}'>{e(r['verdict'].replace('_', ' '))}</span></td></tr>")
        rows_html = ("<div class='scroll'><table><thead><tr><th>Problem</th><th>Qubits</th><th>Quantum found optimum</th>"
                     "<th>P(optimum)</th><th>Lift vs random</th><th>Quantum ms</th><th>Exact search ms</th>"
                     "<th>Annealing optimum / ms</th><th>Verdict</th></tr></thead><tbody>" + "".join(rows) +
                     "</tbody></table></div>")
        hw = rep.get("hardware_runs") or []
        if hw:
            hw_rows = "".join(
                f"<tr><td>{e(j['backend'])}</td><td>{e(j['problem'])}</td><td class='n'>{j['qubits']}</td>"
                f"<td class='n'>{'yes' if j['found_optimum'] else 'no' if j['found_optimum'] is not None else '-'}</td>"
                f"<td class='n'>{j['turnaround_s'] or '-'}</td><td>{e(str(j['verdict'] or '-').replace('_', ' '))}</td>"
                f"<td>{'<a href=' + chr(39) + e(j['receipt_url']) + chr(39) + '>receipt</a>' if j['receipt_url'] else '-'}</td></tr>"
                for j in hw)
            hw_html = ("<h2>Real quantum hardware runs</h2><div class='scroll'><table><thead><tr><th>Backend</th><th>Problem</th>"
                       "<th>Qubits</th><th>Found optimum</th><th>Turnaround s</th><th>Verdict</th><th></th></tr></thead><tbody>"
                       + hw_rows + "</tbody></table></div>")
        else:
            hw_html = ("<h2>Real quantum hardware runs</h2><p class='muted'>None published yet. Runs on IonQ, IBM Quantum "
                       "and Amazon Braket appear here with their signed receipts as they finish.</p>")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Privi Quantum Benchmarks</title>
<meta name="description" content="Signed, public benchmarks of Privi Quantum against classical solvers, including the cases classical wins.">
<style>
:root{{--bg:#fbfaf7;--fg:#1b1d22;--muted:#6b6f78;--line:#e4e1da;--card:#fff;--q:#1d6b4f;--c:#8a4b12;--t:#4a4f8a}}
@media (prefers-color-scheme:dark){{:root{{--bg:#111316;--fg:#e9e7e2;--muted:#9a9ea7;--line:#2a2d33;--card:#181b1f;--q:#5fc49a;--c:#e0a46a;--t:#a3a8e6}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 system-ui,-apple-system,Segoe UI,sans-serif}}
main{{max-width:1040px;margin:0 auto;padding:32px 16px 64px}}
h1{{font-size:28px;margin:0 0 4px}} h2{{font-size:19px;margin:36px 0 10px}}
.lead{{font-size:18px;font-weight:600}} .muted{{color:var(--muted);font-size:14px}}
a{{color:inherit}} .scroll{{overflow-x:auto;border:1px solid var(--line);border-radius:10px;background:var(--card)}}
table{{border-collapse:collapse;width:100%;font-size:14px}} th,td{{padding:9px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}
th{{font-weight:600;color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.03em}}
td.n{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}}
.v{{font-size:12px;font-weight:600;padding:2px 8px;border-radius:99px;border:1px solid currentColor;white-space:nowrap}}
.v.q{{color:var(--q)}} .v.c{{color:var(--c)}} .v.t{{color:var(--t)}}
footer{{margin-top:40px}}
</style></head><body><main>
<h1>Privi Quantum benchmarks</h1>
<p class="muted">Every problem, every result, whichever side wins. JSON: <a href="{e(public_url)}/benchmarks.json">/benchmarks.json</a></p>
{head}{body}{rows_html}{hw_html}
<h2>How to check this</h2>
<p>Each suite run is one attestation signed with Ed25519 and ML-DSA-87 and anchored on chain. Anyone can verify it with the
<code>quantum_verify</code> tool on <code>{e(public_url)}/mcp</code>, or re-run any problem with <code>quantum_advantage_receipt</code>.</p>
<footer class="muted">{e(copyright_line)}</footer>
</main></body></html>"""
