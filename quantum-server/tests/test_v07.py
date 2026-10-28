# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Quantum - https://priviflow.us - dariocanoy@priviflow.us
"""v0.7: x402 paid tools (with Bazaar discovery and no charge on failure) and signed public benchmarks."""
import anyio
import pytest
from mcp import Client

from privi_quantum import benchmarks, inventory
from privi_quantum.attest import Attestor
from privi_quantum.hardware import HardwareRouter, LocalBackend
from privi_quantum.payments import PaySettings
from privi_quantum.server import BAZAAR_DISCOVERY, Settings, build_server

JOBS = {"jobs": [{"name": f"J{i}", "minutes": m} for i, m in enumerate([42, 17, 33, 8, 25, 61])]}
PAY_TO = "0x1990589FD200E043b8C6FD9ec5956c61b3071048"


class FakeFacilitator:
    def __init__(self):
        self.calls = []

    async def verify(self, payload, req):
        self.calls.append("verify")
        return {"isValid": True}

    async def settle(self, payload, req):
        self.calls.append("settle")
        return {"success": True, "transaction": "0x" + "cd" * 32, "network": req["network"]}


def _paid(tmp_path, scanner=None):
    db = str(tmp_path / "p.db")
    fac = FakeFacilitator()
    pay = PaySettings(payments_enabled=True, pay_to=PAY_TO, cdp_key_id="kid", cdp_key_secret="sec", db_path=db)
    server = build_server(Settings(db_path=db), Attestor(db), None, None, HardwareRouter(db, [LocalBackend()]),
                          scanner, pay_settings=pay, facilitator=fac)
    return server, fac


def _payment(need):
    return {"x402Version": 2, "resource": need["resource"], "accepted": need["accepts"][0], "payload": {}}


def test_pay_settings_from_env(monkeypatch):
    for k in ("QUANTUM_PAY_TO", "QUANTUM_PAYMENTS_ENABLED", "QUANTUM_PRICE_RECEIPT"):
        monkeypatch.delenv(k, raising=False)
    assert PaySettings.from_env().payments_enabled is False          # unconfigured: everything stays free
    monkeypatch.setenv("QUANTUM_PAY_TO", PAY_TO)
    with pytest.raises(ValueError):                                  # mainnet needs CDP keys
        PaySettings.from_env()
    monkeypatch.setenv("CDP_API_KEY_ID", "kid")
    monkeypatch.setenv("CDP_API_KEY_SECRET", "sec")
    monkeypatch.setenv("QUANTUM_PRICE_RECEIPT", "0.5")
    s = PaySettings.from_env()
    assert s.payments_enabled and s.prices_usd["quantum_advantage_receipt"] == "0.5"
    assert s.network["network"] == "eip155:8453"
    monkeypatch.setenv("QUANTUM_PAY_TO", "nope")
    with pytest.raises(ValueError):
        PaySettings.from_env()


def test_paid_receipt_flow_and_bazaar(tmp_path):
    server, fac = _paid(tmp_path)

    async def go():
        async with Client(server) as c:
            pricing = (await c.call_tool("quantum_pricing", {})).structured_content
            assert pricing["payments"].startswith("on") and "$0.25" in pricing["paid_tools"]["quantum_advantage_receipt"]
            # bad input is rejected before any payment is asked for
            bad = await c.call_tool("quantum_advantage_receipt", {"problem": "nope", "data": {}})
            assert bad.is_error and "accepts" not in (bad.structured_content or {})
            need = await c.call_tool("quantum_advantage_receipt", {"problem": "balance_lines", "data": JOBS})
            assert need.is_error
            body = need.structured_content
            assert body["accepts"][0]["amount"] == "250000" and body["accepts"][0]["payTo"] == PAY_TO
            assert body["resource"]["url"].endswith("/mcp")
            assert body["extensions"]["bazaar"]["info"]["input"]["toolName"] == "quantum_advantage_receipt"
            assert fac.calls == []
            ok = await c.call_tool("quantum_advantage_receipt", {"problem": "balance_lines", "data": JOBS},
                                   meta={"x402/payment": _payment(body)})
            assert not ok.is_error, ok
            assert ok.structured_content["verdict"] in ("quantum_won", "classical_won", "tie")
            assert ok.meta["x402/payment-response"]["success"] and fac.calls == ["verify", "settle"]
            # free tools stay free
            assert not (await c.call_tool("quantum_optimize", {"problem": "balance_lines", "data": JOBS})).is_error
            assert not (await c.call_tool("pqc_federal_deadlines", {})).is_error
    anyio.run(go)


def test_failed_paid_call_is_not_charged(tmp_path):
    def broken_scanner(ref):
        raise inventory.InventoryError("repository not found")
    server, fac = _paid(tmp_path, broken_scanner)

    async def go():
        async with Client(server) as c:
            need = (await c.call_tool("pqc_crypto_inventory", {"organization": "Acme", "repos": ["acme/gone"]})).structured_content
            r = await c.call_tool("pqc_crypto_inventory", {"organization": "Acme", "repos": ["acme/gone"]},
                                  meta={"x402/payment": _payment(need)})
            assert r.is_error and "not found" in r.structured_content["error"]
            assert "_no_charge" not in r.structured_content
            assert fac.calls == ["verify"]          # verified, never settled: nothing charged
    anyio.run(go)


def test_payments_off_keeps_tools_free(tmp_path):
    db = str(tmp_path / "f.db")
    server = build_server(Settings(db_path=db), Attestor(db), None, None, HardwareRouter(db, [LocalBackend()]),
                          pay_settings=PaySettings())

    async def go():
        async with Client(server) as c:
            r = await c.call_tool("quantum_advantage_receipt", {"problem": "balance_lines", "data": JOBS})
            assert not r.is_error and r.structured_content["receipt_id"]
            assert "off" in (await c.call_tool("quantum_pricing", {})).structured_content["payments"]
    anyio.run(go)


def test_bazaar_examples_are_valid_inputs():
    """The facilitator calls each tool with its example; it must reach the paywall (valid input), not an input error."""
    from privi_quantum import qaoa
    for tool in ("quantum_advantage_receipt", "quantum_run_hardware"):
        ex = BAZAAR_DISCOVERY[tool]["example"]
        qaoa.build(ex["problem"], ex["data"])
    assert BAZAAR_DISCOVERY["pqc_readiness_package"]["example"]["organization"]
    assert BAZAAR_DISCOVERY["pqc_crypto_inventory"]["example"]["domains"]


def test_demo_route_is_capped_when_payments_on(tmp_path):
    from starlette.testclient import TestClient
    server, _ = _paid(tmp_path)
    app = server.streamable_http_app(host="0.0.0.0", stateless_http=True, json_response=True)
    files = [{"name": f"f{i}.py", "content": "from cryptography.hazmat.primitives.asymmetric import rsa"} for i in range(6)]
    with TestClient(app) as http:
        r = http.post("/api/pqc/package", json={"organization": "Demo", "files": files})
        assert r.status_code == 200
        out = r.json()
        assert "Free demo" in out["demo"] and "left out" in out["demo"]


# ------------------------------------------------------------------ benchmarks

SMALL = [{"id": "balance_lines-6", "problem": "balance_lines", "data": JOBS, "story": "six jobs"},
         {"id": "select_lots-6", "problem": "select_lots", "story": "pick 2 of 6",
          "data": {"lots": [{"name": f"L{i}", "risk": r} for i, r in enumerate([0.9, 0.2, 0.7, 0.4, 0.8, 0.1])], "k": 2}}]


def test_suite_is_fixed_and_in_range():
    a, b = benchmarks.suite_cases(), benchmarks.suite_cases()
    assert a == b and len(a) == 9
    from privi_quantum import qaoa
    sizes = [qaoa.build(c["problem"], c["data"])[0].n for c in a]
    assert min(sizes) >= 6 and max(sizes) <= qaoa.MAX_QUBITS


def test_benchmark_run_signed_and_published(tmp_path):
    from starlette.testclient import TestClient
    db = str(tmp_path / "b.db")
    att = Attestor(db)
    server = build_server(Settings(db_path=db), att, None, None, HardwareRouter(db, [LocalBackend()]),
                          pay_settings=PaySettings())
    bench = server._benchmarks
    out = bench.run(SMALL)
    assert out["summary"]["problems"] == 2 and out["attestation_id"]
    for r in out["results"]:
        assert r["verdict"] in ("quantum_won", "classical_won", "tie")
        assert r["lift_over_random"] and r["lift_over_random"] > 1      # trained circuit beats random guessing
        assert r["exhaustive"]["cost"] <= r["quantum"]["cost"] + 1e-9
    assert att.get(out["attestation_id"])["body"]["kind"] == "benchmark_suite"
    assert bench.latest()["attestation_id"] == out["attestation_id"] and bench.age_s() < 60

    async def go():
        async with Client(server) as c:
            rep = (await c.call_tool("quantum_benchmarks", {})).structured_content
            assert rep["suite"]["attestation_id"] == out["attestation_id"] and rep["page"].endswith("/benchmarks")
            v = (await c.call_tool("quantum_verify", {"attestation_id": out["attestation_id"]})).structured_content
            assert v.get("valid") or v.get("verified") or v.get("signatures_valid"), v
    anyio.run(go)

    app = server.streamable_http_app(host="0.0.0.0", stateless_http=True, json_response=True)
    with TestClient(app) as http:
        page = http.get("/benchmarks")
        assert page.status_code == 200 and "balance_lines-6" in page.text and "whichever side wins" in page.text
        assert http.get("/benchmarks.json").json()["suite"]["summary"]["problems"] == 2
        assert http.post("/benchmarks/run").status_code == 401
