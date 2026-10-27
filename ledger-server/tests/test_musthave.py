"""Privi AI Act Pack, Supplier Proof and Content Seal."""

import hashlib
import json
from datetime import date

import anyio
from mcp import Client

from privi_ledger.ai_act import classify
from privi_ledger.config import Settings
from privi_ledger.server import build_server
from test_ledger import PAY_TO, FakeAnchor, FakeFacilitator

ALL_CLEAR = {p: False for p in (
    "harmful_manipulation", "exploiting_vulnerabilities", "social_scoring", "predictive_policing_profiling",
    "untargeted_face_scraping", "workplace_school_emotion_recognition", "biometric_categorisation_sensitive",
    "realtime_remote_biometric_id_public", "non_consensual_intimate_imagery")}


def _caller(ledger, anchor=None):
    srv = build_server(Settings(pay_to=PAY_TO), ledger, FakeFacilitator(), anchor_client=anchor or FakeAnchor())

    def run(tool, args):
        async def go():
            async with Client(srv) as c:
                return await c.call_tool(tool, args)
        return anyio.run(go)
    return srv, run


def test_ai_act_classify_tiers():
    assert classify({"prohibited_screen": {"social_scoring": True}})["tier"] == "prohibited"
    hr = classify({"role": "deployer", "annex_iii_area": "employment"})
    assert hr["tier"] == "high_risk"
    ids = {o["id"]: o["applies_from"] for o in hr["obligations"]}
    assert ids["keep_logs_6_months"] == "2027-12-02" and "inform_workers" in ids and "risk_management" not in ids
    emb = classify({"role": "provider", "annex_i_product": True})
    assert {o["applies_from"] for o in emb["obligations"] if o["id"] == "risk_management"} == {"2028-08-02"}
    chat = classify({"role": "provider", "interacts_with_people": True, "generates_synthetic_content": True})
    assert chat["tier"] == "transparency"
    assert {o["id"] for o in chat["obligations"]} == {"ai_literacy", "disclose_ai_interaction", "mark_synthetic_content"}
    derog = classify({"role": "deployer", "annex_iii_area": "education", "not_high_risk_justification": "narrow task"})
    assert derog["tier"] == "annex_iii_not_high_risk" and "keep_logs_6_months" not in {o["id"] for o in derog["obligations"]}


def test_ai_act_register_check_export_verify(ledger, monkeypatch):
    acme = ledger.create_org("Acme Robotics")
    monkeypatch.setenv("LEDGER_LOCAL_ORG_KEY", acme["api_key"])
    anchor = FakeAnchor()
    _, run = _caller(ledger, anchor)
    bot = {"system_id": "support-bot", "name": "Support chatbot", "role": "provider_and_deployer", "used_in_eu": True,
           "interacts_with_people": True, "generates_synthetic_content": True, "prohibited_screen": ALL_CLEAR}
    s1 = run("ai_act_system_save", {"system": bot, "actor": "compliance"}).structured_content
    assert s1["version"] == 1 and s1["classification"]["tier"] == "transparency"
    assert run("ai_act_system_save", {"system": {**bot, "role": "boss"}, "actor": "x"}).is_error
    assert run("ai_act_system_save", {"system": {"system_id": "x", "controls": {"nope": {"done": True}}}, "actor": "x"}).is_error

    chk = run("ai_act_check", {}).structured_content
    crit = [f["finding"] for f in chk["findings"] if f["severity"] == "critical"]
    assert any("Art. 4" in f for f in crit) and any("Art. 50(1)" in f for f in crit)   # in force since Feb / Aug 2026
    assert chk["compliant_today"] is False

    run("ai_act_system_save", {"actor": "compliance", "system": {"system_id": "support-bot", "controls": {
        "ai_literacy": {"done": True, "evidence": "Training log 2026-09"},
        "disclose_ai_interaction": {"done": True, "evidence": "Banner 'You are chatting with AI'"},
        "mark_synthetic_content": {"done": True, "evidence": "C2PA manifests on images"}}}})
    assert run("ai_act_check", {}).structured_content["compliant_today"] is True

    ex = run("ai_act_export", {}).structured_content
    assert ex["attestation"]["anchored"] and anchor.calls[-1] == [ex["export_hash"]]
    doc = json.loads(ex["register_json"])
    assert doc["systems"][0]["tier"] == "transparency" and all(o["met"] for o in doc["systems"][0]["obligations"])
    v = run("ai_act_verify_export", {"register_json": ex["register_json"]}).structured_content
    assert v["valid"] and v["systems"] == 1
    tampered = ex["register_json"].replace('"transparency"', '"minimal"')
    assert run("ai_act_verify_export", {"register_json": tampered}).structured_content["valid"] is False
    assert [e["seq"] for e in ledger.entries(acme["org_id"], "ai-act")] == [1, 2, 3]


def test_ai_act_high_risk_upcoming_and_logs(ledger):
    from privi_ledger.ai_act import AIActRegister
    reg = AIActRegister(ledger)
    org = ledger.create_org("Hireco")["org_id"]
    reg.upsert(org, "hr", {"system_id": "cv-screen", "role": "deployer", "annex_iii_area": "employment",
                           "prohibited_screen": ALL_CLEAR, "controls": {"ai_literacy": {"done": True, "evidence": "x"}}})
    far = reg.check(org, today=date(2026, 10, 26))
    assert far["compliant_today"] and far["finding_counts"]["upcoming"] >= 5
    assert any("no Privi Ledger log linked" in f["finding"] for f in far["findings"])
    near = reg.check(org, today=date(2027, 12, 3))
    assert not near["compliant_today"] and any("Art. 26(6)" in f["finding"] for f in near["findings"] if f["severity"] == "critical")


def test_supplier_proof_full_flow(ledger, monkeypatch):
    buyer, supplier, other = ledger.create_org("Big Buyer"), ledger.create_org("Small Parts"), ledger.create_org("Other")
    anchor = FakeAnchor()
    _, run = _caller(ledger, anchor)
    doc = hashlib.sha256(b"iso cert pdf").hexdigest()

    monkeypatch.setenv("LEDGER_LOCAL_ORG_KEY", buyer["api_key"])
    req = run("supplier_requirement_create", {"title": "Approved supplier 2027", "items": [
        {"key": "iso_9001", "label": "ISO 9001 certificate"},
        {"key": "traceability", "label": "Lot traceability statement", "document_required": False}]}).structured_content
    rid = req["req_id"]
    assert req["invite_url"].endswith(f"/supplier/requirements/{rid}")
    assert run("supplier_requirement_get", {"req_id": rid}).structured_content["buyer"]["name"] == "Big Buyer"
    # buyer cannot certify itself
    assert run("supplier_proof_submit", {"req_id": rid, "evidence": {"iso_9001": {"sha256": doc},
                                                                    "traceability": {"note": "x"}}}).is_error

    monkeypatch.setenv("LEDGER_LOCAL_ORG_KEY", supplier["api_key"])
    assert run("supplier_proof_submit", {"req_id": rid, "evidence": {"iso_9001": {"sha256": "abc"}}}).is_error
    sub = run("supplier_proof_submit", {"req_id": rid, "evidence": {
        "iso_9001": {"sha256": doc, "valid_until": "2028-01-31"},
        "traceability": {"note": "Every lot on Privi ChainFlow"}}}).structured_content
    assert sub["status"] == "pending"

    monkeypatch.setenv("LEDGER_LOCAL_ORG_KEY", other["api_key"])
    assert run("supplier_proof_decide", {"sub_id": sub["sub_id"], "approve": True}).is_error   # not the buyer

    monkeypatch.setenv("LEDGER_LOCAL_ORG_KEY", buyer["api_key"])
    assert len(run("supplier_proof_inbox", {}).structured_content["submissions"]) == 1
    cert = run("supplier_proof_decide", {"sub_id": sub["sub_id"], "approve": True}).structured_content
    cid = cert["cert_id"]
    assert cert["attestation"]["anchored"] and anchor.calls[-1] == [cert["body_hash"]]
    assert cert["certificate"]["supplier"]["name"] == "Small Parts"
    assert run("supplier_proof_decide", {"sub_id": sub["sub_id"], "approve": True}).is_error   # already decided

    v = run("supplier_cert_verify", {"cert_id": cid, "document_sha256": doc}).structured_content
    assert v["valid"] and v["document_matches"] == ["iso_9001"]
    assert run("supplier_cert_verify", {"cert_id": cid, "document_sha256": "0" * 64}).structured_content["document_matches"] == []

    monkeypatch.setenv("LEDGER_LOCAL_ORG_KEY", supplier["api_key"])
    held = run("supplier_certs", {}).structured_content["certificates"]
    assert held[0]["as"] == "supplier" and held[0]["counterparty"] == "Big Buyer"
    assert run("supplier_cert_revoke", {"cert_id": cid, "reason": "x"}).is_error   # only the buyer revokes

    monkeypatch.setenv("LEDGER_LOCAL_ORG_KEY", buyer["api_key"])
    run("supplier_cert_revoke", {"cert_id": cid, "reason": "Certificate lapsed"})
    v2 = run("supplier_cert_verify", {"cert_id": cid}).structured_content
    assert v2["valid"] is False and v2["revoked"] and v2["untampered"]
    assert len(ledger.entries(supplier["org_id"], "supplier-proof")) == 3   # submitted, issued, revoked


def test_supplier_reject_needs_reason(ledger, monkeypatch):
    buyer, supplier = ledger.create_org("B"), ledger.create_org("S")
    _, run = _caller(ledger)
    monkeypatch.setenv("LEDGER_LOCAL_ORG_KEY", buyer["api_key"])
    rid = run("supplier_requirement_create", {"title": "Insurance", "items": [
        {"key": "coi", "label": "Certificate of insurance"}]}).structured_content["req_id"]
    monkeypatch.setenv("LEDGER_LOCAL_ORG_KEY", supplier["api_key"])
    sid = run("supplier_proof_submit", {"req_id": rid, "evidence": {"coi": {"sha256": "a" * 64}}}).structured_content["sub_id"]
    monkeypatch.setenv("LEDGER_LOCAL_ORG_KEY", buyer["api_key"])
    assert run("supplier_proof_decide", {"sub_id": sid, "approve": False}).is_error
    r = run("supplier_proof_decide", {"sub_id": sid, "approve": False, "reason": "Expired policy"}).structured_content
    assert r["status"] == "rejected"


def test_content_seal(ledger, monkeypatch):
    acme = ledger.create_org("Acme News")
    monkeypatch.setenv("LEDGER_LOCAL_ORG_KEY", acme["api_key"])
    anchor = FakeAnchor()
    _, run = _caller(ledger, anchor)
    photo = hashlib.sha256(b"photo bytes").hexdigest()
    assert run("seal_content", {"items": [{"sha256": photo, "origin": "ai_generated"}]}).is_error   # needs ai_tool
    assert run("seal_content", {"items": [{"sha256": "xyz", "origin": "human"}]}).is_error
    r = run("seal_content", {"items": [
        {"sha256": photo, "origin": "human", "title": "Factory photo", "author": "Dana"},
        {"text": "Press release: Q3 results", "origin": "ai_assisted", "ai_tool": "Claude"}]}).structured_content
    assert len(r["sealed"]) == 2 and all(s["anchored"] for s in r["sealed"])
    assert len(anchor.calls[-1]) == 2   # one on-chain anchor for the whole batch

    monkeypatch.delenv("LEDGER_LOCAL_ORG_KEY")
    v = run("seal_verify", {"sha256": photo}).structured_content
    assert v["sealed"] and v["first_sealed_by"] == "Acme News" and v["ai_involved"] is False
    t = run("seal_verify", {"text": "Press release: Q3 results"}).structured_content
    assert t["sealed"] and t["ai_involved"] is True
    assert run("seal_verify", {"text": "Press release: Q3 results!"}).structured_content["sealed"] is False

    monkeypatch.setenv("LEDGER_LOCAL_ORG_KEY", acme["api_key"])
    sid = run("seal_list", {}).structured_content["seals"][-1]["seal_id"]
    run("seal_revoke", {"seal_id": sid, "reason": "wrong file"})
    assert run("seal_verify", {"sha256": photo}).structured_content["sealed"] is False


def test_http_routes(ledger, monkeypatch):
    from starlette.testclient import TestClient
    acme = ledger.create_org("Acme")
    monkeypatch.setenv("LEDGER_LOCAL_ORG_KEY", acme["api_key"])
    srv, run = _caller(ledger)
    h = hashlib.sha256(b"x").hexdigest()
    run("seal_content", {"items": [{"sha256": h, "origin": "human"}]})
    app = srv.streamable_http_app(host="0.0.0.0", stateless_http=True, json_response=True)
    c = TestClient(app)
    assert "Is this file real?" in c.get("/seal/check").text
    assert c.get(f"/seal/{h}").json()["sealed"] is True
    assert "sealed: human" in c.get(f"/seal/{h}/badge.svg").text
    assert c.get("/seal/nothex").status_code == 400
    assert c.get("/certs/spc_missing").status_code == 404
