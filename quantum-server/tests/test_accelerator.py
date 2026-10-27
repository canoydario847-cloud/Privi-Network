# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Quantum - https://priviflow.us - dariocanoy@priviflow.us
"""Quantum Agent Accelerator: an agent with its own ML-DSA key upgrades step by step; the directory verifies it."""
import base64

import anyio
from cryptography.hazmat.primitives.asymmetric import mldsa
from mcp import Client

from privi_quantum.attest import Attestor
from privi_quantum.server import Settings, build_server, http_app


def fake_checker(targets, *a, **k):
    res = [{"target": t, "status": "pq_hybrid" if "pq" in t else "tls13_classical",
            "pq_key_exchange": "X25519MLKEM768" if "pq" in t else None} for t in targets]
    return {"results": res, "summary": {}}


def test_agent_upgrades_to_quantum_agent_plus(tmp_path):
    from starlette.testclient import TestClient
    db = str(tmp_path / "a.db")
    srv = build_server(Settings(db_path=db, rate_per_min=1000), Attestor(db), None, fake_checker)
    key = mldsa.MLDSA65PrivateKey.generate()
    pub = base64.b64encode(key.public_key().public_bytes_raw()).decode()
    sign = lambda m: base64.b64encode(key.sign(m.encode())).decode()

    async def go():
        async with Client(srv) as c:
            async def t(name, args, ok=True):
                r = await c.call_tool(name, args)
                assert r.is_error is (not ok), (name, r.structured_content)
                return r.structured_content

            info = await t("accelerator_info", {})
            assert set(info["steps"]) == {"q1_scan", "q2_identity", "q3_transport", "q4_quantum"}
            await t("qagent_enroll", {"name": "Ops Bot", "operator": "Acme Robotics", "public_key": "bm90LWEta2V5"}, ok=False)
            e = await t("qagent_enroll", {"name": "Ops Bot", "operator": "Acme Robotics", "public_key": pub,
                                          "homepage": "https://acme.example/bot"})
            aid, tok = e["agent_id"], e["agent_token"]
            assert e["key_alg"] == "ML-DSA-65" and not any(s["passed"] for s in e["plan"])
            await t("qagent_enroll", {"name": "Copy", "operator": "Acme", "public_key": pub}, ok=False)   # one key, one agent

            # Q1: scan code
            q1 = await t("qagent_scan", {"agent_id": aid, "agent_token": tok,
                                         "code": "from cryptography.hazmat.primitives.asymmetric import rsa\nrsa.generate_private_key(65537, 2048)"})
            assert q1["level"] == "quantum_aware" and q1["code_scan"]["readiness_score"] < 100 and q1["certificate_id"]
            await t("qagent_scan", {"agent_id": aid, "agent_token": "wrong", "code": "x"}, ok=False)

            # Q2: wrong signature fails, right one passes
            ch = await t("qagent_challenge", {"agent_id": aid, "agent_token": tok})
            await t("qagent_prove", {"agent_id": aid, "agent_token": tok, "challenge_id": ch["challenge_id"],
                                     "signature": sign("something else")}, ok=False)
            await t("qagent_prove", {"agent_id": aid, "agent_token": tok, "challenge_id": ch["challenge_id"],
                                     "signature": sign(ch["message"])}, ok=False)          # challenge is single-use
            ch = await t("qagent_challenge", {"agent_id": aid, "agent_token": tok})
            q2 = await t("qagent_prove", {"agent_id": aid, "agent_token": tok, "challenge_id": ch["challenge_id"],
                                          "signature": sign(ch["message"])})
            assert q2["level"] == "quantum_safe_identity"

            # Q4 needs a Privi pass from the Inspector (Q2 done, so the agent qualifies)
            import secrets, time as _t
            ts, nonce = int(_t.time()), secrets.token_hex(12)
            p = await t("inspector_pass", {"agent_id": aid, "ts": ts, "nonce": nonce,
                                           "signature": sign(f"privi-inspector:v1:{aid}:{ts}:{nonce}")})
            pp = p["privi_pass"]
            await t("dreamweaver_run", {"problem": "balance_lines", "data": {"jobs": [{"name": "a", "minutes": 1},
                    {"name": "b", "minutes": 2}]}}, ok=False)                                   # no pass: intercepted
            # a run of some other problem is refused; the assigned task passes
            other = await t("dreamweaver_run", {"problem": "balance_lines", "privi_pass": pp, "data": {"jobs": [
                {"name": n, "minutes": m} for n, m in zip("ABCDE", [3, 5, 7, 2, 4])]}, "fanout": 1})
            await t("qagent_quantum_proof", {"agent_id": aid, "agent_token": tok,
                                             "attestation_id": other["attestation"]["id"]}, ok=False)
            task = await t("qagent_quantum_task", {"agent_id": aid, "agent_token": tok})
            run = await t("dreamweaver_run", {"problem": task["problem"], "data": task["data"], "fanout": 2,
                                              "privi_pass": pp})
            q4 = await t("qagent_quantum_proof", {"agent_id": aid, "agent_token": tok,
                                                  "attestation_id": run["attestation"]["id"]})
            assert q4["level"] == "quantum_agent" and q4["level_changed"]

            # Q3: one classical endpoint fails it; all post-quantum passes and upgrades to Quantum Agent+
            q3 = await t("qagent_scan", {"agent_id": aid, "agent_token": tok, "endpoints": ["pq.acme.example", "old.acme.example"]})
            assert q3["q3_transport"]["passed"] is False and q3["level"] == "quantum_agent"
            q3 = await t("qagent_scan", {"agent_id": aid, "agent_token": tok, "endpoints": ["pq.acme.example"]})
            assert q3["level"] == "quantum_agent_plus"
            cert = q3["certificate_id"]
            v = await t("quantum_verify", {"attestation_id": cert})
            assert v["valid"] is True

            # anyone can look it up and verify what it signs
            d = await t("qagent_directory", {"level": "quantum_agent_plus"})
            assert d["agents"][0]["agent_id"] == aid and d["counts"] == {"quantum_agent_plus": 1}
            ok = await t("qagent_verify", {"agent_id": aid, "message": "pay 5 USDC to merchant 42", "signature": sign("pay 5 USDC to merchant 42")})
            assert ok["valid"] and ok["level"] == "quantum_agent_plus"
            bad = await t("qagent_verify", {"agent_id": aid, "message": "pay 500 USDC", "signature": sign("pay 5 USDC to merchant 42")})
            assert bad["valid"] is False
            return aid, sign

    aid, sign = anyio.run(go)
    with TestClient(http_app(srv)) as http:
        assert "Quantum Agent Accelerator" in http.get("/accelerator").text
        assert http.get("/quantum-agents").json()["agents"][0]["agent_id"] == aid
        wk = http.get("/.well-known/quantum-agents.json").json()
        assert wk["verify_mcp"] == "qagent_verify" and wk["counts"]["quantum_agent_plus"] == 1
        prof = http.get(f"/quantum-agents/{aid}").json()
        assert prof["public_key"] and prof["steps"]["q4_quantum"]["passed"]
        r = http.post(f"/quantum-agents/{aid}/verify", json={"message": "hello", "signature": sign("hello")})
        assert r.json()["valid"] is True
        assert http.post(f"/quantum-agents/{aid}/verify", json={"message": "x"}).status_code == 400
        assert "Quantum Agent+" in http.get(f"/quantum-agents/{aid}/badge.svg").text
        assert http.get("/quantum-agents/qagent_missing").status_code == 404


def test_unlisted_agents_stay_out_of_the_directory(tmp_path):
    db = str(tmp_path / "b.db")
    srv = build_server(Settings(db_path=db, rate_per_min=1000), Attestor(db))
    pub = base64.b64encode(mldsa.MLDSA87PrivateKey.generate().public_key().public_bytes_raw()).decode()

    async def go():
        async with Client(srv) as c:
            e = (await c.call_tool("qagent_enroll", {"name": "Quiet Bot", "operator": "Acme", "public_key": pub,
                                                     "listed": False})).structured_content
            assert e["key_alg"] == "ML-DSA-87"
            d = (await c.call_tool("qagent_directory", {})).structured_content
            assert d["agents"] == []
            prof = (await c.call_tool("qagent_status", {"agent_id": e["agent_id"]})).structured_content
            assert prof["level"] == "enrolled"
    anyio.run(go)
