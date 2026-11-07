# Copyright (c) 2026 Privi World Co. All rights reserved.
"""Privi RealCheck: enroll a person's passkey, check 'is it really you', impostor and expiry cases."""
import time

from privi_quantum.attest import Attestor
from privi_quantum.server import Settings, build_server, http_app
from test_humans import Authenticator

ADMIN = "adm_real"


def test_realcheck_end_to_end(tmp_path):
    from starlette.testclient import TestClient
    db = str(tmp_path / "r.db")
    srv = build_server(Settings(db_path=db, rate_per_min=1000, admin_key=ADMIN), Attestor(db))
    with TestClient(http_app(srv)) as http:
        assert http.post("/real/v1/orgs", json={"name": "Acme"}).status_code == 403
        org = http.post("/real/v1/orgs", json={"name": "Acme Tool", "seats": 2, "paid_days": 30},
                        headers={"authorization": f"Bearer {ADMIN}"}).json()
        H = {"authorization": f"Bearer {org['org_key']}"}
        assert http.get("/real/v1/members", headers={"authorization": "Bearer nope"}).status_code == 401

        cfo = http.post("/real/v1/members", json={"name": "Pat CFO", "role": "CFO"}, headers=H).json()
        bob = http.post("/real/v1/members", json={"name": "Bob"}, headers=H).json()
        assert http.post("/real/v1/members", json={"name": "Over"}, headers=H).status_code == 402  # seats

        # not enrolled yet
        assert http.post("/real/v1/checks", json={"member_id": cfo["member_id"]}, headers=H).status_code == 409

        phone, other = Authenticator(), Authenticator()
        tok = cfo["enroll_url"].rsplit("/", 1)[1]
        assert http.get(f"/real/enroll/{tok}").status_code == 200
        opts = srv._realcheck.enroll_options(tok)
        assert http.post(f"/real/enroll/{tok}/finish", json=phone.create({"create": opts["create"]})).json()["enrolled"]
        assert http.post(f"/real/enroll/{tok}/finish", json=phone.create({"create": opts["create"]})).status_code == 404  # one-time
        btok = bob["enroll_url"].rsplit("/", 1)[1]
        bopts = srv._realcheck.enroll_options(btok)
        http.post(f"/real/enroll/{btok}/finish", json=other.create({"create": bopts["create"]}))

        # a 'CFO' calls asking for a wire: the desk sends a RealCheck to the real CFO
        c = http.post("/real/v1/checks", json={"member_id": cfo["member_id"], "requested_by": "AP desk",
                                               "reason": "Wire $25,000 to new vendor", "channel": "phone call"}, headers=H).json()
        cid = c["check_id"]
        assert http.get(f"/real/c/{cid}").status_code == 200
        assert http.get(f"/real/v1/checks/{cid}", headers=H).json()["status"] == "pending"

        # Bob's passkey (someone else) cannot confirm for the CFO
        o = http.get(f"/real/c/{cid}/options?decision=confirm").json()
        assert http.post(f"/real/c/{cid}/decide?decision=confirm", json=other.get(o)).status_code == 403

        # the real CFO confirms with their own passkey
        o = http.get(f"/real/c/{cid}/options?decision=confirm").json()
        r = http.post(f"/real/c/{cid}/decide?decision=confirm", json=phone.get(o)).json()
        assert r["result"] == "confirmed" and r["receipt"]["signatures"]["ml_dsa_87"]
        s = http.get(f"/real/v1/checks/{cid}", headers=H).json()
        assert s["status"] == "confirmed" and s["receipt"]["body"]["member"] == "Pat CFO" and "/receipts/" in s["receipt_url"]
        assert http.post(f"/real/c/{cid}/decide?decision=confirm", json=phone.get(o)).status_code == 409  # no replay

        # impersonation: the CFO says no
        c2 = http.post("/real/v1/checks", json={"member_id": cfo["member_id"], "reason": "gift cards"}, headers=H).json()
        o = http.get(f"/real/c/{c2['check_id']}/options?decision=deny").json()
        assert http.post(f"/real/c/{c2['check_id']}/decide?decision=deny", json=phone.get(o)).json()["result"] == "denied"
        assert "IMPERSONATION" in http.get(f"/real/v1/checks/{c2['check_id']}", headers=H).json()["verdict"]

        # a confirm signature can't be used as a deny (challenge is bound to the decision)
        c3 = http.post("/real/v1/checks", json={"member_id": cfo["member_id"]}, headers=H).json()
        o = http.get(f"/real/c/{c3['check_id']}/options?decision=confirm").json()
        assert http.post(f"/real/c/{c3['check_id']}/decide?decision=deny", json=phone.get(o)).status_code == 400

        # expiry
        srv._realcheck._db.execute("UPDATE real_checks SET expires_at=? WHERE check_id=?", (time.time() - 1, c3["check_id"]))
        assert http.get(f"/real/v1/checks/{c3['check_id']}", headers=H).json()["status"] == "expired"

        # unpaid organization cannot create checks
        srv._realcheck._db.execute("UPDATE real_orgs SET paid_until='2000-01-01T00:00:00Z'")
        assert http.post("/real/v1/checks", json={"member_id": cfo["member_id"]}, headers=H).status_code == 402
        assert http.get("/real").status_code == 200


def test_realcheck_android_links(tmp_path, monkeypatch):
    from starlette.testclient import TestClient
    db = str(tmp_path / "a.db")
    srv = build_server(Settings(db_path=db, rate_per_min=1000), Attestor(db))
    with TestClient(http_app(srv)) as http:
        assert http.get("/.well-known/assetlinks.json").json() == []
        monkeypatch.setenv("REALCHECK_ANDROID_SHA256", "aa:bb, CC:DD")
        a = http.get("/.well-known/assetlinks.json").json()[0]
        assert a["target"]["package_name"] == "us.priviflow.realcheck" and a["target"]["sha256_cert_fingerprints"] == ["AA:BB", "CC:DD"]
        m = http.get("/real/manifest.webmanifest")
        assert m.json()["start_url"].startswith("/real") and "manifest+json" in m.headers["content-type"]
        assert "manifest.webmanifest" in http.get("/real").text
