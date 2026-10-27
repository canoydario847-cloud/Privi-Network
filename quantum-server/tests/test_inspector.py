# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Quantum - https://priviflow.us - dariocanoy@priviflow.us
"""Privi Inspector: intercepts agents that are unknown, uncertified, outdated, revoked, under-level, forged or replayed;
the patrol hunts them onto a watchlist."""
import base64
import json
import secrets
import sqlite3
import time

import anyio
from cryptography.hazmat.primitives.asymmetric import mldsa
from mcp import Client

from privi_quantum.attest import Attestor
from privi_quantum.server import Settings, build_server, http_app

SMALL = {"jobs": [{"name": n, "minutes": m} for n, m in zip("ABCDE", [3, 5, 7, 2, 4])]}
ADMIN = "adm_inspector"


class Agent:
    def __init__(self):
        self.key = mldsa.MLDSA65PrivateKey.generate()
        self.pub = base64.b64encode(self.key.public_key().public_bytes_raw()).decode()
        self.id = self.token = None

    def sign(self, msg: str) -> str:
        return base64.b64encode(self.key.sign(msg.encode())).decode()

    def cred(self, ts=None, nonce=None, signer=None):
        ts = int(time.time()) if ts is None else ts
        nonce = nonce or secrets.token_hex(12)
        sig = (signer or self).sign(f"privi-inspector:v1:{self.id}:{ts}:{nonce}")
        return {"agent_id": self.id, "ts": ts, "nonce": nonce, "signature": sig}


def setup(tmp_path, mode="enforce"):
    db = str(tmp_path / "i.db")
    return build_server(Settings(db_path=db, rate_per_min=1000, admin_key=ADMIN, inspector_mode=mode,
                                 inspector_require_human=False, inspector_require_id=False, inspector_min_grade="F"),
                        Attestor(db)), db      # human factors are tested in test_humans.py


def test_checkpoint_intercepts_and_admits(tmp_path):
    srv, db = setup(tmp_path)
    ag, impostor = Agent(), Agent()

    async def go():
        async with Client(srv) as c:
            async def t(name, args, ok=True):
                r = await c.call_tool(name, args)
                assert r.is_error is (not ok), (name, r.structured_content)
                return r.structured_content

            r = await t("dreamweaver_run", {"problem": "balance_lines", "data": SMALL}, ok=False)
            assert r["error"] == "intercepted by Privi Inspector" and r["reasons"] == ["no_credential"]
            r = await t("dreamscape_open", {"name": "Test scape", "privi_pass": "ppass_fake"}, ok=False)
            assert r["reasons"] == ["pass_invalid"]

            e = await t("qagent_enroll", {"name": "Field Bot", "operator": "Acme", "public_key": ag.pub})
            ag.id, ag.token = e["agent_id"], e["agent_token"]
            r = await t("inspector_pass", ag.cred(), ok=False)                       # enrolled, nothing earned yet
            assert set(r["reasons"]) == {"no_certificate", "level_too_low"}
            await t("qagent_scan", {"agent_id": ag.id, "agent_token": ag.token, "code": "x = 1"})
            r = await t("inspector_pass", ag.cred(), ok=False)                       # Q1 only: certified, too low
            assert r["reasons"] == ["level_too_low"] and "Quantum-safe identity" in r["fixes"][0]

            ch = await t("qagent_challenge", {"agent_id": ag.id, "agent_token": ag.token})
            await t("qagent_prove", {"agent_id": ag.id, "agent_token": ag.token, "challenge_id": ch["challenge_id"],
                                     "signature": ag.sign(ch["message"])})
            good = ag.cred()
            p = await t("inspector_pass", good)
            assert p["allowed"] and p["privi_pass"].startswith("ppass_")
            assert (await t("inspector_pass", good, ok=False))["reasons"][0] == "replayed_nonce"
            assert (await t("inspector_pass", ag.cred(ts=int(time.time()) - 3600), ok=False))["reasons"][0] == "stale_timestamp"

            run = await t("dreamweaver_run", {"problem": "balance_lines", "data": SMALL, "fanout": 1, "privi_pass": p["privi_pass"]})
            assert run["ok"]
            sc = await t("dreamscape_open", {"name": "Field scape", "privi_pass": p["privi_pass"]})

            # someone posing as the agent: signatures from the wrong key are intercepted and counted
            for _ in range(5):
                r = await t("inspector_pass", ag.cred(signer=impostor), ok=False)
                assert r["reasons"][0] == "bad_signature"
            st = await t("inspector_status", {"agent_id": ag.id})
            assert st["allowed"] and st["impersonation_attempts_last_hour"] == 5

            patrol = await t("inspector_patrol", {})
            assert patrol["patrol"]["by_reason"] == {"impersonation_attempts": 1}
            wl = await t("inspector_watchlist", {})
            assert wl["agents"][0]["agent_id"] == ag.id and wl["agents"][0]["reasons"] == ["impersonation_attempts"]
            assert (await t("inspector_patrol", {}, ok=False))["error"].startswith("a patrol ran")

            # any other service can use the same checkpoint
            chk = await t("inspector_check", {**ag.cred(), "min_level": "quantum_agent"})
            assert chk["intercepted"] and chk["reasons"] == ["level_too_low"]
            rep = await t("inspector_report", {})
            assert rep["by_decision"]["intercepted"] >= 9 and rep["intercepts_by_reason"]["bad_signature"] == 5
            return p["privi_pass"], sc

    pp, sc = anyio.run(go)
    from starlette.testclient import TestClient

    async def call(name, args):
        async with Client(srv) as c:
            return await c.call_tool(name, args)

    with TestClient(http_app(srv)) as http:
        # the WebSocket gate
        with http.websocket_connect("/dreamscape/ws") as ws:
            ws.receive_json()
            ws.send_json({"type": "auth", "scape_id": sc["scape_id"], "key": sc["scape_key"]})
            m = ws.receive_json()
            assert m["ok"] is False and m["reasons"] == ["no_credential"]
            ws.send_json({"type": "auth", "scape_id": sc["scape_id"], "key": sc["scape_key"], "privi_pass": pp})
            assert ws.receive_json()["ok"] is True

        # Privi revokes the agent: its live pass stops working at once
        assert http.post(f"/quantum-agents/{ag.id}/revoke", json={"reason": "x"}).status_code == 401
        assert http.post(f"/quantum-agents/{ag.id}/revoke", headers={"Authorization": f"Bearer {ADMIN}"},
                         json={"reason": "operator reported key theft"}).json()["revoked"]
        r = anyio.run(call, "dreamweaver_run", {"problem": "balance_lines", "data": SMALL, "privi_pass": pp})
        assert r.is_error and "revoked" in r.structured_content["reasons"]
        assert http.get(f"/inspector/agents/{ag.id}").json()["revoke_reason"] == "operator reported key theft"
        assert http.post("/inspector/check", json=ag.cred()).status_code == 403
        http.delete(f"/quantum-agents/{ag.id}/revoke", headers={"Authorization": f"Bearer {ADMIN}"})
        assert not anyio.run(call, "dreamweaver_run", {"problem": "balance_lines", "data": SMALL, "fanout": 1,
                                                       "privi_pass": pp}).is_error
        assert http.get("/inspector").json()["inspections"] > 0
        assert "agents" in http.get("/inspector/watchlist").json()

    # an outdated certificate is intercepted and hunted onto the watchlist; re-proving Q2 renews it
    con = sqlite3.connect(db)
    cert_id = con.execute("SELECT certificate_id FROM qa_agents WHERE agent_id=?", (ag.id,)).fetchone()[0]
    body = json.loads(con.execute("SELECT body FROM attestations WHERE id=?", (cert_id,)).fetchone()[0])
    body["valid_until"] = "2026-01-01T00:00:00+00:00"
    con.execute("UPDATE attestations SET body=? WHERE id=?", (json.dumps(body), cert_id))
    con.commit()
    r = anyio.run(call, "dreamweaver_run", {"problem": "balance_lines", "data": SMALL, "privi_pass": pp})
    assert r.is_error and r.structured_content["reasons"] == ["certificate_outdated"]
    srv._inspector.sweep()
    wl = {a["agent_id"]: a["reasons"] for a in srv._inspector.watchlist()["agents"]}
    assert "certificate_outdated" in wl[ag.id]

    async def renew():
        async with Client(srv) as c:
            ch = (await c.call_tool("qagent_challenge", {"agent_id": ag.id, "agent_token": ag.token})).structured_content
            return (await c.call_tool("qagent_prove", {"agent_id": ag.id, "agent_token": ag.token,
                                                       "challenge_id": ch["challenge_id"],
                                                       "signature": ag.sign(ch["message"])})).structured_content
    rn = anyio.run(renew)
    assert rn["certificate_renewed"] and rn["certificate_id"] != cert_id
    assert not anyio.run(call, "dreamweaver_run", {"problem": "balance_lines", "data": SMALL, "fanout": 1,
                                                   "privi_pass": pp}).is_error


def test_report_mode_logs_without_blocking(tmp_path):
    srv, _ = setup(tmp_path, mode="report")

    async def go():
        async with Client(srv) as c:
            r = await c.call_tool("dreamweaver_run", {"problem": "balance_lines", "data": SMALL, "fanout": 1})
            assert not r.is_error and r.structured_content["ok"]
            rep = (await c.call_tool("inspector_report", {})).structured_content
            assert rep["policy"]["mode"] == "report" and rep["by_decision"] == {"would_intercept": 1}
    anyio.run(go)
