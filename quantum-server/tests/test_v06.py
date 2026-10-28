# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Quantum - https://priviflow.us - dariocanoy@priviflow.us
"""v0.6: Quantum Advantage Receipts, hardware routing, crypto inventory, Privi Vault."""
import io
import json
import tarfile

import anyio
import numpy as np
import pytest
from mcp import Client

from privi_quantum import advantage, hardware, inventory, qaoa, vault
from privi_quantum.attest import Attestor
from privi_quantum.hardware import Backend, HardwareError, HardwareRouter, IonQBackend, LocalBackend
from privi_quantum.server import Settings, build_server

JOBS = {"jobs": [{"name": f"J{i}", "minutes": m} for i, m in enumerate([42, 17, 33, 8, 25, 61, 12, 29])]}


class FakeAnchor:
    def anchor(self, hashes, label):
        return {"status": "confirmed", "tx_hash": "0x" + "ab" * 32, "merkle_root": "00" * 32, "chain_id": 8453,
                "receipts": [{"hash": h, "proof": []} for h in hashes]}

    def verify(self, *a):
        return {"verified": True}


# ------------------------------------------------------------------ advantage

@pytest.mark.parametrize("problem,data", [
    ("balance_lines", JOBS),
    ("select_lots", {"lots": [{"name": f"L{i}", "risk": r} for i, r in enumerate([5, 1, 9, 3, 7, 2, 8])], "k": 3,
                     "linked": [["L2", "L6"]]}),
    ("split_conflicts", {"items": list("ABCDEF"), "conflicts": [{"a": "A", "b": "B", "weight": 3}, {"a": "B", "b": "C"},
                                                                  {"a": "C", "b": "D", "weight": 2}, {"a": "E", "b": "F"},
                                                                  {"a": "A", "b": "F", "weight": 2}]}),
])
def test_classical_baselines_reach_optimum(problem, data):
    q, _ = qaoa.build(problem, data)
    ex, sa = advantage.exhaustive(q), advantage.simulated_annealing(q)
    assert ex["cost"] == pytest.approx(float(q.all_costs().min()))
    assert sa["cost"] == pytest.approx(ex["cost"]) and q.cost(sa["solution"]) == pytest.approx(sa["cost"])


def test_verdict_rules():
    cl = [{"method": "exhaustive", "cost": 4.0, "runtime_ms": 5.0}, {"method": "simulated_annealing", "cost": 4.0, "runtime_ms": 2.0}]
    assert advantage.verdict({"cost": 5.0, "runtime_ms": 1.0}, cl)["verdict"] == "classical_won"
    assert advantage.verdict({"cost": 3.0, "runtime_ms": 99.0}, cl)["verdict"] == "quantum_won"
    assert advantage.verdict({"cost": 4.0, "runtime_ms": 1.0}, cl)["verdict"] == "quantum_won"
    v = advantage.verdict({"cost": 4.0, "runtime_ms": 3.0}, cl)
    assert v["verdict"] == "classical_won" and "simulated_annealing" in v["why"]


def test_best_from_counts():
    q, _ = qaoa.build("balance_lines", JOBS)
    costs = q.all_costs()
    opt, bad = int(np.argmin(costs)), int(np.argmax(costs))
    m = advantage.best_from_counts(q, {opt: 3, bad: 7})
    assert m["found_optimum"] and m["optimum_frequency"] == pytest.approx(0.3) and m["shots"] == 10


# ------------------------------------------------------------------ hardware

def _trained_qasm():
    q, _ = qaoa.build("balance_lines", JOBS)
    r = qaoa.solve(q, layers=1, shots=64, seed=1)
    nm = r["cost_normalization"]
    return q, r, qaoa.to_qasm(q, r["angles"]["gamma"], r["angles"]["beta"], nm["min"], nm["span"])


def test_parse_and_simulate_match_qaoa():
    q, r, qasm = _trained_qasm()
    n, gates = hardware.parse_qasm(qasm)
    nm = r["cost_normalization"]
    psi = qaoa.qaoa_state((q.all_costs() - nm["min"]) / nm["span"], r["angles"]["gamma"], r["angles"]["beta"], n)
    assert n == q.n and np.allclose(hardware.simulate(gates, n), np.abs(psi) ** 2, atol=1e-9)
    ion = hardware.to_ionq(gates)
    assert {"gate": "h", "target": 0} in ion and any(g["gate"] == "cnot" and "control" in g for g in ion)
    q3 = hardware.to_qasm3(gates, n)
    assert q3.startswith("OPENQASM 3.0;") and f"c[{n - 1}] = measure q[{n - 1}];" in q3
    with pytest.raises(HardwareError):
        hardware.parse_qasm("OPENQASM 2.0;\nqreg q[2];\nccx q[0],q[1],q[2];")


def test_bit_order_helpers():
    # k = 0b011: qubits 0 and 1 measured 1
    assert hardware.counts_from_bitstrings({"011": 5}, qubit0_first=False) == {3: 5}      # IBM: c[n-1]..c[0]
    assert hardware.counts_from_bitstrings({"110": 5}, qubit0_first=True) == {3: 5}       # Braket: qubit 0 first
    assert hardware.counts_from_probs({"3": 0.75, "0": 0.25}, 100) == {3: 75, 0: 25}


class FakeIonQ:
    """Stand-in for api.ionq.co: job queued on first poll, completed on the second."""
    def __init__(self, n):
        self.n, self.polls, self.sent = n, 0, None

    def __call__(self, req, timeout=30):
        url, body = req.full_url, req.data
        assert req.headers["Authorization"] == "apiKey k123"
        if req.get_method() == "POST":
            self.sent = json.loads(body)
            out = {"id": "ionq-job-1", "status": "submitted"}
        elif url.endswith("/results/probabilities"):
            out = {"0": 0.5, str(2 ** self.n - 1): 0.5}
        else:
            self.polls += 1
            out = {"id": "ionq-job-1", "status": "ready" if self.polls == 1 else "completed"}
        return _Resp(json.dumps(out))


class _Resp(io.BytesIO):
    def __init__(self, text):
        super().__init__(text.encode())

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_ionq_backend_round_trip():
    q, r, qasm = _trained_qasm()
    n, gates = hardware.parse_qasm(qasm)
    fake = FakeIonQ(n)
    b = IonQBackend("k123", "simulator", None, opener=fake)
    pid = b.submit(qasm, n, gates, 200, "privi balance_lines hw_1")
    assert pid == "ionq-job-1" and fake.sent["type"] == "ionq.circuit.v1" and fake.sent["backend"] == "simulator"
    assert fake.sent["input"]["gateset"] == "qis" and fake.sent["input"]["qubits"] == n and fake.sent["shots"] == 200
    assert b.fetch(pid, n, 200)["status"] == "queued"
    done = b.fetch(pid, n, 200)
    assert done["status"] == "done" and done["counts"] == {0: 100, 2 ** n - 1: 100}


class PaidQPU(Backend):
    id, provider, name, kind = "fake:qpu", "Fake", "Fake QPU", "qpu"

    def submit(self, qasm, n, gates, shots, name):
        return "p1"

    def fetch(self, pid, n, shots):
        return {"status": "done", "counts": {0: shots}}


def test_money_guard_and_routing(tmp_path):
    db = str(tmp_path / "h.db")
    unknown = HardwareRouter(db, [LocalBackend(), PaidQPU(None)], daily_budget_usd=10)
    with pytest.raises(HardwareError, match="unknown"):
        unknown.choose("fake:qpu", "cheapest", 100, None)
    r = HardwareRouter(db, [LocalBackend(), PaidQPU({"per_task": 1.0, "per_shot": 0.01})], daily_budget_usd=0)
    with pytest.raises(HardwareError, match="HARDWARE_DAILY_BUDGET_USD"):
        r.choose("fake:qpu", "cheapest", 100, None)
    b, est, _ = r.choose("auto", "cheapest", 100, None)
    assert b.id == "local" and est == 0
    with pytest.raises(HardwareError, match="no real quantum hardware"):
        r.choose("auto", "hardware", 100, None)
    r = HardwareRouter(db, [LocalBackend(), PaidQPU({"per_task": 1.0, "per_shot": 0.01})], daily_budget_usd=3)
    b, est, considered = r.choose("auto", "hardware", 100, None)
    assert b.id == "fake:qpu" and est == 2.0 and any(c["chosen"] for c in considered)
    with pytest.raises(HardwareError, match="max_cost_usd"):
        r.choose("auto", "hardware", 100, 1.5)
    _, _, qasm = _trained_qasm()
    r.submit("balance_lines", JOBS, qasm, 100, 1, {}, "fake:qpu")
    assert r.spent_today() == 2.0
    with pytest.raises(HardwareError, match="budget"):
        r.choose("fake:qpu", "cheapest", 100, None)   # 2 more would exceed the $3 day


# ------------------------------------------------------------------ inventory

def _tarball(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, text in files.items():
            data = text.encode()
            ti = tarfile.TarInfo(f"acme-api-1a2b3c/{name}")
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
        link = tarfile.TarInfo("acme-api-1a2b3c/evil")
        link.type, link.linkname = tarfile.SYMTYPE, "/etc/passwd"
        tf.addfile(link)
    return buf.getvalue()


def test_repo_parsing_and_tarball_scan():
    assert inventory.parse_repo("https://github.com/acme/api") == ("acme", "api", "")
    assert inventory.parse_repo("https://github.com/acme/api/tree/main") == ("acme", "api", "main")
    for bad in ("https://gitlab.com/acme/api", "http://169.254.169.254/latest", "../x", ""):
        with pytest.raises(inventory.InventoryError):
            inventory.parse_repo(bad)
    rep = inventory.scan_tarball(_tarball({"auth.py": "k = rsa.generate_private_key(public_exponent=65537, key_size=2048)",
                                           "node_modules/x.js": "RSA", "logo.png": "RSA", "ok.py": "print(1)"}),
                                 "github.com/acme/api")
    assert rep["files_scanned"] == 2 and rep["counts"]["HIGH"] == 1 and rep["findings"][0]["path"] == "auth.py"


def test_crypto_inventory_tool(tmp_path):
    from starlette.testclient import TestClient
    blob = _tarball({"tls.go": 'cfg.CurvePreferences = []tls.CurveID{tls.X25519} // ECDHE', "sign.py": "alg='RS256'"})
    scanned = []

    def repo_scanner(ref):
        scanned.append(ref)
        return inventory.scan_tarball(blob, "github.com/acme/api")

    def checker(hosts):
        return {"summary": {"checked": len(hosts), "pq_hybrid": 0},
                "results": [{"host": h, "asset": {"system": h, "asset": f"{h}:443", "algorithm": "ECDHE X25519",
                                                  "usage": "tls", "protocol": "TLS 1.2"}} for h in hosts]}
    att = Attestor(str(tmp_path / "i.db"))
    server = build_server(Settings(db_path=str(tmp_path / "i.db")), att, FakeAnchor(), checker,
                          HardwareRouter(str(tmp_path / "i.db"), [LocalBackend()]), repo_scanner)

    async def go():
        async with Client(server) as c:
            r = await c.call_tool("pqc_crypto_inventory", {"organization": "Acme Tool & Die", "domains": ["www.acme.com"],
                                                           "repos": ["acme/api"], "long_lived_data": True})
            assert not r.is_error, r
            out = r.structured_content
            assert scanned == ["acme/api"] and out["repositories"][0]["files_scanned"] == 2
            assert out["summary"]["assets"] >= 3 and out["summary"]["by_priority"]["P1"] >= 1
            assert out["endpoint_check"]["checked"] == 1 and out["cbom_url"].endswith(".cbom.json")
            assert (await c.call_tool("pqc_crypto_inventory", {"organization": "X"})).is_error
            return out["package_id"]
    aid = anyio.run(go)
    body = att.get(aid)["body"]["package_body"]
    assert body["profile"] == "company" and all("NIST" in m["source"] for m in body["milestones"])
    app = server.streamable_http_app(host="0.0.0.0", stateless_http=True, json_response=True)
    with TestClient(app) as http:
        assert http.get(f"/reports/{aid}").status_code == 200
        assert http.get(f"/reports/{aid}.cbom.json").json()["specVersion"] == "1.6"


# ------------------------------------------------------------------ vault

def test_vault_round_trip_and_tamper(tmp_path):
    for suite in vault.SUITES:
        kp = vault.keygen(suite)
        env = vault.seal(b"\x00\x01 contract", kp["public_key"], "c")
        assert vault.open_(env, kp["private_key"]) == b"\x00\x01 contract"
        assert "contract" not in json.dumps(env)
        for field in ("label", "ciphertext"):
            bad = dict(env)
            bad[field] = "x" if field == "label" else vault.b64e(b"\x00" * 40)
            with pytest.raises(vault.VaultError):
                vault.open_(bad, kp["private_key"])
        other = vault.keygen(suite)
        with pytest.raises(vault.VaultError, match="recipient"):
            vault.open_(env, other["private_key"])
    pk = vault.keygen()["public_key"]
    pk["key_id"] = "pvk_wrong"
    with pytest.raises(vault.VaultError):
        vault.seal(b"x", pk)
    # local CLI
    keyf, pubf, src, envf, out = (tmp_path / n for n in ("k.json", "p.json", "a.txt", "e.json", "o.txt"))
    src.write_text("trade secret")
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert vault.main(["keygen", "--out", str(keyf)]) == 0
    pubf.write_text(buf.getvalue())
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert vault.main(["seal", str(src), "--public-key", str(pubf)]) == 0
    envf.write_text(buf.getvalue())
    assert vault.main(["open", str(envf), "--private-key", str(keyf), "--out", str(out)]) == 0
    assert out.read_text() == "trade secret"


# ------------------------------------------------------------------ MCP end to end

def test_mcp_receipts_hardware_and_vault(tmp_path):
    from starlette.testclient import TestClient
    db = str(tmp_path / "m.db")
    att = Attestor(db)
    q, _, _ = _trained_qasm()
    fake = FakeIonQ(q.n)
    router = HardwareRouter(db, [LocalBackend(), IonQBackend("k123", "simulator", None, opener=fake)])
    server = build_server(Settings(db_path=db), att, FakeAnchor(), None, router)

    async def go():
        async with Client(server) as c:
            r = (await c.call_tool("quantum_advantage_receipt", {"problem": "balance_lines", "data": JOBS})).structured_content
            assert r["verdict"] in advantage.VERDICTS and {x["method"] for x in r["classical"]} == {"exhaustive", "simulated_annealing"}
            receipt = r["receipt_id"]
            bk = (await c.call_tool("quantum_backends", {})).structured_content
            assert {b["id"] for b in bk["backends"]} == {"local", "ionq:simulator"}
            # auto + cheapest prefers the real provider's free simulator over this server
            j = (await c.call_tool("quantum_run_hardware", {"problem": "balance_lines", "data": JOBS, "shots": 200})).structured_content
            assert j["backend"] == "ionq:simulator" and j["status"] == "queued" and fake.sent["shots"] == 200
            done = (await c.call_tool("quantum_hardware_job", {"job_id": j["job_id"]})).structured_content
            assert done["status"] == "done" and done["advantage_receipt"]["quantum"]["backend"] == "ionq:simulator"
            again = (await c.call_tool("quantum_hardware_job", {"job_id": j["job_id"]})).structured_content
            assert again["advantage_receipt"]["receipt_id"] == done["advantage_receipt"]["receipt_id"]  # sealed once
            loc = (await c.call_tool("quantum_run_hardware", {"problem": "balance_lines", "data": JOBS, "backend": "local"})).structured_content
            assert loc["status"] == "done" and loc["measurement"]["shots"] == 1000 and loc["attestation"]["id"]
            assert (await c.call_tool("quantum_run_hardware", {"problem": "balance_lines", "data": JOBS, "policy": "hardware"})).is_error
            assert (await c.call_tool("quantum_hardware_job", {"job_id": "hw_nope"})).is_error
            kp = (await c.call_tool("vault_keygen", {})).structured_content
            s = (await c.call_tool("vault_seal", {"public_key": kp["public_key"], "text": "merger terms", "label": "deal"})).structured_content
            assert s["protection_receipt"]["receipt_id"] and s["envelope"]["suite"] == vault.DEFAULT_SUITE
            o = (await c.call_tool("vault_open", {"envelope": s["envelope"], "private_key": kp["private_key"]})).structured_content
            assert o["text"] == "merger terms"
            rr = (await c.call_tool("vault_receipt", {"envelope_sha256": "ab" * 32, "label": "local"})).structured_content
            assert rr["envelope_sha256"] == "ab" * 32
            assert (await c.call_tool("vault_receipt", {"envelope_sha256": "zz"})).is_error
            st = (await c.call_tool("quantum_status", {})).structured_content
            assert st["version"] == "0.8.0" and st["backends"]["local"] == "ready"
            return receipt
    receipt = anyio.run(go)
    assert att.get(receipt)["body"]["kind"] == "advantage_receipt"
    app = server.streamable_http_app(host="0.0.0.0", stateless_http=True, json_response=True)
    with TestClient(app) as http:
        page = http.get(f"/receipts/{receipt}")
        assert page.status_code == 200 and "Quantum Advantage Receipt" in page.text and "valid" in page.text
        assert http.get(f"/receipts/{receipt}.json").json()["id"] == receipt
        assert http.get("/receipts/qa_nope").status_code == 404


def test_explorer_feed_hides_ids_and_bodies(tmp_path):
    """Privi Explorer: the public feed shows kind, time and hash only; lookups by hash never reveal the id."""
    from starlette.testclient import TestClient
    db = str(tmp_path / "x.db")
    att = Attestor(db)
    server = build_server(Settings(db_path=db), att, FakeAnchor(), None, None)

    async def go():
        async with Client(server) as c:
            r = (await c.call_tool("quantum_advantage_receipt", {"problem": "balance_lines", "data": JOBS})).structured_content
            return r["receipt_id"]
    rid = anyio.run(go)
    full = att.get(rid)
    att.set_anchor(rid, {"chain_id": 8453, "tx_hash": "0x" + "cd" * 32, "merkle_root": "11" * 32, "proof": ["22" * 32],
                         "status": "confirmed", "block_number": 7, "block_time": 1, "network": "Base"})
    app = server.streamable_http_app(host="0.0.0.0", stateless_http=True, json_response=True)
    with TestClient(app) as http:
        feed = http.get("/explorer/recent")
        assert feed.headers["access-control-allow-origin"] == "*"
        body = feed.json()
        assert body["total"] >= 1 and body["by_kind"]["advantage_receipt"] >= 1
        row = next(a for a in body["attestations"] if a["body_sha256"] == full["body_sha256"])
        assert row["kind"] == "advantage_receipt" and row["anchor"]["tx_hash"] == "0x" + "cd" * 32
        assert rid not in feed.text and "balance_lines" not in feed.text and "proof" not in row["anchor"]
        by_hash = http.get("/explorer/lookup", params={"q": full["body_sha256"]}).json()
        assert by_hash["found"] and by_hash["signatures"]["valid"] is True and rid not in json.dumps(by_hash)
        by_id = http.get("/explorer/lookup", params={"q": rid}).json()
        assert by_id["id"] == rid and by_id["page"].endswith(f"/receipts/{rid}") and by_id["verdict"] in advantage.VERDICTS
        assert http.get("/explorer/lookup", params={"q": "qa_nope"}).status_code == 404
        assert http.get("/explorer/lookup", params={"q": "zz"}).status_code == 404
