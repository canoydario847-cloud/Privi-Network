# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Quantum - https://priviflow.us - dariocanoy@priviflow.us
"""The Privi quantum realm: Privilege, Dream Weaver and Dream Scape.

Privilege   The directory of quantum realms. A realm is somewhere a quantum job can run:
            a quantum engine inside this server, or another Privi Quantum node (another
            region or machine). Privilege measures every realm from real runs and benchmarks:
            time to answer, how often it finds the proven optimum, and the expected time to
            the optimum, and ranks realms by it.

Dream Weaver  Runs one quantum job on several realms at once. In "first" mode the first valid
            answer wins and the rest are cancelled; with hedge_ms it starts on the top realm and
            fans out only if no answer has arrived by then (or a realm fails). In "best" mode
            every realm runs until the deadline and the best answer wins. Every result is signed
            (Ed25519 + ML-DSA-87) and anchored on chain like any Privi Quantum attestation.

Dream Scape The environment: a private workspace (scape_id + scape_key) that keeps its jobs and
            results. Jobs come in by MCP tool or over one WebSocket (/dreamscape/ws) that runs many
            jobs at once and streams each realm's progress.

Scope, stated plainly: realms run quantum algorithms (CVaR-QAOA) on exact simulators today, and
racing chooses the fastest realm; it does not make any processor or link faster than it is.
Real quantum hardware joins Privilege as a realm once a provider account is connected.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import os
import re
import secrets
import socket
import sqlite3
import threading
import time
from typing import Any, Awaitable, Callable
from urllib.parse import urlsplit

import anyio
import httpx2

from . import qaoa
from .attest import now_iso

MODES = ("first", "best")
MAX_FANOUT = 8
WS_CONCURRENCY = 16
WS_PER_MIN = 120
PROTOCOL = "2025-06-18"
JOBS_KEPT = 500

# Built-in engines: both run CVaR-QAOA on the exact statevector simulator.
ENGINES = {
    "dreamscape-exact": {"name": "Dream Scape Exact", "location": "this server",
                         "about": "CVaR-QAOA at the requested depth; best answers, slower"},
    "dreamscape-swift": {"name": "Dream Scape Swift", "location": "this server",
                         "about": "CVaR-QAOA at depth 1 with a short training budget; fastest, approximate"},
}

BENCHMARK = ("balance_lines", {"jobs": [{"name": f"J{i}", "minutes": m}
                                        for i, m in enumerate([42, 17, 33, 8, 25, 61, 12, 29])]})

SCHEMA = """
CREATE TABLE IF NOT EXISTS dream_realms (
    realm_id   TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    kind       TEXT NOT NULL,              -- engine | node
    url        TEXT NOT NULL DEFAULT '',
    location   TEXT NOT NULL DEFAULT '',
    active     INTEGER NOT NULL DEFAULT 1,
    added_at   TEXT NOT NULL,
    ewma_ms    REAL,
    runs       INTEGER NOT NULL DEFAULT 0,
    optimum_hits INTEGER NOT NULL DEFAULT 0,
    failures   INTEGER NOT NULL DEFAULT 0,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    wins       INTEGER NOT NULL DEFAULT 0,
    last_seen  TEXT,
    last_error TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS dream_scapes (
    scape_id   TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    key_hash   TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dream_jobs (
    job_id      TEXT PRIMARY KEY,
    scape_id    TEXT NOT NULL,
    status      TEXT NOT NULL,             -- running | done | failed
    request     TEXT NOT NULL,
    result      TEXT,
    created_at  TEXT NOT NULL,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_dream_jobs_scape ON dream_jobs (scape_id, created_at);
"""

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{1,63}$")


class DreamError(ValueError):
    pass


def _hash_key(key: str) -> str:
    return hashlib.sha256(("privi-dreamscape:" + key).encode()).hexdigest()


def problem_sha(problem: str, data: dict) -> str:
    return hashlib.sha256(json.dumps({"problem": problem, "data": data}, sort_keys=True, default=str).encode()).hexdigest()


def check_node_url(url: str, allow_private: bool = False) -> str:
    u = urlsplit((url or "").strip())
    if u.scheme != "https" and not (allow_private and u.scheme == "http"):
        raise DreamError("a node URL must be public https://")
    host = (u.hostname or "").lower()
    if not host or u.username or u.password:
        raise DreamError("node URL needs a host and no credentials")
    if not allow_private:
        if host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
            raise DreamError("node host is not public")
        try:
            infos = socket.getaddrinfo(host, u.port or 443, 0, socket.SOCK_STREAM)
        except OSError:
            raise DreamError(f"cannot resolve {host}")
        if any(not ipaddress.ip_address(sa[0]).is_global for *_, sa in infos):
            raise DreamError("node resolves to a non-public address")
    return url.strip()


# ---------------------------------------------------------------- Privilege

class Privilege:
    """Directory of quantum realms, ranked by measured speed to the optimum."""

    def __init__(self, db_path: str, nodes_env: str = "", allow_private: bool = False):
        self.allow_private = allow_private
        self._lock = threading.Lock()
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.executescript(SCHEMA)
            for rid, e in ENGINES.items():
                self._db.execute("INSERT OR IGNORE INTO dream_realms (realm_id, name, kind, location, added_at) "
                                 "VALUES (?,?, 'engine', ?, ?)", (rid, e["name"], e["location"], now_iso()))
            self._db.commit()
        for part in filter(None, (p.strip() for p in (nodes_env or "").split(";"))):
            name, _, url = part.partition("=")
            try:
                self.add_node(name.strip(), url.strip(), "", check=False)
            except DreamError as e:
                print(f"[privi-quantum] ignoring DREAMWEAVER_NODES entry {name!r}: {e}", flush=True)

    @property
    def db(self):
        return self._db

    def add_node(self, name: str, url: str, location: str = "", check: bool = True) -> dict:
        if not NAME_RE.match(name or ""):
            raise DreamError("name: 2-64 letters, digits, spaces, . _ -")
        url = check_node_url(url, self.allow_private) if check else url.strip()
        if not url.startswith(("https://", "http://")):
            raise DreamError("node URL must start with https://")
        rid = "node-" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40]
        with self._lock:
            self._db.execute("""INSERT INTO dream_realms (realm_id, name, kind, url, location, added_at)
                                VALUES (?,?, 'node', ?,?,?)
                                ON CONFLICT(realm_id) DO UPDATE SET url=excluded.url, location=excluded.location, active=1""",
                             (rid, name, url, (location or "")[:80], now_iso()))
            self._db.commit()
        return self.get(rid)

    def remove(self, realm_id: str) -> bool:
        if realm_id in ENGINES:
            raise DreamError("built-in engines cannot be removed")
        with self._lock:
            n = self._db.execute("UPDATE dream_realms SET active=0 WHERE realm_id=? AND kind='node'", (realm_id,)).rowcount
            self._db.commit()
        return n > 0

    def get(self, realm_id: str) -> dict | None:
        r = self._db.execute("SELECT * FROM dream_realms WHERE realm_id=?", (realm_id,)).fetchone()
        return dict(r) if r else None

    def active(self) -> list[dict]:
        return [dict(r) for r in self._db.execute("SELECT * FROM dream_realms WHERE active=1").fetchall()]

    @staticmethod
    def metrics(r: dict) -> dict:
        ok = r["runs"]
        rate = r["optimum_hits"] / ok if ok else None
        exp = None
        if r["ewma_ms"] is not None and rate:
            exp = round(r["ewma_ms"] / rate)
        if r["consecutive_failures"] >= 3:
            status = "down"
        elif not ok:
            status = "untested"
        else:
            status = "ready"
        return {"latency_ms": None if r["ewma_ms"] is None else round(r["ewma_ms"]),
                "optimum_rate": None if rate is None else round(rate, 3),
                "expected_ms_to_optimum": exp, "status": status}

    def rank_key(self, r: dict) -> float:
        m = self.metrics(r)
        if m["status"] == "down":
            return 1e12
        if m["expected_ms_to_optimum"] is not None:
            return float(m["expected_ms_to_optimum"])
        base = r["ewma_ms"] if r["ewma_ms"] is not None else 2000.0    # untested: try after proven realms
        return base * 4 if m["optimum_rate"] == 0 else base

    def ranked(self) -> list[dict]:
        return sorted(self.active(), key=self.rank_key)

    def pick(self, fanout: int, only: list[str] | None = None) -> list[dict]:
        realms = self.ranked()
        if only:
            want = set(only)
            unknown = want - {r["realm_id"] for r in realms}
            if unknown:
                raise DreamError(f"unknown or inactive realm(s): {', '.join(sorted(unknown))}")
            realms = [r for r in realms if r["realm_id"] in want]
        live = [r for r in realms if self.metrics(r)["status"] != "down"] or realms
        return live[:max(1, min(fanout, MAX_FANOUT))]

    def observe(self, realm_id: str, ms: float | None, optimum: bool | None = None, won: bool = False,
                error: str = "") -> None:
        with self._lock:
            r = self._db.execute("SELECT ewma_ms FROM dream_realms WHERE realm_id=?", (realm_id,)).fetchone()
            if not r:
                return
            if ms is None:
                self._db.execute("UPDATE dream_realms SET failures=failures+1, consecutive_failures=consecutive_failures+1, "
                                 "last_error=? WHERE realm_id=?", (error[:200], realm_id))
            else:
                ew = ms if r["ewma_ms"] is None else 0.7 * r["ewma_ms"] + 0.3 * ms
                self._db.execute("UPDATE dream_realms SET ewma_ms=?, runs=runs+1, optimum_hits=optimum_hits+?, "
                                 "wins=wins+?, consecutive_failures=0, last_seen=?, last_error='' WHERE realm_id=?",
                                 (ew, 1 if optimum else 0, 1 if won else 0, now_iso(), realm_id))
            self._db.commit()

    def add_win(self, realm_id: str) -> None:
        with self._lock:
            self._db.execute("UPDATE dream_realms SET wins=wins+1 WHERE realm_id=?", (realm_id,))
            self._db.commit()

    def directory(self) -> dict:
        realms = []
        for i, r in enumerate(self.ranked(), 1):
            realms.append({"rank": i, "realm_id": r["realm_id"], "name": r["name"], "kind": r["kind"],
                           "location": r["location"] or None, "max_qubits": qaoa.MAX_QUBITS,
                           "about": ENGINES.get(r["realm_id"], {}).get("about", "Privi Quantum node (CVaR-QAOA)"),
                           **self.metrics(r), "runs": r["runs"], "wins": r["wins"], "failures": r["failures"],
                           "last_seen": r["last_seen"], "last_error": r["last_error"] or None})
        return {"directory": "Privilege", "realms": realms,
                "ranking": "by expected time to the proven optimum (latency / optimum rate), from real runs and benchmarks",
                "note": "Realms run CVaR-QAOA on exact simulators; quantum hardware joins as a realm when a provider "
                        "account is connected."}


# ---------------------------------------------------------------- Dream Weaver

class DreamWeaver:
    def __init__(self, privilege: Privilege, attestor, limiter: anyio.CapacityLimiter,
                 client: httpx2.AsyncClient | None = None):
        self.privilege, self.attestor, self.limiter = privilege, attestor, limiter
        self._client = client

    @property
    def client(self) -> httpx2.AsyncClient:
        if self._client is None:
            self._client = httpx2.AsyncClient(timeout=httpx2.Timeout(connect=5.0, read=120.0, write=15.0, pool=5.0),
                                              follow_redirects=False,
                                              limits=httpx2.Limits(max_connections=200, max_keepalive_connections=50))
        return self._client

    # -- realms -----------------------------------------------------------

    async def _engine(self, engine: str, problem: str, data: dict, layers: int, shots: int) -> dict:
        def work():
            qubo, decode = qaoa.build(problem, data)
            if engine == "dreamscape-swift":
                r = qaoa.solve(qubo, layers=1, shots=min(shots, 512), deadline_s=1.0)
            else:
                r = qaoa.solve(qubo, layers=layers, shots=shots)
            return {"decision": decode(r["solution"]), "found_optimum": r["found_optimum"],
                    "approximation_ratio": r["approximation_ratio"],
                    "probability_of_optimum": r["probability_of_optimum"], "qubits": r["qubits"],
                    "layers": 1 if engine == "dreamscape-swift" else layers, "runtime_ms": r["runtime_ms"],
                    "angles": r["angles"]}
        return await anyio.to_thread.run_sync(work, abandon_on_cancel=True, limiter=self.limiter)

    async def _rpc(self, url: str, method: str, params: dict, session: str | None, rid: Any) -> tuple[dict, str | None]:
        headers = {"content-type": "application/json", "accept": "application/json, text/event-stream",
                   "mcp-protocol-version": PROTOCOL}
        if session:
            headers["mcp-session-id"] = session
        body: dict[str, Any] = {"jsonrpc": "2.0", "method": method, "params": params}
        if rid is not None:
            body["id"] = rid
        resp = await self.client.post(url, content=json.dumps(body), headers=headers)
        if rid is None:
            return {}, session
        if resp.status_code >= 400:
            raise DreamError(f"node answered HTTP {resp.status_code}")
        ctype = resp.headers.get("content-type", "")
        if "text/event-stream" in ctype:
            for ev in resp.text.replace("\r\n", "\n").split("\n\n"):
                payload = "\n".join(l[5:].lstrip() for l in ev.split("\n") if l.startswith("data:"))
                if payload:
                    msg = json.loads(payload)
                    if isinstance(msg, dict) and msg.get("id") == rid:
                        return msg, resp.headers.get("mcp-session-id") or session
            raise DreamError("node sent no response")
        msg = resp.json()
        if not isinstance(msg, dict):
            raise DreamError("node sent an unexpected response")
        return msg, resp.headers.get("mcp-session-id") or session

    async def _node(self, url: str, problem: str, data: dict, layers: int, shots: int) -> dict:
        init, session = await self._rpc(url, "initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                                                            "clientInfo": {"name": "privi-dreamweaver", "version": "1"}},
                                        None, 0)
        if "error" in init:
            raise DreamError("node refused initialize")
        await self._rpc(url, "notifications/initialized", {}, session, None)
        msg, _ = await self._rpc(url, "tools/call", {"name": "quantum_optimize", "arguments": {
            "problem": problem, "data": data, "layers": layers, "shots": shots}}, session, 1)
        if "error" in msg:
            raise DreamError(msg["error"].get("message", "node error"))
        res = msg.get("result") or {}
        sc = res.get("structuredContent")
        if sc is None:
            try:
                sc = json.loads(next(c["text"] for c in res.get("content", []) if c.get("type") == "text"))
            except (StopIteration, ValueError, KeyError):
                sc = {}
        if res.get("isError") or "decision" not in sc:
            raise DreamError(str(sc.get("error") or "node returned no decision")[:200])
        q, run = sc.get("quality") or {}, sc.get("quantum_run") or {}
        att = sc.get("attestation") or {}
        return {"decision": sc["decision"], "found_optimum": bool(q.get("found_optimum")),
                "approximation_ratio": float(q.get("approximation_ratio") or 0.0),
                "probability_of_optimum": q.get("probability_of_optimum"), "qubits": run.get("qubits"),
                "layers": layers, "runtime_ms": run.get("runtime_ms"), "angles": run.get("angles"),
                "node_attestation": {"id": att.get("id"), "url": att.get("attestation_url")}}

    async def _run(self, realm: dict, problem: str, data: dict, layers: int, shots: int) -> dict:
        if realm["kind"] == "engine":
            return await self._engine(realm["realm_id"], problem, data, layers, shots)
        return await self._node(realm["url"], problem, data, layers, shots)

    # -- the weave ----------------------------------------------------------

    async def weave(self, problem: str, data: dict, *, layers: int = 2, shots: int = 1024, mode: str = "first",
                    fanout: int = 3, hedge_ms: int = 0, deadline_s: float = 30.0, realms: list[str] | None = None,
                    on_event: Callable[[dict], Awaitable[None]] | None = None, scape_id: str | None = None,
                    benchmark: bool = False) -> dict:
        if mode not in MODES:
            raise DreamError(f"mode must be one of {', '.join(MODES)}")
        if not 1 <= int(layers) <= qaoa.MAX_LAYERS:
            raise DreamError(f"layers must be 1-{qaoa.MAX_LAYERS}")
        if not 1 <= int(shots) <= 100_000:
            raise DreamError("shots must be 1-100000")
        qubo, _ = qaoa.build(problem, data)        # validates before any realm is used (raises ProblemError)
        hedge_ms = 0 if mode == "best" else max(0, min(int(hedge_ms), 10_000))
        deadline_s = max(1.0, min(float(deadline_s), 120.0))
        targets = self.privilege.pick(int(fanout), realms)
        weave_id = "dw_" + secrets.token_hex(6)
        t0 = time.perf_counter()
        results: list[dict] = []
        attempts: list[dict] = []
        state: dict[str, Any] = {"winner": None}
        done, kick = anyio.Event(), anyio.Event()

        async def emit(ev: dict) -> None:
            if on_event:
                try:
                    await on_event({"weave_id": weave_id, **ev})
                except Exception:
                    pass

        async def one(realm: dict, delay: float, scope: anyio.CancelScope) -> None:
            rid = realm["realm_id"]
            if delay:
                with anyio.move_on_after(delay):
                    await kick.wait()
                if done.is_set():
                    attempts.append({"realm_id": rid, "status": "not_needed"})
                    return
            await emit({"type": "realm.started", "realm_id": rid})
            st = time.perf_counter()
            try:
                res = await self._run(realm, problem, data, layers, shots)
            except anyio.get_cancelled_exc_class():
                attempts.append({"realm_id": rid, "status": "cancelled"})
                raise
            except Exception as e:
                err = str(e) or type(e).__name__
                self.privilege.observe(rid, None, error=err)
                attempts.append({"realm_id": rid, "status": "failed", "error": err[:200]})
                kick.set()
                await emit({"type": "realm.failed", "realm_id": rid, "error": err[:200]})
                return
            ms = (time.perf_counter() - st) * 1000
            res.update(realm_id=rid, latency_ms=round(ms))
            results.append(res)
            first = mode == "first" and state["winner"] is None
            self.privilege.observe(rid, ms, res["found_optimum"], won=first)
            attempts.append({"realm_id": rid, "status": "won" if first else "answered", "latency_ms": round(ms),
                             "found_optimum": res["found_optimum"], "approximation_ratio": res["approximation_ratio"]})
            await emit({"type": "realm.result", "realm_id": rid, "latency_ms": round(ms),
                        "found_optimum": res["found_optimum"], "approximation_ratio": res["approximation_ratio"]})
            if first:
                state["winner"] = res
                done.set()
                kick.set()
                scope.cancel()

        with anyio.move_on_after(deadline_s):
            async with anyio.create_task_group() as tg:
                for i, realm in enumerate(targets):
                    tg.start_soon(one, realm, 0 if i == 0 else hedge_ms / 1000, tg.cancel_scope)
        started = {a["realm_id"] for a in attempts}
        attempts += [{"realm_id": r["realm_id"], "status": "timed_out"} for r in targets if r["realm_id"] not in started]

        if mode == "best" and results:
            best = max(results, key=lambda r: (r["found_optimum"], r["approximation_ratio"], -r["latency_ms"]))
            state["winner"] = best
            self.privilege.add_win(best["realm_id"])
            for a in attempts:
                if a["realm_id"] == best["realm_id"] and a["status"] == "answered":
                    a["status"] = "won"
        total_ms = round((time.perf_counter() - t0) * 1000)
        w = state["winner"]
        out: dict[str, Any] = {"weave_id": weave_id, "mode": mode, "problem": problem, "qubits": qubo.n,
                               "total_ms": total_ms, "realms_tried": len(targets), "hedge_ms": hedge_ms,
                               "attempts": sorted(attempts, key=lambda a: a.get("latency_ms", math.inf))}
        if not w:
            out.update(ok=False, error="no realm answered in time")
            await emit({"type": "weave.done", "ok": False, "total_ms": total_ms, "error": out["error"]})
            return out
        body = {"kind": "dreamweaver_result", "weave_id": weave_id, "mode": mode, "problem": problem,
                "problem_sha256": problem_sha(problem, data), "qubits": qubo.n, "winner_realm": w["realm_id"],
                "decision": w["decision"], "found_optimum": w["found_optimum"],
                "approximation_ratio": w["approximation_ratio"], "layers": w.get("layers"),
                "realms": [{k: a.get(k) for k in ("realm_id", "status", "latency_ms", "found_optimum")} for a in out["attempts"]],
                "node_attestation": (w.get("node_attestation") or {}).get("id"), "scape_id": scape_id,
                "benchmark": benchmark}
        att = await anyio.to_thread.run_sync(self.attestor.issue, "dreamweaver_result", body)
        out.update(ok=True, winner={"realm_id": w["realm_id"], "latency_ms": w["latency_ms"]},
                   decision=w["decision"],
                   quality={"found_optimum": w["found_optimum"], "approximation_ratio": w["approximation_ratio"],
                            "probability_of_optimum": w.get("probability_of_optimum")},
                   quantum_run={k: w.get(k) for k in ("layers", "runtime_ms", "angles")},
                   attestation={"id": att["id"], "body_sha256": att["body_sha256"]})
        if w.get("node_attestation", {}).get("id"):
            out["node_attestation"] = w["node_attestation"]
        await emit({"type": "weave.done", "ok": True, "total_ms": total_ms, "winner": out["winner"],
                    "decision": out["decision"], "quality": out["quality"], "attestation": out["attestation"]})
        return out


# ---------------------------------------------------------------- Dream Scape

class DreamScape:
    """Private quantum workspaces: each keeps its own jobs and results."""

    def __init__(self, privilege: Privilege, weaver: DreamWeaver):
        self.privilege, self.weaver = privilege, weaver
        self.gate: Callable[[str | None, str], dict] | None = None     # Privi Inspector, set by the server
        self._db, self._lock = privilege.db, privilege._lock

    def open(self, name: str) -> dict:
        if not NAME_RE.match(name or ""):
            raise DreamError("name: 2-64 letters, digits, spaces, . _ -")
        sid, key = "scape_" + secrets.token_hex(6), "dsk_" + secrets.token_urlsafe(24)
        with self._lock:
            self._db.execute("INSERT INTO dream_scapes VALUES (?,?,?,?)", (sid, name, _hash_key(key), now_iso()))
            self._db.commit()
        return {"scape_id": sid, "scape_key": key, "name": name}

    def auth(self, scape_id: str, key: str) -> bool:
        r = self._db.execute("SELECT key_hash FROM dream_scapes WHERE scape_id=?", (scape_id or "",)).fetchone()
        return bool(r and key and secrets.compare_digest(r["key_hash"], _hash_key(key)))

    def _save(self, job_id: str, status: str, result: dict | None) -> None:
        with self._lock:
            self._db.execute("UPDATE dream_jobs SET status=?, result=?, finished_at=? WHERE job_id=?",
                             (status, json.dumps(result) if result is not None else None, now_iso(), job_id))
            self._db.commit()

    async def submit(self, scape_id: str, request: dict, on_event=None) -> dict:
        job_id = "job_" + secrets.token_hex(6)
        with self._lock:
            self._db.execute("INSERT INTO dream_jobs (job_id, scape_id, status, request, created_at) VALUES (?,?,?,?,?)",
                             (job_id, scape_id, "running", json.dumps(request), now_iso()))
            self._db.execute("""DELETE FROM dream_jobs WHERE scape_id=? AND job_id NOT IN
                                (SELECT job_id FROM dream_jobs WHERE scape_id=? ORDER BY created_at DESC LIMIT ?)""",
                             (scape_id, scape_id, JOBS_KEPT))
            self._db.commit()

        async def ev(e: dict) -> None:
            if on_event:
                await on_event({"job_id": job_id, **e})

        await ev({"type": "job.accepted"})
        try:
            r = await self.weaver.weave(request["problem"], request["data"], layers=request.get("layers", 2),
                                        shots=request.get("shots", 1024), mode=request.get("mode", "first"),
                                        fanout=request.get("fanout", 3), hedge_ms=request.get("hedge_ms", 0),
                                        deadline_s=request.get("deadline_s", 30), realms=request.get("realms"),
                                        on_event=ev, scape_id=scape_id)
        except (DreamError, qaoa.ProblemError) as e:
            self._save(job_id, "failed", {"error": str(e)})
            await ev({"type": "job.failed", "error": str(e)})
            return {"job_id": job_id, "status": "failed", "error": str(e)}
        except Exception as e:  # keep the workspace consistent whatever happens
            self._save(job_id, "failed", {"error": "internal error"})
            await ev({"type": "job.failed", "error": "internal error"})
            raise
        self._save(job_id, "done" if r.get("ok") else "failed", r)
        return {"job_id": job_id, "status": "done" if r.get("ok") else "failed", **r}

    def job(self, scape_id: str, job_id: str) -> dict | None:
        r = self._db.execute("SELECT * FROM dream_jobs WHERE job_id=? AND scape_id=?", (job_id, scape_id)).fetchone()
        if not r:
            return None
        return {"job_id": r["job_id"], "status": r["status"], "request": json.loads(r["request"]),
                "result": json.loads(r["result"]) if r["result"] else None, "created_at": r["created_at"],
                "finished_at": r["finished_at"]}

    def jobs(self, scape_id: str, limit: int = 20) -> list[dict]:
        rows = self._db.execute("SELECT job_id, status, request, result, created_at FROM dream_jobs WHERE scape_id=? "
                                "ORDER BY created_at DESC LIMIT ?", (scape_id, max(1, min(limit, 100)))).fetchall()
        out = []
        for r in rows:
            req, res = json.loads(r["request"]), json.loads(r["result"]) if r["result"] else {}
            out.append({"job_id": r["job_id"], "status": r["status"], "problem": req.get("problem"),
                        "mode": req.get("mode", "first"), "created_at": r["created_at"],
                        "winner": (res or {}).get("winner"), "total_ms": (res or {}).get("total_ms")})
        return out

    # -- WebSocket: many jobs at once on one connection ------------------------

    async def ws(self, websocket) -> None:
        from starlette.websockets import WebSocketDisconnect
        await websocket.accept()
        lock, sem = anyio.Lock(), anyio.Semaphore(WS_CONCURRENCY)
        hits: list[float] = []
        state = {"scape": None}

        async def send(obj: dict) -> None:
            async with lock:
                await websocket.send_text(json.dumps(obj, separators=(",", ":"), default=str))

        async def run(ref, req: dict) -> None:
            async with sem:
                async def ev(e: dict) -> None:
                    await send({"ref": ref, **e})
                try:
                    await self.submit(state["scape"], req, on_event=ev)
                except Exception:
                    await send({"ref": ref, "type": "job.failed", "error": "internal error"})

        await send({"type": "hello", "service": "Privi Dream Scape",
                    "send": {"auth": {"type": "auth", "scape_id": "scape_...", "key": "dsk_...", "privi_pass": "ppass_..."},
                             "weave": {"type": "weave", "ref": "your-id", "problem": "balance_lines", "data": {},
                                       "mode": "first|best", "fanout": 3, "hedge_ms": 0}}})
        try:
            async with anyio.create_task_group() as tg:
                try:
                    while True:
                        text = await websocket.receive_text()
                        if len(text) > 256_000:
                            await send({"type": "error", "error": "frame too large"})
                            continue
                        try:
                            m = json.loads(text)
                            assert isinstance(m, dict)
                        except (ValueError, AssertionError):
                            await send({"type": "error", "error": "send JSON objects"})
                            continue
                        if m.get("type") == "auth":
                            if self.gate:
                                g = self.gate(m.get("privi_pass"), "dreamscape_ws")
                                if not g["allowed"]:
                                    state["scape"] = None
                                    await send({"type": "auth", "ok": False, "error": "intercepted by Privi Inspector",
                                                "reasons": g.get("reasons"), "fixes": g.get("fixes")})
                                    continue
                            ok = self.auth(str(m.get("scape_id", "")), str(m.get("key", "")))
                            state["scape"] = str(m["scape_id"]) if ok else None
                            await send({"type": "auth", "ok": ok, **({} if ok else {"error": "wrong scape_id or key"})})
                        elif m.get("type") == "weave":
                            if not state["scape"]:
                                await send({"type": "error", "ref": m.get("ref"), "error": "authenticate first"})
                                continue
                            now = time.monotonic()
                            hits[:] = [h for h in hits if now - h < 60]
                            if len(hits) >= WS_PER_MIN:
                                await send({"type": "error", "ref": m.get("ref"), "error": f"limit {WS_PER_MIN} jobs per minute"})
                                continue
                            hits.append(now)
                            req = {k: m[k] for k in ("problem", "data", "layers", "shots", "mode", "fanout", "hedge_ms",
                                                     "deadline_s", "realms") if k in m}
                            if not isinstance(req.get("data"), dict) or not isinstance(req.get("problem"), str):
                                await send({"type": "error", "ref": m.get("ref"), "error": "weave needs problem and data"})
                                continue
                            tg.start_soon(run, m.get("ref"), req)
                        elif m.get("type") == "directory":
                            await send({"type": "directory", **self.privilege.directory()})
                        else:
                            await send({"type": "error", "error": "unknown frame type; use auth, weave or directory"})
                except (WebSocketDisconnect, RuntimeError):
                    pass
                finally:
                    tg.cancel_scope.cancel()
        except (WebSocketDisconnect, RuntimeError):
            pass
