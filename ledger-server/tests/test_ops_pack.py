"""Privi Ops Pack: Trust Page, Incident Clock, Policy Sign-off, Control Calendar, Release Seal."""

import hashlib
from datetime import datetime, timedelta, timezone

import anyio
from mcp import Client
from starlette.testclient import TestClient

from privi_ledger.config import Settings
from privi_ledger.ops_pack import add_business_days
from privi_ledger.server import build_server
from test_ledger import PAY_TO, FakeAnchor, FakeFacilitator, as_org


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


def _setup(ledger, monkeypatch):
    org = ledger.create_org("Acme Tooling")
    as_org(monkeypatch, org["api_key"])
    anchor = FakeAnchor()
    srv = build_server(Settings(pay_to=PAY_TO), ledger, FakeFacilitator(), anchor_client=anchor)

    def run(tool, args):
        async def go():
            async with Client(srv) as c:
                return await c.call_tool(tool, args)
        return anyio.run(go)
    return org, srv, run, anchor


def test_trust_page(ledger, monkeypatch):
    org, srv, run, _ = _setup(ledger, monkeypatch)
    ledger.record(org["org_id"], "bot", "bot", "message", "hi")
    r = run("trust_page_publish", {"slug": "acme-tooling", "headline": "ISO 9001 shop in Port Huron",
                                   "claims": [{"label": "ISO 9001", "document_sha256": sha("cert"),
                                               "valid_until": "2020-01-01T00:00:00Z"}, {"label": "Insured"}]})
    assert not r.is_error, r
    page = r.structured_content
    assert page["company"] == "Acme Tooling" and page["claims"][0]["expired"] and not page["claims"][1]["expired"]
    assert page["logs"]["all_intact"] is True and page["logs"]["entries"] >= 2
    assert run("trust_page_publish", {"slug": "Bad Slug!", "headline": "abc", "claims": []}).is_error
    other = ledger.create_org("Other Co")
    as_org(monkeypatch, other["api_key"])
    assert "already used" in run("trust_page_publish", {"slug": "acme-tooling", "headline": "mine", "claims": []}).structured_content["error"]
    as_org(monkeypatch, None)
    assert run("trust_page_view", {"slug": "acme-tooling"}).structured_content["headline"].startswith("ISO")
    http = TestClient(srv.streamable_http_app())
    assert "Acme Tooling" in http.get("/trust/acme-tooling").text
    assert http.get("/trust/acme-tooling?format=json").json()["slug"] == "acme-tooling"
    assert http.get("/trust/nope").status_code == 404


def test_business_days_skip_weekend():
    fri = datetime(2026, 11, 13, 15, 0, tzinfo=timezone.utc)          # a Friday
    assert add_business_days(fri, 4) == datetime(2026, 11, 19, 15, 0, tzinfo=timezone.utc)


def test_incident_clock(ledger, monkeypatch):
    org, _, run, anchor = _setup(ledger, monkeypatch)
    aware = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
    r = run("incident_open", {"title": "Customer database exposed", "severity": "high", "actor": "dario",
                              "regimes": ["gdpr", "nis2", "sec_8k"], "aware_at": aware, "contract_hours": 48})
    assert not r.is_error, r
    inc = r.structured_content
    by = {f"{c['regime']}.{c['step']}": c for c in inc["clocks"]}
    assert by["nis2.early_warning"]["status"] == "overdue" and inc["overdue"] == ["early_warning"]
    assert by["gdpr.authority_notification"]["status"] == "running" and 41 < by["gdpr.authority_notification"]["hours_left"] <= 42
    assert by["sec_8k.form_8k"]["status"] == "not_started" and by["contract.notify"]["status"] == "running"
    iid = inc["incident_id"]
    assert run("incident_update", {"incident_id": iid, "note": "x1", "actor": "dario", "completed_step": "gdpr.nope"}).is_error
    u = run("incident_update", {"incident_id": iid, "note": "Told the authority", "actor": "dario",
                                "completed_step": "gdpr.authority_notification",
                                "material_at": datetime.now(timezone.utc).isoformat()}).structured_content
    by = {f"{c['regime']}.{c['step']}": c for c in u["clocks"]}
    assert by["gdpr.authority_notification"]["status"] == "done" and by["sec_8k.form_8k"]["status"] == "running"
    assert len(u["timeline"]) == 1 and len(u["timeline"][0]["entry_hash"]) == 64
    assert run("incident_status", {}).structured_content["incidents"][0]["incident_id"] == iid
    c = run("incident_close", {"incident_id": iid, "root_cause": "Open storage bucket; now private", "actor": "dario"})
    assert not c.is_error, c
    out = c.structured_content
    assert out["report_hash"] == sha(out["report_json"]) and out["attestation"]["anchored"] and anchor.calls == [[out["report_hash"]]]
    assert out["incident"]["status"] == "closed"
    assert run("incident_update", {"incident_id": iid, "note": "late", "actor": "x"}).is_error
    assert ledger.audit(org["org_id"], "incidents")["intact"]
    as_org(monkeypatch, ledger.create_org("Other")["api_key"])
    assert run("incident_status", {"incident_id": iid}).is_error       # other companies cannot read it


def test_policy_signoff(ledger, monkeypatch):
    _, _, run, _ = _setup(ledger, monkeypatch)
    v1, v2 = sha("policy v1"), sha("policy v2")
    assert run("policy_publish", {"policy_id": "acceptable-use", "title": "Acceptable use", "document_sha256": v1,
                                  "actor": "dario"}).structured_content["version"] == 1
    assert not run("policy_acknowledge", {"policy_id": "acceptable-use", "person": "chad", "document_sha256": v1}).is_error
    assert run("policy_acknowledge", {"policy_id": "acceptable-use", "person": "chad", "document_sha256": v1}).is_error
    st = run("policy_status", {"policy_id": "acceptable-use", "required_people": ["chad", "dario"]}).structured_content
    assert st["missing"] == ["dario"] and st["complete"] is False
    assert run("policy_publish", {"policy_id": "acceptable-use", "title": "Acceptable use", "document_sha256": v2,
                                  "actor": "dario"}).structured_content["version"] == 2
    # the old document can no longer be signed, and old sign-offs do not carry over
    assert run("policy_acknowledge", {"policy_id": "acceptable-use", "person": "dario", "document_sha256": v1}).is_error
    st = run("policy_status", {"policy_id": "acceptable-use", "required_people": ["chad"]}).structured_content
    assert st["version"] == 2 and st["missing"] == ["chad"]


def test_control_calendar(ledger, monkeypatch):
    _, _, run, _ = _setup(ledger, monkeypatch)
    c = run("control_save", {"control_id": "access-review", "title": "Quarterly access review", "every_days": 90,
                             "owner": "chad", "actor": "dario", "reference": "SOC 2 CC6.2"}).structured_content
    assert c["status"] == "never_done"
    run("control_save", {"control_id": "backup-test", "title": "Backup restore test", "every_days": 30, "owner": "dario", "actor": "dario"})
    old = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
    assert not run("control_evidence", {"control_id": "backup-test", "performed_by": "dario", "document_sha256": sha("b"),
                                        "performed_at": old}).is_error
    assert not run("control_evidence", {"control_id": "access-review", "performed_by": "chad", "document_sha256": sha("a")}).is_error
    assert run("control_evidence", {"control_id": "nope", "performed_by": "chad", "document_sha256": sha("a")}).is_error
    future = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    assert run("control_evidence", {"control_id": "backup-test", "performed_by": "d", "document_sha256": sha("b"), "performed_at": future}).is_error
    due = run("controls_due", {}).structured_content
    st = {c["control_id"]: c["status"] for c in due["controls"]}
    assert st == {"access-review": "ok", "backup-test": "overdue"} and due["all_current"] is False
    assert run("controls_due", {"soon_days": 120}).structured_content["counts"]["due_soon"] == 1


def test_release_seal(ledger, monkeypatch):
    _, srv, run, anchor = _setup(ledger, monkeypatch)
    files = [{"name": "app-1.0.0.zip", "sha256": sha("zip")}, {"name": "app-1.0.0.exe", "sha256": sha("exe")}]
    r = run("release_seal", {"product": "ChainFlow", "version": "1.0.0", "files": files, "actor": "dario", "commit": "6a78ec3"})
    assert not r.is_error, r
    out = r.structured_content
    assert out["attestation"]["anchored"] and anchor.calls == [[out["release_hash"]]]
    assert "already sealed" in run("release_seal", {"product": "ChainFlow", "version": "1.0.0", "files": files, "actor": "d"}).structured_content["error"]
    as_org(monkeypatch, None)
    ok = run("release_check", {"file_sha256": sha("zip")}).structured_content
    assert ok["genuine"] and ok["releases"][0]["product"] == "ChainFlow" and ok["releases"][0]["file_name"] == "app-1.0.0.zip"
    assert run("release_check", {"file_sha256": sha("tampered")}).structured_content["genuine"] is False
    http = TestClient(srv.streamable_http_app())
    assert http.get(f"/releases/check/{sha('exe')}").json()["genuine"] and http.get(f"/releases/check/{sha('x')}").status_code == 404
    assert http.get("/releases/check/zz").status_code == 400
