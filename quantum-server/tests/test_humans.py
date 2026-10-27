# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Quantum - https://priviflow.us - dariocanoy@priviflow.us
"""Human trust: passkey (user-verified) approval, Stripe Identity, and the Inspector's grade and gate."""
import base64
import hashlib
import hmac
import json
import os
import secrets
import struct
import time

import anyio
import httpx2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, mldsa
from mcp import Client

from privi_quantum.attest import Attestor
from privi_quantum.server import PUBLIC_URL, Settings, build_server, http_app

SMALL = {"jobs": [{"name": n, "minutes": m} for n, m in zip("ABCDE", [3, 5, 7, 2, 4])]}
ADMIN = "adm_humans"
WHSEC = "whsec_test"
ORIGIN = PUBLIC_URL
RP_ID = ORIGIN.split("//", 1)[1].split("/")[0].split(":")[0]


def b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def unb64u(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def cbor(v):
    def head(major, n):
        if n < 24:
            return bytes([major << 5 | n])
        for info, fmt in ((24, ">B"), (25, ">H"), (26, ">I"), (27, ">Q")):
            if n < 1 << (8 * struct.calcsize(fmt)):
                return bytes([major << 5 | info]) + struct.pack(fmt, n)
    if isinstance(v, bool):
        return bytes([0xF5 if v else 0xF4])
    if isinstance(v, int):
        return head(0, v) if v >= 0 else head(1, -1 - v)
    if isinstance(v, bytes):
        return head(2, len(v)) + v
    if isinstance(v, str):
        e = v.encode()
        return head(3, len(e)) + e
    if isinstance(v, list):
        return head(4, len(v)) + b"".join(cbor(x) for x in v)
    if isinstance(v, dict):
        return head(5, len(v)) + b"".join(cbor(k) + cbor(x) for k, x in v.items())
    raise TypeError(v)


class Authenticator:
    """A software passkey, standing in for Face ID / Touch ID / Windows Hello."""

    def __init__(self, user_verifies=True):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.cred_id = secrets.token_bytes(16)
        self.count = 0
        self.uv = user_verifies

    def _client(self, typ, challenge, origin=ORIGIN):
        return json.dumps({"type": typ, "challenge": challenge, "origin": origin}).encode()

    def create(self, options, origin=ORIGIN):
        nums = self.key.public_key().public_numbers()
        cose = cbor({1: 2, 3: -7, -1: 1, -2: nums.x.to_bytes(32, "big"), -3: nums.y.to_bytes(32, "big")})
        flags = 0x01 | 0x40 | (0x04 if self.uv else 0)
        ad = (hashlib.sha256(RP_ID.encode()).digest() + bytes([flags]) + struct.pack(">I", 0) + bytes(16)
              + struct.pack(">H", len(self.cred_id)) + self.cred_id + cose)
        att = cbor({"fmt": "none", "attStmt": {}, "authData": ad})
        return {"id": b64u(self.cred_id), "rawId": b64u(self.cred_id), "type": "public-key",
                "response": {"clientDataJSON": b64u(self._client("webauthn.create", options["create"]["challenge"], origin)),
                             "attestationObject": b64u(att)}}

    def get(self, options):
        self.count += 1
        flags = 0x01 | (0x04 if self.uv else 0)
        ad = hashlib.sha256(RP_ID.encode()).digest() + bytes([flags]) + struct.pack(">I", self.count)
        cd = self._client("webauthn.get", options["get"]["challenge"])
        sig = self.key.sign(ad + hashlib.sha256(cd).digest(), ec.ECDSA(hashes.SHA256()))
        return {"id": b64u(self.cred_id), "rawId": b64u(self.cred_id), "type": "public-key",
                "response": {"clientDataJSON": b64u(cd), "authenticatorData": b64u(ad), "signature": b64u(sig)}}


class FakeStripe:
    def __init__(self):
        self.sessions = {}

    def handler(self, request):
        assert request.headers["authorization"].startswith("Basic ")
        if request.method == "POST" and request.url.path == "/v1/identity/verification_sessions":
            form = dict(x.split("=", 1) for x in request.content.decode().split("&"))
            assert form["type"] == "document" and form["options%5Bdocument%5D%5Brequire_matching_selfie%5D"] == "true"
            sid = "vs_" + secrets.token_hex(6)
            self.sessions[sid] = "requires_input"
            return httpx2.Response(200, json={"id": sid, "status": "requires_input", "url": f"https://verify.stripe.com/start/{sid}"})
        sid = request.url.path.rsplit("/", 1)[-1]
        return httpx2.Response(200, json={"id": sid, "status": self.sessions.get(sid, "requires_input")})


def webhook(event_type, sid, human_id, secret=WHSEC, ts=None):
    ts = int(time.time()) if ts is None else ts
    body = json.dumps({"type": event_type, "data": {"object": {"id": sid, "metadata": {"human_id": human_id}}}}).encode()
    sig = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return body, f"t={ts},v1={sig}"


def test_human_approval_id_verification_grade_and_gate(tmp_path):
    from starlette.testclient import TestClient
    db = str(tmp_path / "h.db")
    srv = build_server(Settings(db_path=db, rate_per_min=1000, admin_key=ADMIN, stripe_secret_key="sk_test_x",
                                stripe_identity_webhook_secret=WHSEC), Attestor(db))
    stripe = FakeStripe()
    humans = srv._humans
    humans._http = httpx2.Client(transport=httpx2.MockTransport(stripe.handler), base_url="https://api.stripe.com")
    key = mldsa.MLDSA65PrivateKey.generate()
    pub = base64.b64encode(key.public_key().public_bytes_raw()).decode()
    sign = lambda m: base64.b64encode(key.sign(m.encode())).decode()

    def cred(aid):
        ts, nonce = int(time.time()), secrets.token_hex(12)
        return {"agent_id": aid, "ts": ts, "nonce": nonce, "signature": sign(f"privi-inspector:v1:{aid}:{ts}:{nonce}")}

    async def mcp_calls(steps):
        out = []
        async with Client(srv) as c:
            for name, args in steps:
                out.append(await c.call_tool(name, args))
        return out

    run = lambda *steps: anyio.run(mcp_calls, list(steps))
    e, = run(("qagent_enroll", {"name": "Plant Bot", "operator": "Acme Robotics", "public_key": pub}))
    aid, tok = e.structured_content["agent_id"], e.structured_content["agent_token"]
    ch, = run(("qagent_challenge", {"agent_id": aid, "agent_token": tok}))
    ch = ch.structured_content
    run(("qagent_scan", {"agent_id": aid, "agent_token": tok, "code": "x=1"}),
        ("qagent_prove", {"agent_id": aid, "agent_token": tok, "challenge_id": ch["challenge_id"], "signature": sign(ch["message"])}))

    # quantum-safe identity alone is no longer enough
    p, = run(("inspector_pass", cred(aid)))
    assert p.is_error
    r = p.structured_content["reasons"]
    assert "human_approval_required" in r and "id_verification_required" in r and "grade_too_low" in r
    g0 = p.structured_content["trust"]
    assert g0["grade"] == "F" and g0["points"]["human_approval"] == 0

    req, = run(("qagent_human_request", {"agent_id": aid, "agent_token": tok}))
    req = req.structured_content
    rid = req["request_id"]
    assert req["approval_url"].endswith(f"/humans/approve/{rid}") and req["id_verification_available"]

    phone, laptop_no_uv = Authenticator(), Authenticator(user_verifies=False)
    with TestClient(http_app(srv)) as http:
        page = http.get(f"/humans/approve/{rid}").text
        assert "Plant Bot" in page and "Approve this AI agent?" in page
        opts = http.get(f"/humans/approve/{rid}/options").json()
        assert opts["create"]["authenticatorSelection"]["userVerification"] == "required"
        assert opts["create"]["rp"]["id"] == RP_ID

        # a device that did not verify the person is refused; so is a passkey made for another site
        bad = http.post(f"/humans/approve/{rid}/finish", json=laptop_no_uv.create(opts))
        assert bad.status_code == 400 and "did not verify the person" in bad.json()["error"]
        assert http.post(f"/humans/approve/{rid}/finish", json=phone.create(opts, origin="https://evil.example")).status_code == 400

        ok = http.post(f"/humans/approve/{rid}/finish", json=phone.create(opts)).json()
        assert ok["approved"] and ok["new_passkey"] and not ok["id_verified"]
        hid, session = ok["human_id"], ok["human_session"]
        assert http.post(f"/humans/approve/{rid}/finish", json=phone.create(opts)).status_code == 400   # link is one-time

        # passkey approved but no ID yet: still intercepted, grade improved
        p2, = run(("inspector_pass", cred(aid)))
        assert p2.structured_content["reasons"] == ["id_verification_required", "grade_too_low"]
        assert p2.structured_content["trust"]["points"]["human_approval"] == 20

        # ID verification through Stripe Identity (document + live selfie); Privi keeps only the result
        assert http.post("/humans/id/start", json={"human_session": "hsess_wrong"}).status_code == 400
        st = http.post("/humans/id/start", json={"human_session": session}).json()
        assert st["id_status"] == "pending" and st["verify_url"].startswith("https://verify.stripe.com/")
        sid = humans.human(hid)["id_ref"]
        body, sig = webhook("identity.verification_session.verified", sid, hid, secret="whsec_wrong")
        assert http.post("/humans/stripe-webhook", content=body, headers={"stripe-signature": sig}).status_code == 400
        body, sig = webhook("identity.verification_session.verified", sid, hid, ts=int(time.time()) - 3600)
        assert http.post("/humans/stripe-webhook", content=body, headers={"stripe-signature": sig}).status_code == 400
        body, sig = webhook("identity.verification_session.verified", sid, hid)
        assert http.post("/humans/stripe-webhook", content=body, headers={"stripe-signature": sig}).json()["id_status"] == "verified"
        assert "verified" in http.get(f"/humans/id/return?human={hid}").text

        # all factors present: the pass is issued and the realm opens
        p3, = run(("inspector_pass", cred(aid)))
        assert not p3.is_error, p3.structured_content
        t = p3.structured_content["trust"]
        assert t["grade"] == "B" and t["score"] == 83 and t["human"]["id_method"] == "stripe_identity"
        dw, = run(("dreamweaver_run", {"problem": "balance_lines", "data": SMALL, "fanout": 1,
                                       "privi_pass": p3.structured_content["privi_pass"]}))
        assert not dw.is_error and dw.structured_content["ok"]

        # the same person approves a second agent with their existing passkey: one tap, ID already verified
        key2 = mldsa.MLDSA87PrivateKey.generate()
        e2, = run(("qagent_enroll", {"name": "Dock Bot", "operator": "Acme Robotics",
                                     "public_key": base64.b64encode(key2.public_key().public_bytes_raw()).decode()}))
        a2, t2 = e2.structured_content["agent_id"], e2.structured_content["agent_token"]
        r2, = run(("qagent_human_request", {"agent_id": a2, "agent_token": t2}))
        rid2 = r2.structured_content["request_id"]
        o2 = http.get(f"/humans/approve/{rid2}/options").json()
        assert o2["get"]["challenge"] != opts["get"]["challenge"]          # bound to a different agent and key
        ok2 = http.post(f"/humans/approve/{rid2}/finish", json=phone.get(o2)).json()
        assert ok2["approved"] and not ok2["new_passkey"] and ok2["human_id"] == hid and ok2["id_verified"]
        phone.count -= 1                                                    # a cloned passkey's counter goes backwards
        r3, = run(("qagent_human_request", {"agent_id": a2, "agent_token": t2}))
        o3 = http.get(f"/humans/approve/{r3.structured_content['request_id']}/options").json()
        cloned = http.post(f"/humans/approve/{r3.structured_content['request_id']}/finish", json=phone.get(o3))
        assert cloned.status_code == 400 and "counter" in cloned.json()["error"]

        # grade and directory show the human factors
        g = http.get(f"/inspector/grade/{aid}").json()
        assert g["grade"] == "B" and g["missing"] == []
        prof = http.get(f"/quantum-agents/{aid}").json()
        assert prof["trust"]["human_approved"] and prof["trust"]["id_verified"] and prof["trust"]["grade"] == "B"

        # an in-person check recorded by Privi counts, but for less
        assert http.post(f"/humans/{hid}/id-verified", json={"note": "seen in person"}).status_code == 401
        http.post(f"/humans/{hid}/id-verified", headers={"Authorization": f"Bearer {ADMIN}"}, json={"note": "seen in person"})
        assert http.get(f"/inspector/grade/{aid}").json()["points"]["id_verification"] == 15
        http.delete(f"/humans/{hid}/id-verified", headers={"Authorization": f"Bearer {ADMIN}"})
        p4, = run(("inspector_pass", cred(aid)))
        assert p4.is_error and "id_verification_required" in p4.structured_content["reasons"]


def test_id_verification_off_until_stripe_is_connected(tmp_path):
    from starlette.testclient import TestClient
    db = str(tmp_path / "n.db")
    srv = build_server(Settings(db_path=db, rate_per_min=1000), Attestor(db))
    key = mldsa.MLDSA65PrivateKey.generate()
    pub = base64.b64encode(key.public_key().public_bytes_raw()).decode()

    async def go():
        async with Client(srv) as c:
            e = (await c.call_tool("qagent_enroll", {"name": "Solo Bot", "operator": "Acme", "public_key": pub})).structured_content
            return (await c.call_tool("qagent_human_request", {"agent_id": e["agent_id"], "agent_token": e["agent_token"]})).structured_content
    req = anyio.run(go)
    assert req["id_verification_available"] is False
    phone = Authenticator()
    with TestClient(http_app(srv)) as http:
        opts = http.get(f"/humans/approve/{req['request_id']}/options").json()
        ok = http.post(f"/humans/approve/{req['request_id']}/finish", json=phone.create(opts)).json()
        r = http.post("/humans/id/start", json={"human_session": ok["human_session"]})
        assert r.status_code == 400 and "not switched on" in r.json()["error"]
        assert http.post("/humans/stripe-webhook", content=b"{}", headers={"stripe-signature": "t=1,v1=x"}).status_code == 400
