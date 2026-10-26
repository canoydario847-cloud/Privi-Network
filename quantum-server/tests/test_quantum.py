# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Quantum - https://priviflow.us - dariocanoy@priviflow.us
import copy
import re

import anyio
import numpy as np
import pytest
from mcp import Client

from privi_quantum import qaoa
from privi_quantum.anchoring import anchor_pending
from privi_quantum.attest import Attestor
from privi_quantum.server import Settings, build_server

JOBS = {"jobs": [{"name": f"J{i}", "minutes": m} for i, m in enumerate([42, 17, 33, 8, 25, 61, 12, 29, 50, 21])]}


class FakeAnchor:
    def __init__(self):
        self.anchored = {}

    def anchor(self, hashes, label):
        self.anchored.update({h: "0x" + "ab" * 32 for h in hashes})
        return {"status": "confirmed", "tx_hash": "0x" + "ab" * 32, "merkle_root": "00" * 32, "chain_id": 262144,
                "network": "test", "block_number": 7, "block_time": 1,
                "receipts": [{"hash": h, "proof": []} for h in hashes]}

    def verify(self, hash_hex, tx_hash, proof):
        return {"verified": hash_hex in self.anchored, "block_number": 7, "chain_id": 262144}


def _sim_qasm(qasm, n):
    """Independent gate-by-gate simulator used to check the exported circuit."""
    t = np.zeros(2 ** n, complex); t[0] = 1; t = t.reshape([2] * n)
    ax = lambda q: n - 1 - q

    def one(U, q):
        nonlocal t
        t = np.moveaxis(np.tensordot(U, t, axes=([1], [ax(q)])), 0, ax(q))
    for line in qasm.splitlines():
        m = re.match(r"(h|rz|rx|cx)(?:\((.*)\))? q\[(\d+)\](?:,q\[(\d+)\])?;", line)
        if not m:
            continue
        g, a, q1, q2 = m.groups(); q1 = int(q1)
        if g == "h":
            one(np.array([[1, 1], [1, -1]]) / np.sqrt(2), q1)
        elif g == "rz":
            th = float(a); one(np.diag([np.exp(-1j * th / 2), np.exp(1j * th / 2)]), q1)
        elif g == "rx":
            th = float(a); c, s = np.cos(th / 2), -1j * np.sin(th / 2); one(np.array([[c, s], [s, c]]), q1)
        else:
            q2 = int(q2); idx = [slice(None)] * n; idx[ax(q1)] = 1
            rem = [k for k in range(n) if k != ax(q1)]
            t[tuple(idx)] = np.flip(t[tuple(idx)], axis=rem.index(ax(q2))).copy()
    return np.abs(t.reshape(-1)) ** 2


def test_ising_matches_qubo():
    rng = np.random.default_rng(0)
    for n in (1, 2, 5, 8):
        q = qaoa.Qubo(rng.normal(size=(n, n)), 1.5)
        h, J, c = q.ising()
        Z = 1 - 2 * q.bits()
        e = Z @ h + sum(w * Z[:, i] * Z[:, j] for (i, j), w in J.items()) + c
        assert np.allclose(e, q.all_costs())


def test_qasm_reproduces_statevector():
    rng = np.random.default_rng(1)
    q = qaoa.Qubo(rng.normal(size=(5, 5)))
    c = q.all_costs(); cmin, span = c.min(), c.max() - c.min()
    g, b = [0.7, 1.3], [0.4, 0.2]
    direct = np.abs(qaoa.qaoa_state((c - cmin) / span, g, b, 5)) ** 2
    assert np.allclose(direct, _sim_qasm(qaoa.to_qasm(q, g, b, cmin, span), 5), atol=1e-9)


@pytest.mark.parametrize("problem,data", [
    ("balance_lines", JOBS),
    ("select_lots", {"lots": [{"name": f"L{i}", "risk": r} for i, r in enumerate([0.9, 0.2, 0.75, 0.4, 0.85, 0.1])],
                     "k": 2, "linked": [["L0", "L4"]]}),
    ("split_conflicts", {"items": list("ABCDEF"), "conflicts": [
        {"a": "A", "b": "B", "weight": 3}, {"a": "B", "b": "C"}, {"a": "C", "b": "D", "weight": 2},
        {"a": "D", "b": "E"}, {"a": "E", "b": "F", "weight": 2}, {"a": "F", "b": "A"}]}),
])
def test_templates_reach_the_optimum(problem, data):
    qubo, decode = qaoa.build(problem, data)
    r = qaoa.solve(qubo, layers=2, seed=3)
    assert r["found_optimum"] and r["approximation_ratio"] == 1.0
    assert r["probability_of_optimum"] > r["random_guess_probability_of_optimum"]
    d = decode(r["solution"])
    if problem == "select_lots":
        assert d["meets_k"] and d["linked_pairs_both_chosen"] == [] and set(d["inspect"]) == {"L0", "L2"}
    if problem == "balance_lines":
        assert d["imbalance_minutes"] == 0.0


def test_bad_input_is_rejected():
    for problem, data in [("nope", {}), ("balance_lines", {"jobs": [{"minutes": 1}]}),
                          ("balance_lines", {"jobs": [{"minutes": 1}] * 17}),
                          ("qubo", {"Q": [[1, 2], [3]]}), ("qubo", {"Q": [[float("nan")]]}),
                          ("select_lots", {"lots": [{"risk": 1}, {"risk": 2}], "k": 5})]:
        with pytest.raises(qaoa.ProblemError):
            qaoa.build(problem, data)


def test_attestation_signatures_and_tamper(tmp_path):
    a = Attestor(str(tmp_path / "q.db"))
    k = a.public_keys()
    att = a.issue("t", {"x": 1})
    assert Attestor.verify(att, k["ed25519"], k["ml_dsa_87"])["valid"]
    bad = copy.deepcopy(att); bad["body"]["x"] = 2
    assert not Attestor.verify(bad, k["ed25519"], k["ml_dsa_87"])["valid"]
    half = copy.deepcopy(att); half["signatures"]["ml_dsa_87"] = att["signatures"]["ed25519"]
    v = Attestor.verify(half, k["ed25519"], k["ml_dsa_87"])
    assert v["ed25519_valid"] and not v["ml_dsa_87_valid"] and not v["valid"]
    assert Attestor(str(tmp_path / "q.db")).key_id == a.key_id  # key survives restart


def test_mcp_end_to_end(tmp_path):
    anchor = FakeAnchor()
    attestor = Attestor(str(tmp_path / "q.db"))

    async def go():
        async with Client(build_server(Settings(db_path=str(tmp_path / "q.db")), attestor, anchor)) as c:
            st = (await c.call_tool("quantum_status", {})).structured_content
            assert st["max_qubits"] == qaoa.MAX_QUBITS and st["anchoring"]["enabled"]
            pr = (await c.call_tool("quantum_problems", {})).structured_content
            assert "balance_lines" in pr["problems"]
            r = (await c.call_tool("quantum_optimize", {"problem": "balance_lines", "data": JOBS,
                                                        "include_qasm": True})).structured_content
            assert r["quality"]["found_optimum"] and r["openqasm"].startswith("OPENQASM 2.0;")
            aid = r["attestation"]["id"]
            v = (await c.call_tool("quantum_verify", {"attestation_id": aid})).structured_content
            assert v["valid"] and v["anchor"]["verified"] is False
            assert anchor_pending(attestor, anchor) == 1
            v = (await c.call_tool("quantum_verify", {"attestation_id": aid})).structured_content
            assert v["valid"] and v["anchor"]["verified"] is True
            forged = attestor.get(aid); forged["body"]["decision"]["imbalance_minutes"] = 99
            v = (await c.call_tool("quantum_verify", {"attestation": forged})).structured_content
            assert not v["valid"]
            s = (await c.call_tool("pqc_scan_code", {"code": "k = rsa.generate_private_key(public_exponent=65537, key_size=2048)"})).structured_content
            assert s["counts"]["HIGH"] == 1 and s["readiness_score"] < 100
            e = await c.call_tool("quantum_optimize", {"problem": "qubo", "data": {"Q": [[0] * 17] * 17}})
            assert e.is_error
    anyio.run(go)


# ---------------------------------------------------------------- government readiness packages

from datetime import date  # noqa: E402

from privi_quantum import govpqc  # noqa: E402


@pytest.mark.parametrize("alg,cls", [
    ("RSA-2048", "quantum_vulnerable"), ("TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256", "quantum_vulnerable"),
    ("X25519+ML-KEM-768", "hybrid"), ("ML-DSA-87", "post_quantum"), ("ML-DSA-65", "post_quantum"),
    ("SLH-DSA-SHA2-128s", "post_quantum"), ("DSA-2048", "quantum_vulnerable"), ("Ed25519", "quantum_vulnerable"),
    ("SHA-1", "broken"), ("MD5", "broken"), ("AES-256-GCM", "symmetric_ok"), ("AES-128-GCM", "symmetric_weakened"),
    ("SHA-384", "symmetric_ok"), ("LMS", "post_quantum"), ("mystery-cipher", "unknown"),
])
def test_gov_classify(alg, cls):
    assert govpqc.classify(alg)["class"] == cls


def test_gov_deadlines_and_priorities():
    today = date(2026, 10, 26)
    hva_ke = govpqc.assess_asset({"system": "a", "algorithm": "RSA-2048", "usage": "key_establishment", "hva": True}, "agency", today)
    assert hva_ke["priority"] == "P1" and hva_ke["deadline"] == "2030-12-31"
    hva_sig = govpqc.assess_asset({"system": "a", "algorithm": "ECDSA P-256", "usage": "signature", "impact": "high"}, "agency", today)
    assert hva_sig["deadline"] == "2030-12-31"  # NIST IR 8547 draft deprecation comes before the 2031 signature date
    assert any(d["date"] == "2031-12-31" for d in hva_sig["deadlines"])
    low = govpqc.assess_asset({"system": "b", "algorithm": "RSA-2048", "impact": "low"}, "agency", today)
    assert low["priority"] == "P2" and any(d["date"] == "2035-12-31" for d in low["deadlines"])
    tls = govpqc.assess_asset({"system": "w", "algorithm": "ECDSA P-256", "usage": "tls", "protocol": "TLS 1.2"}, "agency", today)
    assert tls["deadline"] == "2030-01-02" and "TLS 1.3" in tls["action"]
    broken = govpqc.assess_asset({"system": "c", "algorithm": "MD5", "usage": "hash"}, "agency", today)
    assert broken["priority"] == "P1" and broken["deadline"] == "2026-10-26" and broken["action"].startswith("Replace now")
    done = govpqc.assess_asset({"system": "d", "algorithm": "X25519+ML-KEM-768", "usage": "vpn", "protocol": "TLS 1.3"}, "agency", today)
    assert done["priority"] == "P4 done" and done["deadline"] is None
    nss = govpqc.assess_asset({"system": "e", "algorithm": "RSA-3072", "usage": "code_signing"}, "nss_vendor", today)
    assert nss["deadline"] == "2030-12-31" and "CNSA 2.0" in nss["deadlines"][0]["rule"]
    assert "LMS/XMSS" in nss["action"]


def test_gov_package_cbom_and_plan_elements():
    pkg = govpqc.build_package({"name": "Dept of Example", "pqc_lead": "J. Smith"}, [
        {"system": "Benefits", "algorithm": "RSA-2048", "usage": "tls", "protocol": "TLS 1.2", "impact": "high", "hva": True, "vendor": "V"},
        {"system": "Payroll", "algorithm": "X25519+ML-KEM-768", "usage": "vpn", "protocol": "TLS 1.3"},
    ], "agency", today=date(2026, 10, 26))
    assert pkg["summary"]["by_priority"]["P1"] == 1 and pkg["summary"]["pqc_ready_percent"] == 50
    els = {e["name"]: e["status"] for e in pkg["plan_elements"]}
    assert len(els) == 9 and els["Governance"] == "evidence" and els["Resource estimates"] == "gap"
    bom = pkg["cbom"]
    assert bom["bomFormat"] == "CycloneDX" and bom["specVersion"] == "1.6" and len(bom["components"]) == 2
    assert all(c["type"] == "cryptographic-asset" for c in bom["components"])
    assert bom["components"][1]["cryptoProperties"]["algorithmProperties"]["nistQuantumSecurityLevel"] == 0 or \
        bom["components"][0]["cryptoProperties"]["algorithmProperties"]["nistQuantumSecurityLevel"] == 0
    c = govpqc.build_package({"name": "Acme"}, [{"algorithm": "RSA-2048"}], "contractor")
    assert c["plan_elements"] is None and c["contractor_readiness"][0]["status"] == "action_needed"


def test_gov_package_tool_report_and_api(tmp_path):
    from starlette.testclient import TestClient
    anchor = FakeAnchor()
    attestor = Attestor(str(tmp_path / "g.db"))
    server = build_server(Settings(db_path=str(tmp_path / "g.db")), attestor, anchor)

    async def go():
        async with Client(server) as c:
            dl = (await c.call_tool("pqc_federal_deadlines", {})).structured_content
            assert any(t["source"] == "OMB M-26-15" for t in dl["timeline"]) and len(dl["cnsa_2_0"]) == 6
            r = await c.call_tool("pqc_readiness_package", {
                "organization": "Dept of Example", "pqc_lead": "J. Smith", "system_name": "Benefits portal",
                "impact": "high", "hva": True,
                "files": [{"name": "auth.py", "content": "k = rsa.generate_private_key(public_exponent=65537, key_size=2048)\nalg='RS256'"}],
                "assets": [{"system": "Website", "algorithm": "ECDSA P-256", "usage": "tls", "protocol": "TLS 1.2"}]})
            assert not r.is_error, r
            out = r.structured_content
            assert out["summary"]["assets"] == 3 and out["summary"]["by_priority"]["P1"] == 2
            assert out["report_url"].endswith(out["package_id"]) and len(out["plan_elements"]) == 9
            empty = await c.call_tool("pqc_readiness_package", {"organization": "X"})
            assert empty.is_error
            return out["package_id"]
    aid = anyio.run(go)
    att = attestor.get(aid)
    assert Attestor.verify(att, *[attestor.public_keys()[k] for k in ("ed25519", "ml_dsa_87")])["valid"]
    assert anchor_pending(attestor, anchor) == 1

    app = server.streamable_http_app(host="0.0.0.0", stateless_http=True, json_response=True)
    with TestClient(app) as http:
        page = http.get(f"/reports/{aid}")
        assert page.status_code == 200 and "Dept of Example" in page.text and "valid" in page.text and "Anchored" in page.text
        bom = http.get(f"/reports/{aid}.cbom.json")
        assert bom.status_code == 200 and bom.json()["specVersion"] == "1.6"
        assert http.get(f"/reports/{aid}.json").json()["id"] == aid
        assert http.get("/reports/qa_nope").status_code == 404
        pre = http.options("/api/pqc/package")
        assert pre.headers["access-control-allow-origin"] == "*"
        api = http.post("/api/pqc/package", json={"organization": "Demo", "profile": "contractor",
                                                  "assets": [{"algorithm": "RSA-2048", "usage": "tls"}]})
        assert api.status_code == 200 and api.json()["contractor_readiness"]
        bad = http.post("/api/pqc/package", json={"organization": "Demo"})
        assert bad.status_code == 400
        assert http.get("/api/pqc/deadlines").json()["timeline"]
