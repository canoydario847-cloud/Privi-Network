# Copyright (c) 2026 Privi World Co. All rights reserved.
"""Privi Quantum Toolkit: certificate check, harvest risk, size impact, circuit stats, supplier score."""
from datetime import datetime, timedelta, timezone

import anyio
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import NameOID
from mcp import Client

from privi_quantum import toolkit
from privi_quantum.attest import Attestor
from privi_quantum.payments import DEFAULT_PRICES_USD, PaySettings
from privi_quantum.server import Settings, build_server


def _cert(key, cn, years):
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    now = datetime.now(timezone.utc)
    c = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
         .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
         .not_valid_after(now + timedelta(days=365 * years)).sign(key, hashes.SHA256()))
    return c.public_bytes(serialization.Encoding.PEM).decode()


def test_certificate_check():
    short = _cert(ec.generate_private_key(ec.SECP256R1()), "short.example", 1)
    long_rsa = _cert(rsa.generate_private_key(public_exponent=65537, key_size=2048), "root.example", 20)
    r = toolkit.certificate_check(short + long_rsa)
    a, b = r["certificates"]
    assert a["key"]["algorithm"] == "ECDSA secp256r1" and a["key"]["quantum_safe"] is False and a["severity"] == "low"
    assert b["key"]["algorithm"] == "RSA-2048" and b["severity"] == "high" and len(b["findings"]) == 2
    assert r["quantum_vulnerable"] == 2 and r["worst_severity"] == "high"
    expired = toolkit.certificate_check(short, now=datetime.now(timezone.utc) + timedelta(days=800))
    assert expired["certificates"][0]["findings"][0]["finding"] == "certificate has expired"
    with pytest.raises(toolkit.ToolkitError):
        toolkit.certificate_check("not a cert")


def test_harvest_risk():
    r = toolkit.harvest_risk([{"name": "contracts", "secrecy_years": 10, "protected_by": "RSA-2048"},
                              {"name": "designs", "secrecy_years": 2, "protected_by": "ECDH P-256"},
                              {"name": "backups", "secrecy_years": 30, "protected_by": "AES-256"}],
                             migration_years=3, quantum_years=[2035], this_year=2026)
    by = {d["name"]: d for d in r["datasets"]}
    assert by["contracts"]["scenarios"][0] == {"quantum_year": 2035, "exposed": True, "years_exposed": 4.0}   # 2026+3+10-2035
    assert by["contracts"]["latest_safe_migration_finish"] == {"2035": 2025}
    assert not by["designs"]["scenarios"][0]["exposed"] and by["backups"]["already_quantum_safe"]
    assert r["at_risk"] == ["contracts"] and r["datasets"][0]["name"] == "contracts"
    with pytest.raises(toolkit.ToolkitError):
        toolkit.harvest_risk([], 1)


def test_size_impact():
    k = toolkit.size_impact("key exchange", "X25519", "X25519MLKEM768", per_day=1_000_000)
    assert k["bytes_per_operation"] == {"current": 64, "target": 2336, "added": 2272, "times_larger": 36.5}
    assert k["per_day"]["added_megabytes"] == 2272.0 and "warning" in k
    s = toolkit.size_impact("signature", "ecdsa-p256", "ML-DSA-65", signatures_per_operation=3, keys_per_operation=2)
    assert s["bytes_per_operation"]["current"] == 65 * 2 + 64 * 3 and s["bytes_per_operation"]["target"] == 1952 * 2 + 3309 * 3
    with pytest.raises(toolkit.ToolkitError):
        toolkit.size_impact("signature", "x25519", "ml-dsa-65")


def test_circuit_stats():
    bell = 'OPENQASM 2.0; include "qelib1.inc"; qreg q[3]; h q[0]; cx q[0],q[1];'
    s = toolkit.circuit_stats(bell)
    assert s["qubits"] == 3 and s["qubits_used"] == 2 and s["idle_qubits"] == [2]
    assert s["two_qubit_gates"] == 1 and s["depth"] == 2 and s["basis_gates"] == {"h": 1, "cx": 1}
    assert s["runs_on_local_simulator"] and not s["all_to_all_needed"]
    with pytest.raises(toolkit.ToolkitError):
        toolkit.circuit_stats("")


def test_supplier_score_signed_and_priced(tmp_path):
    assert sum(q["weight"] for q in toolkit.QUESTIONS) == 100
    assert all(DEFAULT_PRICES_USD[t] == p for t, p in toolkit.PRICES.items())      # every toolkit tool is paid
    db = str(tmp_path / "q.db")
    att = Attestor(db)
    srv = build_server(Settings(db_path=db, rate_per_min=1000), att)

    async def go():
        async with Client(srv) as c:
            names = {t.name for t in (await c.list_tools()).tools}
            assert set(toolkit.PRICES) <= names
            qs = (await c.call_tool("pqc_supplier_score", {})).structured_content
            assert len(qs["questions"]) == 10
            answers = {q["id"]: "yes" for q in qs["questions"]}
            answers.update(tls_hybrid="no", roadmap="partial")
            r = await c.call_tool("pqc_supplier_score", {"supplier": "Acme Fasteners", "answers": answers,
                                                         "evidence": {"inventory": "ab" * 32}})
            assert not r.is_error, r
            card = r.structured_content
            assert card["score"] == 78 and card["grade"] == "B" and card["gaps"][0]["id"] == "tls_hybrid"
            stored = att.get(card["scorecard_id"])
            keys = att.public_keys()
            assert stored["body"]["supplier"] == "Acme Fasteners"
            assert Attestor.verify(stored, keys["ed25519"], keys["ml_dsa_87"])["valid"]
            assert (await c.call_tool("pqc_supplier_score", {"supplier": "X Co", "answers": {"nope": "yes"}})).is_error
            st = (await c.call_tool("quantum_circuit_stats", {"qasm": "OPENQASM 2.0; qreg q[2]; h q[0]; cx q[0],q[1];"}))
            assert st.structured_content["depth"] == 2
    anyio.run(go)


def test_toolkit_price_env(monkeypatch):
    monkeypatch.setenv("QUANTUM_PRICE_PQC_SUPPLIER_SCORE", "5")
    assert PaySettings.from_env().prices_usd["pqc_supplier_score"] == "5"
