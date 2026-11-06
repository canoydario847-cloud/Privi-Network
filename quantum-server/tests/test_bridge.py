# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Quantum - https://priviflow.us - dariocanoy@priviflow.us
"""Privi Bridge: agents drive a company's existing software inside a passkey-signed scope."""
import base64
import hashlib
import hmac
import json
import secrets
import time
from urllib.parse import urlsplit

import anyio
import httpx2
import pytest
from cryptography.hazmat.primitives.asymmetric import mldsa
from mcp import Client

from privi_quantum import bridge
from privi_quantum.attest import Attestor
from privi_quantum.hardware import HardwareRouter, IonQBackend, LocalBackend
from privi_quantum.server import Settings, build_server, http_app
from test_humans import Authenticator
from test_mandates import FakeIonQCloud

ORDERS = {"data": {"plant": "Port Huron", "orders": [
    {"sku": "BRK-A", "cycle_min": 42}, {"sku": "HSG-B", "cycle_min": 17}, {"sku": "SHF-C", "cycle_min": 33},
    {"sku": "GSK-D", "cycle_min": 8}, {"sku": "VLV-E", "cycle_min": 25}, {"sku": "PNL-F", "cycle_min": 29}]}}
OPS = [{"name": "list_orders", "method": "GET", "path": "/orders", "kind": "read", "description": "Open orders for a plant"},
       {"name": "post_schedule", "method": "POST", "path": "/schedule/{plant}", "kind": "write",
        "description": "Store the line schedule"}]
TRANSFORM = {"jobs": {"from": "data.orders", "fields": {"name": "sku", "minutes": "cycle_min"}},
             "line_a": {"value": "Press 1"}, "line_b": {"value": "Press 2"}}
PUBLIC = lambda host: ["93.184.216.34"]  # noqa: E731


class FakeERP:
    """A company's existing software: a JSON API that checks Privi's signature on every call."""

    def __init__(self):
        self.secret, self.pushes, self.calls, self.fail_push = None, [], [], False

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.calls.append(request)
        if request.headers.get("x-api-key") != "erp-key-123":
            return httpx2.Response(401, json={"error": "bad key"})
        if self.secret and not self.verify(request):
            return httpx2.Response(403, json={"error": "bad signature"})
        if request.method == "GET" and request.url.path == "/api/orders":
            return httpx2.Response(200, json=ORDERS)
        if request.method == "POST" and request.url.path.startswith("/api/schedule/"):
            if self.fail_push:
                return httpx2.Response(500, json={"error": "db down"})
            self.pushes.append(json.loads(request.content))
            return httpx2.Response(201, json={"stored": True})
        return httpx2.Response(404)

    def verify(self, request) -> bool:
        ts = int(request.headers["X-Privi-Timestamp"])
        path_q = request.url.raw_path.decode()
        msg = f"{ts}.{request.method}.{path_q}.{hashlib.sha256(request.content).hexdigest()}".encode()
        good = "v1=" + hmac.new(self.secret, msg, hashlib.sha256).hexdigest()
        return abs(time.time() - ts) < 300 and hmac.compare_digest(good, request.headers["X-Privi-Signature"])


def test_transform_and_paths():
    data = bridge.apply_transform(ORDERS, TRANSFORM)
    assert data["jobs"][0] == {"name": "BRK-A", "minutes": 42} and len(data["jobs"]) == 6 and data["line_a"] == "Press 1"
    assert bridge.apply_transform(ORDERS, {"plant": {"path": "data.plant"}}) == {"plant": "Port Huron"}
    assert bridge.get_path(ORDERS, "data.orders.-1.sku") == "PNL-F"
    for bad, msg in [({"jobs": {"from": "data.nope"}}, "no field"), ({"jobs": {"from": "data.plant"}}, "not a list"),
                     ({"jobs": {"x": 1}}, "needs from"), ({}, "transform must"),
                     ({"jobs": {"from": "data.orders", "fields": {"name": "missing"}}}, "no field")]:
        with pytest.raises(bridge.BridgeError, match=msg):
            bridge.apply_transform(ORDERS, bad)
    big = {"rows": [{"a": i} for i in range(100)]}
    with pytest.raises(bridge.BridgeError, match="at most"):
        bridge.apply_transform(big, {"x": {"from": "rows"}})


@pytest.mark.parametrize("url,addrs,msg", [
    ("http://erp.acme.com/api/", ["93.184.216.34"], "https://"),
    ("https://user:pw@erp.acme.com/", ["93.184.216.34"], "no credentials"),
    ("https://erp.acme.com/", ["10.0.0.5"], "private or reserved"),
    ("https://erp.acme.com/", ["127.0.0.1"], "private or reserved"),
    ("https://erp.acme.com/", ["169.254.169.254"], "private or reserved"),
    ("https://erp.acme.com/", ["93.184.216.34", "192.168.1.9"], "private or reserved"),
    ("https://erp.acme.com/", ["::1"], "private or reserved"),
])
def test_network_safety(url, addrs, msg):
    with pytest.raises(bridge.BridgeError, match=msg):
        bridge.check_url(url, resolver=lambda h: addrs)


def test_bridge_end_to_end(tmp_path):
    from starlette.testclient import TestClient
    db = str(tmp_path / "b.db")
    erp = FakeERP()
    cloud = FakeIonQCloud()
    router = HardwareRouter(db, [LocalBackend(), IonQBackend("k123", "simulator", None, opener=cloud)])
    resolver_hosts = {"erp.acme.com": ["93.184.216.34"], "internal.acme.com": ["10.1.2.3"]}
    srv = build_server(Settings(db_path=db, rate_per_min=1000), Attestor(db), None, None, router,
                       bridge_http=httpx2.Client(transport=httpx2.MockTransport(erp.handler)),
                       bridge_resolver=lambda h: resolver_hosts.get(h, []))
    humans = srv._humans
    key = mldsa.MLDSA65PrivateKey.generate()
    pub = base64.b64encode(key.public_key().public_bytes_raw()).decode()
    sign = lambda m: base64.b64encode(key.sign(m.encode())).decode()

    async def calls(steps):
        out = []
        async with Client(srv) as c:
            for name, args in steps:
                out.append(await c.call_tool(name, args))
        return out
    run = lambda *steps: anyio.run(calls, list(steps))
    one = lambda name, args: run((name, args))[0]

    e = one("qagent_enroll", {"name": "Plant Bot", "operator": "Acme Robotics", "public_key": pub}).structured_content
    aid, tok = e["agent_id"], e["agent_token"]
    ch = one("qagent_challenge", {"agent_id": aid, "agent_token": tok}).structured_content
    run(("qagent_scan", {"agent_id": aid, "agent_token": tok, "code": "x=1"}),
        ("qagent_prove", {"agent_id": aid, "agent_token": tok, "challenge_id": ch["challenge_id"], "signature": sign(ch["message"])}))
    rid = one("qagent_human_request", {"agent_id": aid, "agent_token": tok}).structured_content["request_id"]
    phone, stranger = Authenticator(), Authenticator()

    with TestClient(http_app(srv)) as http:
        opts = http.get(f"/humans/approve/{rid}/options").json()
        hid = http.post(f"/humans/approve/{rid}/finish", json=phone.create(opts)).json()["human_id"]
        humans._mark(hid, "verified", "stripe_identity", "vs_test")
        ts, nonce = int(time.time()), secrets.token_hex(12)
        ppass = one("inspector_pass", {"agent_id": aid, "ts": ts, "nonce": nonce,
                                       "signature": sign(f"privi-inspector:v1:{aid}:{ts}:{nonce}")}).structured_content["privi_pass"]
        conn = {"name": "Acme ERP", "base_url": "https://erp.acme.com/api", "operations": OPS,
                "auth_header": "X-Api-Key", "auth_value": "erp-key-123", "privi_pass": ppass}

        # 1. registering needs the agent's pass, public HTTPS, and a sane scope
        assert one("bridge_connect", {k: v for k, v in conn.items() if k != "privi_pass"}).is_error
        r = one("bridge_connect", {**conn, "base_url": "https://internal.acme.com/api"})
        assert r.is_error and "private" in r.structured_content["error"]
        r = one("bridge_connect", {**conn, "operations": [{"name": "drop", "method": "GET", "path": "/x", "kind": "write"}]})
        assert r.is_error and "write operations use" in r.structured_content["error"]
        d = one("bridge_connect", conn).structured_content
        bid = d["bridge_id"]
        erp.secret = base64.b64decode(d["signing_secret"])
        assert d["status"] == "draft" and d["sign_url"].endswith(f"/bridges/{bid}") and d["stores_credential"]
        assert "READ GET /orders" in d["scope_text"] and "WRITE POST /schedule/{plant}" in d["scope_text"]
        pub_view = http.get(f"/bridges/{bid}.json")
        assert "erp-key-123" not in pub_view.text and "signing_secret" not in pub_view.text
        assert pub_view.headers["access-control-allow-origin"] == "*"

        wf = {"bridge_id": bid, "pull_operation": "list_orders", "problem": "balance_lines", "transform": TRANSFORM,
              "push_operation": "post_schedule", "push_params": {"plant": "port-huron"}, "privi_pass": ppass}
        r = one("quantum_workflow_run", wf)
        assert r.is_error and "not signed" in r.structured_content["error"] and not erp.calls

        # 2. the person signs the exact scope with their passkey; nobody else can
        page = http.get(f"/bridges/{bid}").text
        assert "Waiting for your signature" in page and "Acme ERP" in page and "/schedule/{plant}" in page
        so = http.get(f"/bridges/{bid}/options?action=sign").json()
        assert http.post(f"/bridges/{bid}/sign", json=stranger.get(so)).status_code == 400
        ro = http.get(f"/bridges/{bid}/options?action=revoke").json()
        assert http.post(f"/bridges/{bid}/sign", json=phone.get(ro)).status_code == 400
        signed = http.post(f"/bridges/{bid}/sign", json=phone.get(so)).json()
        assert signed["status"] == "active" and http.get(f"/attestations/{signed['attestation_id']}").json()["body"]["kind"] == "software_bridge"

        # 3. test a READ; WRITE and out-of-scope operations never run outside a workflow
        t = one("bridge_test", {"bridge_id": bid, "operation": "list_orders", "privi_pass": ppass}).structured_content
        assert t["status"] == 200 and "BRK-A" in t["preview"]
        assert "is a WRITE operation" in one("bridge_test", {"bridge_id": bid, "operation": "post_schedule",
                                                              "privi_pass": ppass}).structured_content["error"]
        r = one("quantum_workflow_run", {**wf, "pull_operation": "delete_everything"})
        assert r.is_error and "not in the signed scope" in r.structured_content["error"]

        # 4. a full workflow: pull orders -> quantum -> push the signed schedule back
        w = one("quantum_workflow_run", wf).structured_content
        assert w["status"] == "done", w
        assert [s["step"] for s in w["steps"]] == ["pull", "transform", "quantum", "push"]
        assert len(w["steps"][0]["response_sha256"]) == 64 and w["steps"][0]["bytes"] > 0 and w["steps"][0]["status"] == 200
        push = erp.pushes[-1]
        assert push["privi_workflow"] == w["workflow_id"] and push["found_optimum"] is True
        assert set(push["decision"]["assignment"]) == {"Press 1", "Press 2"} and push["advantage_receipt_id"].startswith("qa_")
        assert all(erp.verify(c) for c in erp.calls)                       # every request is signed for this bridge
        sealed = http.get(f"/attestations/{w['sealed']['id']}").json()["body"]
        assert sealed["kind"] == "software_bridge_run" and sealed["outcome"] == "done"
        assert [s["step"] for s in sealed["steps"]] == ["pull", "transform", "quantum", "push"]
        assert "erp-key-123" not in json.dumps(sealed)

        # 5. queued hardware: the push happens when the job finishes
        q = one("quantum_workflow_run", {**wf, "backend": "ionq:simulator", "shots": 200}).structured_content
        assert q["status"] == "waiting_hardware" and len(erp.pushes) == 1
        for _ in range(2):
            q = one("bridge_workflow", {"workflow_id": q["workflow_id"]}).structured_content
        assert q["status"] == "done" and len(erp.pushes) == 2 and erp.pushes[-1]["backend"] == "ionq:simulator"

        # 6. if the software refuses the push, the run is sealed as failed with the reason
        erp.fail_push = True
        f = one("quantum_workflow_run", wf)
        assert f.structured_content["status"] == "failed" and "500" in f.structured_content["error"]
        erp.fail_push = False

        # 7. the person revokes with their passkey; the agent can no longer reach the software
        ro = http.get(f"/bridges/{bid}/options?action=revoke").json()
        rv = http.post(f"/bridges/{bid}/revoke", json=phone.get(ro)).json()
        assert rv["status"] == "revoked" and rv["revocation_attestation_id"]
        n = len(erp.calls)
        assert "revoked" in one("quantum_workflow_run", wf).structured_content["error"] and len(erp.calls) == n

        # 8. the agent can give up a bridge too
        d2 = one("bridge_connect", conn).structured_content
        so2 = http.get(f"/bridges/{d2['bridge_id']}/options?action=sign").json()
        http.post(f"/bridges/{d2['bridge_id']}/sign", json=phone.get(so2))
        gone = one("bridge_revoke", {"bridge_id": d2["bridge_id"], "privi_pass": ppass}).structured_content
        assert gone["status"] == "revoked" and gone["revoked_by"] == "agent"
        st = one("bridge_status", {"bridge_id": bid}).structured_content
        assert st["status"] == "revoked" and len(st["workflows"]) >= 3
        assert "Revoked" in http.get(f"/bridges/{bid}").text
