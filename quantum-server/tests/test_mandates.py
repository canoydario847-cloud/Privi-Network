# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Quantum - https://priviflow.us - dariocanoy@priviflow.us
"""Quantum Mandates: a human's passkey-signed spending terms gate every paid quantum run."""
import base64
import io
import itertools
import json
import secrets
import time

import anyio
from cryptography.hazmat.primitives.asymmetric import mldsa
from mcp import Client

from privi_quantum.attest import Attestor
from privi_quantum.hardware import HardwareRouter, IonQBackend, LocalBackend
from privi_quantum.mandates import MandateError, QuantumMandates
from privi_quantum.server import Settings, build_server, http_app
from test_humans import Authenticator

JOBS = {"jobs": [{"name": n, "minutes": m} for n, m in zip("ABCDE", [3, 5, 7, 2, 4])]}
QPU = "ionq:qpu.forte-1"
PRICE = {"per_task": 0.3, "per_shot": 0.01}          # 100 shots = $1.30


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeIonQCloud:
    """api.ionq.co stand-in with many jobs: each completes (or fails, if asked) on its second poll."""

    def __init__(self):
        self.jobs, self.ids, self.fail_next = {}, itertools.count(1), False

    def __call__(self, req, timeout=30):
        url = req.full_url
        if req.get_method() == "POST":
            body = json.loads(req.data)
            jid = f"ionq-{next(self.ids)}"
            self.jobs[jid] = {"polls": 0, "fail": self.fail_next, "n": body["input"]["qubits"]}
            self.fail_next = False
            return _Resp(json.dumps({"id": jid, "status": "submitted"}).encode())
        if url.endswith("/results/probabilities"):
            jid = url.split("/jobs/")[1].split("/")[0]
            return _Resp(json.dumps({"0": 0.5, str(2 ** self.jobs[jid]["n"] - 1): 0.5}).encode())
        jid = url.rsplit("/", 1)[1]
        j = self.jobs[jid]
        j["polls"] += 1
        st = "ready" if j["polls"] == 1 else ("failed" if j["fail"] else "completed")
        return _Resp(json.dumps({"id": jid, "status": st, **({"failure": {"error": "device calibration"}} if j["fail"] else {})}).encode())


def test_quantum_mandates_end_to_end(tmp_path):
    from starlette.testclient import TestClient
    db = str(tmp_path / "m.db")
    cloud = FakeIonQCloud()
    router = HardwareRouter(db, [LocalBackend(), IonQBackend("k123", "qpu.forte-1", PRICE, opener=cloud)], daily_budget_usd=50)
    srv = build_server(Settings(db_path=db, rate_per_min=1000, mandate_id_over_usd=20), Attestor(db), None, None, router)
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

    # an agent with a quantum-safe identity, approved by a person with a passkey whose ID is verified
    e, = run(("qagent_enroll", {"name": "Plant Bot", "operator": "Acme Robotics", "public_key": pub}))
    aid, tok = e.structured_content["agent_id"], e.structured_content["agent_token"]
    ch, = run(("qagent_challenge", {"agent_id": aid, "agent_token": tok}))
    ch = ch.structured_content
    run(("qagent_scan", {"agent_id": aid, "agent_token": tok, "code": "x=1"}),
        ("qagent_prove", {"agent_id": aid, "agent_token": tok, "challenge_id": ch["challenge_id"], "signature": sign(ch["message"])}))
    rq, = run(("qagent_human_request", {"agent_id": aid, "agent_token": tok}))
    rid = rq.structured_content["request_id"]
    phone, stranger = Authenticator(), Authenticator()

    with TestClient(http_app(srv)) as http:
        opts = http.get(f"/humans/approve/{rid}/options").json()
        hid = http.post(f"/humans/approve/{rid}/finish", json=phone.create(opts)).json()["human_id"]
        humans._mark(hid, "verified", "stripe_identity", "vs_test")
        ts, nonce = int(time.time()), secrets.token_hex(12)
        p, = run(("inspector_pass", {"agent_id": aid, "ts": ts, "nonce": nonce,
                                     "signature": sign(f"privi-inspector:v1:{aid}:{ts}:{nonce}")}))
        assert not p.is_error, p.structured_content
        ppass = p.structured_content["privi_pass"]

        def hw(shots=100, **kw):
            r, = run(("quantum_run_hardware", {"problem": "balance_lines", "data": JOBS, "backend": QPU, "shots": shots, **kw}))
            return r

        # 1. paid hardware needs a mandate; free backends do not
        r = hw()
        assert r.is_error and "Quantum Mandate" in r.structured_content["error"]
        loc, = run(("quantum_run_hardware", {"problem": "balance_lines", "data": JOBS, "backend": "local"}))
        assert not loc.is_error and loc.structured_content["status"] == "done"

        # 2. the agent drafts terms; it must prove who it is
        bad, = run(("quantum_mandate_request", {"budget_usd": 10, "purpose": "nightly line balancing"}))
        assert bad.is_error
        terms = {"budget_usd": 10, "max_per_job_usd": 2, "backends": [QPU], "problems": ["balance_lines"],
                 "max_shots": 150, "days": 7, "purpose": "nightly line balancing", "privi_pass": ppass}
        assert run(("quantum_mandate_request", {**terms, "backends": ["ionq:nope"]}))[0].is_error
        assert run(("quantum_mandate_request", {**terms, "max_per_job_usd": 20}))[0].is_error
        d, = run(("quantum_mandate_request", terms))
        d = d.structured_content
        mid = d["mandate_id"]
        assert d["status"] == "draft" and d["sign_url"].endswith(f"/quantum-mandates/{mid}")
        assert "Total budget: $10.00" in d["terms_text"] and "Plant Bot" in d["terms_text"] and QPU in d["terms_text"]

        # a draft authorizes nothing
        r = hw(mandate_id=mid, privi_pass=ppass)
        assert r.is_error and "not signed" in r.structured_content["error"]

        # 3. the person reads and signs the exact terms with their passkey; nobody else can
        page = http.get(f"/quantum-mandates/{mid}").text
        assert "Waiting for your signature" in page and "Sign with my passkey" in page and "nightly line balancing" in page
        so = http.get(f"/quantum-mandates/{mid}/options?action=sign").json()
        assert so["get"]["userVerification"] == "required"
        assert http.post(f"/quantum-mandates/{mid}/sign", json=stranger.get(so)).status_code == 400
        ro = http.get(f"/quantum-mandates/{mid}/options?action=revoke").json()
        assert http.post(f"/quantum-mandates/{mid}/sign", json=phone.get(ro)).status_code == 400   # a revoke signature cannot sign
        signed = http.post(f"/quantum-mandates/{mid}/sign", json=phone.get(so)).json()
        assert signed["status"] == "active" and signed["attestation_id"].startswith("qa_")
        sealed = http.get(f"/attestations/{signed['attestation_id']}").json()
        assert sealed["body"]["kind"] == "quantum_mandate" and sealed["body"]["terms_sha256"] == d["terms_sha256"]
        assert http.post(f"/quantum-mandates/{mid}/sign", json=phone.get(so)).status_code == 400   # signs once

        # 4. dry run and enforcement of every term
        ok, = run(("quantum_mandate_check", {"mandate_id": mid, "backend": QPU, "shots": 100}))
        assert ok.structured_content["allowed"] and ok.structured_content["estimated_usd"] == 1.3
        too_many, = run(("quantum_mandate_check", {"mandate_id": mid, "backend": QPU, "shots": 160}))
        assert not too_many.structured_content["allowed"]
        assert hw(mandate_id=mid).is_error                                         # no pass, no spend
        r = hw(shots=150, mandate_id=mid, privi_pass=ppass)                         # $1.80 fits the $2 cap
        assert not r.is_error and r.structured_content["mandate"]["charged_usd"] == 1.8
        r = hw(mandate_id=mid, privi_pass=ppass, problem="select_lots",
               data={"lots": [{"name": f"L{i}", "risk": i} for i in range(5)], "k": 2})
        assert r.is_error and "problem select_lots is not allowed" in r.structured_content["error"]

        # 5. a job the provider fails is refunded to the mandate and to the operator's daily budget
        cloud.fail_next = True
        f = hw(mandate_id=mid, privi_pass=ppass).structured_content
        before = run(("quantum_mandate_status", {"mandate_id": mid}))[0].structured_content["spent_usd"]
        assert before == 3.1
        for _ in range(2):
            j, = run(("quantum_hardware_job", {"job_id": f["job_id"]}))
        assert j.structured_content["status"] == "failed" and j.structured_content["mandate"]["status"] == "refunded"
        st = run(("quantum_mandate_status", {"mandate_id": mid}))[0].structured_content
        assert st["spent_usd"] == 1.8 and {s["status"] for s in st["spends"]} == {"charged", "refunded"}
        assert router.spent_today() == 1.8

        # 6. the budget is a hard ceiling: $10 - $1.80 leaves room for six $1.30 runs, not seven
        runs = 0
        while not hw(mandate_id=mid, privi_pass=ppass).is_error:
            runs += 1
        assert runs == 6
        r = hw(mandate_id=mid, privi_pass=ppass)
        assert "left in the budget" in r.structured_content["error"]

        # 7. the person revokes with their passkey; the revocation is sealed and every run stops
        ro = http.get(f"/quantum-mandates/{mid}/options?action=revoke").json()
        rv = http.post(f"/quantum-mandates/{mid}/revoke", json=phone.get(ro)).json()
        assert rv["status"] == "revoked" and rv["revoked_by"] == "human" and rv["revocation_attestation_id"]
        assert "mandate was revoked" in hw(mandate_id=mid, privi_pass=ppass).structured_content["error"]
        js = http.get(f"/quantum-mandates/{mid}.json")
        assert js.headers["access-control-allow-origin"] == "*" and js.json()["status"] == "revoked"
        assert "Revoked" in http.get(f"/quantum-mandates/{mid}").text

        # 8. big budgets need a verified ID; the agent can also give up its own mandate
        big, = run(("quantum_mandate_request", {**terms, "budget_usd": 25, "max_per_job_usd": 5}))
        big = big.structured_content
        assert big["needs_id_verification"]
        humans.revoke_id(hid)
        bo = http.get(f"/quantum-mandates/{big['mandate_id']}/options?action=sign").json()
        refused = http.post(f"/quantum-mandates/{big['mandate_id']}/sign", json=phone.get(bo))
        assert refused.status_code == 400 and "ID verified" in refused.json()["error"]
        humans._mark(hid, "verified", "stripe_identity", "vs_test2")
        assert http.post(f"/quantum-mandates/{big['mandate_id']}/sign", json=phone.get(bo)).json()["status"] == "active"
        gone, = run(("quantum_mandate_revoke", {"mandate_id": big["mandate_id"], "privi_pass": ppass, "reason": "job finished"}))
        assert not gone.is_error and gone.structured_content["status"] == "revoked"

        st = run(("quantum_status", {}))[0].structured_content
        assert st["version"] == "0.9.0" and st["quantum_mandates"]["required_for_paid_backends"] is True
        feed = http.get("/explorer/recent").json()
        assert feed["by_kind"]["quantum_mandate"] == 2 and feed["by_kind"]["quantum_mandate_revocation"] == 2


def test_mandate_rules_unit(tmp_path):
    m = QuantumMandates(str(tmp_path / "u.db"), id_required_over_usd=100)
    agent = {"agent_id": "qagent_1", "name": "Bot", "operator": "Acme"}
    known = {QPU: "IonQ Forte"}
    d = m.draft(agent, "human_1", "50", None, [], [], 1000, 30, "test runs", known, ["balance_lines"])
    mid = d["mandate_id"]
    assert d["terms"]["max_per_job_usd"] == 50 and d["terms"]["backends"] == "any paid backend"
    for bad in [("0", None), ("-5", None), ("abc", None), ("10", "20")]:
        try:
            m.draft(agent, "human_1", bad[0], bad[1], [], [], 1000, 30, "x runs", known, ["balance_lines"])
            raise AssertionError(bad)
        except MandateError:
            pass
    try:
        m.activate(mid, "human_2", "cred", True)
        raise AssertionError("someone else signed")
    except MandateError as e:
        assert "only the person" in str(e)
    m.activate(mid, "human_1", "cred", False)                      # $50 is under the $100 ID threshold
    assert m.decide(mid, "qagent_2", QPU, 1, 10, "balance_lines")["reasons"] == ["this mandate belongs to a different agent"]
    assert m.decide(mid, "qagent_1", QPU, 1, 10, "balance_lines")["allowed"]
    m._db.execute("UPDATE qmandates SET expires_at='2020-01-01T00:00:00+00:00' WHERE mandate_id=?", (mid,))
    assert m.decide(mid, "qagent_1", QPU, 1, 10, "balance_lines")["reasons"] == ["mandate expired"]
    assert m.public(mid)["status"] == "expired"
