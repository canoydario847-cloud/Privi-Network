# Copyright (c) 2026 Privi World Co. All rights reserved.
"""Privi GENIUS: reserve report checks, CEO/CFO passkey certification, sealing, and the stablecoin check."""
import json

import anyio
from mcp import Client

from privi_quantum.attest import Attestor
from privi_quantum.genius import evaluate, posting_deadline
from privi_quantum.server import Settings, build_server, http_app
from test_humans import Authenticator

ADMIN = "adm_gen"
USDC_BASE = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"


def good_report(period="2026-10", outstanding=1_000_000.0, supply_chain=1_000_000.0):
    return {"period": period, "outstanding_total_usd": outstanding,
            "reserves": [{"class": "demand_deposits", "value_usd": 400_000, "custodian": "Bank A"},
                         {"class": "treasury_bills", "value_usd": 610_000, "max_remaining_maturity_days": 60}],
            "chains": [{"chain": "base", "address": USDC_BASE, "outstanding_usd": supply_chain}],
            "examination": {"firm": "Example CPA LLP", "letter_sha256": "ab" * 32}}


def test_evaluate_rules():
    assert evaluate({**good_report(), "chains": []})["all_pass"]
    bad = evaluate({"outstanding_total_usd": 100.0, "chains": [], "reserves": [
        {"class": "bitcoin", "value_usd": 50}, {"class": "treasury_bills", "value_usd": 40, "max_remaining_maturity_days": 180}]})
    failed = {f["check"] for f in bad["findings"] if not f["pass"]}
    assert failed == {"one_to_one", "permitted_assets", "maturity_limits"}
    assert str(posting_deadline("2026-10")) == "2026-11-30" and str(posting_deadline("2026-12")) == "2027-01-31"


def test_genius_end_to_end(tmp_path):
    from starlette.testclient import TestClient
    db = str(tmp_path / "g.db")
    srv = build_server(Settings(db_path=db, rate_per_min=1000, admin_key=ADMIN), Attestor(db))
    gen = srv._genius
    gen._rpc_call = lambda url, payload: {"result": hex(1_000_000 * 10**6)}   # on-chain totalSupply = 1,000,000 USDC
    A = {"authorization": f"Bearer {ADMIN}"}
    with TestClient(http_app(srv)) as http:
        iss = http.post("/genius/v1/issuers", json={"name": "Example Dollar Co"}, headers=A).json()
        iid, K = iss["issuer_id"], {"authorization": f"Bearer {iss['issuer_key']}"}
        assert http.post(f"/genius/v1/issuers/{iid}/license", json={"status": "permitted"}, headers=A).status_code == 400  # needs source
        http.post(f"/genius/v1/issuers/{iid}/license", json={"status": "applied", "regulator": "OCC"}, headers=A)
        http.post(f"/genius/v1/issuers/{iid}/coins", json={"chain": "base", "address": USDC_BASE, "symbol": "exd"}, headers=A)

        ceo, cfo, other = Authenticator(), Authenticator(), Authenticator()
        ids = {}
        for role, dev in (("CEO", ceo), ("CFO", cfo)):
            o = http.post("/genius/v1/officers", json={"name": f"Pat {role}", "role": role}, headers=K).json()
            tok = o["enroll_url"].rsplit("/", 1)[1]
            assert http.get(f"/genius/enroll/{tok}").status_code == 200
            assert http.post(f"/genius/enroll/{tok}/finish", json=dev.create({"create": gen.enroll_options(tok)["create"]})).json()["enrolled"]
            ids[role] = o["officer_id"]

        sub = http.post("/genius/v1/reports", json=good_report(), headers=K).json()
        rid = sub["report_id"]
        assert sub["checks"]["all_pass"] and http.get(f"/genius/certify/{rid}").status_code == 200
        # sealing needs both certifications
        assert http.post(f"/genius/v1/reports/{rid}/seal", headers=K).status_code == 409
        # someone else's passkey cannot certify as the CEO
        op = http.get(f"/genius/certify/{rid}/options?officer={ids['CEO']}").json()
        assert http.post(f"/genius/certify/{rid}/sign?officer={ids['CEO']}", json=other.get(op)).status_code == 400
        for role, dev in (("CEO", ceo), ("CFO", cfo)):
            op = http.get(f"/genius/certify/{rid}/options?officer={ids[role]}").json()
            assert http.post(f"/genius/certify/{rid}/sign?officer={ids[role]}", json=dev.get(op)).json()["role"] == role
        sealed = http.post(f"/genius/v1/reports/{rid}/seal", headers=K).json()
        assert sealed["status"] == "sealed" and sealed["receipt"]["signatures"]["ml_dsa_87"]
        pub = http.get(f"/genius/reports/{rid}.json").json()
        names = {f["check"]: f["pass"] for f in pub["checks"]["findings"]}
        assert names["onchain_supply_base"] and names["ceo_cfo_certified"] and names["examination_recorded"]
        assert http.get(f"/genius/reports/{rid}").status_code == 200
        assert http.post("/genius/v1/reports", json=good_report(), headers=K).status_code == 409   # sealed month is final

        # the stablecoin check, over MCP (payments off in tests)
        async def call(args):
            async with Client(srv) as c:
                r = await c.call_tool("genius_stablecoin_check", args)
                return json.loads(r.content[0].text)
        res = anyio.run(call, {"chain": "base", "address": USDC_BASE.upper().replace("0X", "0x")})
        assert res["verdict"] == "pass_reserves_license_pending" and res["latest_reserve_report"]["current"]
        http.post(f"/genius/v1/issuers/{iid}/license", headers=A, json={"status": "permitted", "regulator": "OCC",
                                                                       "source_url": "https://www.occ.gov/example"})
        assert anyio.run(call, {"chain": "base", "address": USDC_BASE})["verdict"] == "pass"
        unknown = anyio.run(call, {"chain": "base", "address": "0x" + "1" * 40})
        assert unknown["verdict"] == "unknown" and not unknown["in_privi_registry"]

        # a report that misses 1:1 and an on-chain mismatch is sealed honestly as failing -> caution
        gen._rpc_call = lambda url, payload: {"result": hex(2_000_000 * 10**6)}
        bad = good_report("2026-11", outstanding=1_200_000.0, supply_chain=1_200_000.0)
        r2 = http.post("/genius/v1/reports", json=bad, headers=K).json()
        assert not r2["checks"]["all_pass"]
        for role, dev in (("CEO", ceo), ("CFO", cfo)):
            op = http.get(f"/genius/certify/{r2['report_id']}/options?officer={ids[role]}").json()
            http.post(f"/genius/certify/{r2['report_id']}/sign?officer={ids[role]}", json=dev.get(op))
        s2 = http.post(f"/genius/v1/reports/{r2['report_id']}/seal", headers=K).json()
        assert s2["all_pass"] is False
        res = anyio.run(call, {"chain": "base", "address": USDC_BASE})
        assert res["verdict"] == "caution" and "one_to_one" in res["latest_reserve_report"]["failed_checks"]

        # unpaid issuer
        gen._db.execute("UPDATE gen_issuers SET paid_until='2000-01-01T00:00:00Z'")
        assert http.post("/genius/v1/reports", json=good_report("2026-12"), headers=K).status_code == 402
