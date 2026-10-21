import json
import os
import sqlite3

import anyio
import pytest
from mcp import Client

from privi_ledger.config import Settings
from privi_ledger.server import build_server
from privi_ledger.store import Ledger

PAY_TO = "0x1990589FD200E043b8C6FD9ec5956c61b3071048"


class FakeFacilitator:
    def __init__(self):
        self.calls = []

    async def verify(self, payload, req):
        self.calls.append("verify")
        return {"isValid": True}

    async def settle(self, payload, req):
        self.calls.append("settle")
        return {"success": True, "transaction": "0x" + "ab" * 32, "network": req["network"]}


@pytest.fixture
def ledger(tmp_path):
    return Ledger(str(tmp_path / "l.db"))


def server(ledger, fac=None, **kw):
    return build_server(Settings(pay_to=PAY_TO, **kw), ledger, fac or FakeFacilitator())


def as_org(monkeypatch, key):
    """Over in-process (stdio-like) transport the org key comes from LEDGER_LOCAL_ORG_KEY."""
    if key is None:
        monkeypatch.delenv("LEDGER_LOCAL_ORG_KEY", raising=False)
    else:
        monkeypatch.setenv("LEDGER_LOCAL_ORG_KEY", key)


def test_record_read_and_receipt(ledger, monkeypatch):
    acme = ledger.create_org("Acme")
    as_org(monkeypatch, acme["api_key"])

    async def go():
        async with Client(server(ledger)) as c:
            r1 = await c.call_tool("ledger_record_action", {
                "stream_id": "billing-agent", "actor": "claude", "action_type": "payment",
                "summary": "Paid invoice 1042", "resource": "inv_1042", "details": {"usd": 120.5}})
            assert not r1.is_error, r1
            e1 = r1.structured_content["entry"]
            assert e1["seq"] == 1 and e1["details"] == {"usd": 120.5}
            await c.call_tool("ledger_record_action", {
                "stream_id": "billing-agent", "actor": "claude", "action_type": "message",
                "summary": "Emailed receipt", "outcome": "failure"})
            read = (await c.call_tool("ledger_read_stream", {"stream_id": "billing-agent"})).structured_content
            assert [e["seq"] for e in read["entries"]] == [1, 2] and read["integrity"]["intact"]
            assert read["entries"][1]["prev_hash"] == e1["entry_hash"]
            streams = (await c.call_tool("ledger_list_streams", {})).structured_content
            assert streams["streams"][0]["entries"] == 2
            rc = (await c.call_tool("ledger_check_receipt", {"entry_hash": e1["entry_hash"]})).structured_content
            assert rc["found"] and rc["seq"] == 1 and "summary" not in rc
    anyio.run(go)


def test_auth_and_org_isolation(ledger, monkeypatch):
    acme, other = ledger.create_org("Acme"), ledger.create_org("Other")
    ledger.record(acme["org_id"], "agent-a", "claude", "tool_call", "secret thing")

    async def call(name, args):
        async with Client(server(ledger)) as c:
            return await c.call_tool(name, args)

    as_org(monkeypatch, None)
    assert anyio.run(call, "ledger_list_streams", {}).is_error
    as_org(monkeypatch, "plk_wrong")
    assert anyio.run(call, "ledger_record_action", {
        "stream_id": "x", "actor": "y", "action_type": "other", "summary": "z"}).is_error
    as_org(monkeypatch, other["api_key"])
    r = anyio.run(call, "ledger_read_stream", {"stream_id": "agent-a"}).structured_content
    assert r["entries"] == []  # other org cannot see Acme's stream
    # keys are stored hashed
    raw = sqlite3.connect(ledger._db.execute("PRAGMA database_list").fetchone()[2])
    assert acme["api_key"] not in str(raw.execute("SELECT * FROM orgs").fetchall())


def test_paid_audit_and_tamper_detection(ledger, tmp_path):
    acme = ledger.create_org("Acme")
    for i in range(3):
        ledger.record(acme["org_id"], "ops-agent", "claude", "data_change", f"step {i}")
    fac = FakeFacilitator()

    async def go():
        async with Client(server(ledger, fac)) as c:
            args = {"org_id": acme["org_id"], "stream_id": "ops-agent"}
            need = await c.call_tool("ledger_audit_stream", args)
            assert need.is_error and need.structured_content["accepts"][0]["amount"] == "20000"
            pay = {"x402Version": 2, "resource": need.structured_content["resource"],
                   "accepted": need.structured_content["accepts"][0], "payload": {}}
            ok = await c.call_tool("ledger_audit_stream", args, meta={"x402/payment": pay})
            a = ok.structured_content
            assert a["intact"] and a["entry_count"] == 3 and "summary" not in str(a)
            assert ok.meta["x402/payment-response"]["success"] and fac.calls == ["verify", "settle"]

            db = sqlite3.connect(str(tmp_path / "l.db"))
            db.execute("UPDATE entries SET summary='edited' WHERE seq=2"); db.commit()
            bad = (await c.call_tool("ledger_audit_stream", args, meta={"x402/payment": pay})).structured_content
            assert bad["intact"] is False and bad["broken_at_seq"] == 2

            db.execute("DELETE FROM entries WHERE seq=2"); db.commit()
            gone = (await c.call_tool("ledger_audit_stream", args, meta={"x402/payment": pay})).structured_content
            assert gone["intact"] is False and gone["broken_at_seq"] == 3
    anyio.run(go)


def test_validation(ledger):
    org = ledger.create_org("Acme")["org_id"]
    for bad in [dict(action_type="hack"), dict(outcome="maybe"), dict(stream_id="has space"),
                dict(details={"x": "y" * 20000}), dict(summary="  ")]:
        args = dict(stream_id="s", actor="a", action_type="other", summary="ok") | bad
        with pytest.raises(ValueError):
            ledger.record(org, **args)


class FakeAnchor:
    def __init__(self):
        self.calls = []

    def anchor(self, hashes, label):
        self.calls.append(list(hashes))
        return {"status": "confirmed", "merkle_root": "ab" * 32, "tx_hash": "0x" + "cd" * 32,
                "block_number": 58200, "block_time": 1792466000,
                "receipts": [{"hash": h, "proof": [], "tx_hash": "0x" + "cd" * 32} for h in hashes]}


def test_onchain_checkpoint_catches_consistent_rewrite(ledger, tmp_path):
    from privi_ledger.anchoring import Checkpoints
    from privi_ledger.store import fingerprint, GENESIS

    org = ledger.create_org("Acme")["org_id"]
    for i in range(3):
        ledger.record(org, "ops", "claude", "data_change", f"step {i}")
    cps, fake = Checkpoints(ledger._db, ledger._lock), FakeAnchor()
    assert cps.run_once(ledger.heads(), fake, "privi-ledger") == 1
    assert cps.run_once(ledger.heads(), fake, "privi-ledger") == 0      # nothing new
    ledger.record(org, "ops", "claude", "data_change", "step 3")
    assert cps.run_once(ledger.heads(), fake, "privi-ledger") == 1      # new head only

    async def audit():
        async with Client(server(ledger, payments_enabled=False)) as c:
            return (await c.call_tool("ledger_audit_stream", {"org_id": org, "stream_id": "ops"})).structured_content

    a = anyio.run(audit)
    assert a["intact"] and a["onchain_checkpoint"]["anchored"] and a["onchain_checkpoint"]["matches_current_record"]
    assert a["onchain_checkpoint"]["seq"] == 4 and a["onchain_checkpoint"]["verify_with"]["tool"] == "anchor_verify"

    # Rewrite entry 2 AND recompute every later hash, so the local chain is internally consistent.
    db = sqlite3.connect(str(tmp_path / "l.db")); db.row_factory = sqlite3.Row
    rows = [dict(r) for r in db.execute("SELECT * FROM entries WHERE org_id=? ORDER BY seq", (org,))]
    prev = GENESIS
    for r in rows:
        if r["seq"] == 2:
            r["summary"] = "step 1 (quietly edited)"
        r["prev_hash"] = prev
        r["entry_hash"] = fingerprint(r)
        prev = r["entry_hash"]
        db.execute("UPDATE entries SET summary=?, prev_hash=?, entry_hash=? WHERE id=?",
                   (r["summary"], r["prev_hash"], r["entry_hash"], r["id"]))
    db.commit()
    assert ledger.check_chain(ledger.entries(org, "ops")).valid      # local check alone is fooled
    b = anyio.run(audit)
    assert b["intact"] is False and "anchored on the Privi chain" in b["reason"]
    assert b["onchain_checkpoint"]["matches_current_record"] is False


class FakeAnchorWithVerify(FakeAnchor):
    def verify(self, hash_hex, tx_hash, proof):
        return {"verified": any(hash_hex in c for c in self.calls), "block_number": 58200,
                "block_time_utc": "2026-10-20T03:50:00Z"}


def test_compliance_report_sealed_and_verifiable(ledger, monkeypatch):
    import copy
    acme = ledger.create_org("Acme")
    org = acme["org_id"]
    ledger.record(org, "billing-agent", "claude", "payment", "Paid invoice 7")
    ledger.record(org, "billing-agent", "claude", "message", "Emailed customer", outcome="failure")
    ledger.record(org, "support-agent", "claude", "data_access", "Read ticket 9")
    ledger.record(org, "support-agent", "dana", "approval", "Approved refund")
    as_org(monkeypatch, acme["api_key"])
    fake = FakeAnchorWithVerify()

    async def go():
        srv = build_server(Settings(pay_to=PAY_TO), ledger, FakeFacilitator(), anchor_client=fake)
        async with Client(srv) as c:
            r = (await c.call_tool("ledger_compliance_report", {})).structured_content
            rep, att = r["report"], r["attestation"]
            assert rep["totals"]["entries"] == 4 and rep["totals"]["failures"] == 1 and rep["totals"]["approvals"] == 1
            assert rep["status"] == "attention_required"          # billing-agent: sensitive actions, no approval; not anchored
            sev = {(f["stream_id"], f["severity"]) for f in rep["findings"]}
            assert ("billing-agent", "medium") in sev
            assert att["anchored"] and fake.calls == [[att["report_hash"]]]
            assert "# AI Agent Activity Report: Acme" in r["markdown"] and att["report_hash"] in r["markdown"]

            ok = (await c.call_tool("ledger_verify_report", {"report": rep})).structured_content
            assert ok["valid"] and ok["onchain_verified"] and ok["report_id"] == r["report_id"]

            edited = copy.deepcopy(rep)
            edited["totals"]["failures"] = 0                       # someone hides the failure
            bad = (await c.call_tool("ledger_verify_report", {"report": edited})).structured_content
            assert bad["valid"] is False and "edited" in bad["reason"]

            # period filter and stream filter
            only = (await c.call_tool("ledger_compliance_report", {"streams": ["support-agent"]})).structured_content
            assert [s["stream_id"] for s in only["report"]["streams"]] == ["support-agent"]
            future = (await c.call_tool("ledger_compliance_report", {"since": "2999-01-01T00:00:00Z"})).structured_content
            assert future["report"]["totals"]["entries"] == 0

        monkeypatch.setenv("LEDGER_LOCAL_ORG_KEY", "plk_wrong")
        async with Client(srv) as c:
            assert (await c.call_tool("ledger_compliance_report", {})).is_error
    anyio.run(go)


def test_report_pdf(ledger, monkeypatch):
    import base64
    acme = ledger.create_org("Acme")
    ledger.record(acme["org_id"], "agent", "claude", "payment", "Paid invoice 1", outcome="failure")
    as_org(monkeypatch, acme["api_key"])

    async def go():
        async with Client(build_server(Settings(pay_to=PAY_TO), ledger, FakeFacilitator(),
                                       anchor_client=FakeAnchorWithVerify())) as c:
            rid = (await c.call_tool("ledger_compliance_report", {})).structured_content["report_id"]
            r = await c.call_tool("ledger_report_pdf", {"report_id": rid})
            pdf = base64.b64decode(r.structured_content["pdf_base64"])
            assert pdf.startswith(b"%PDF") and len(pdf) > 2000
            assert (await c.call_tool("ledger_report_pdf", {"report_id": "rpt_nope"})).is_error
    anyio.run(go)


def test_privi_handshake_between_two_companies(ledger, monkeypatch, tmp_path):
    a, b, c3 = ledger.create_org("Acme Robotics"), ledger.create_org("Blue Water Fab"), ledger.create_org("Other")
    fake = FakeAnchorWithVerify()
    srv = build_server(Settings(pay_to=PAY_TO), ledger, FakeFacilitator(), anchor_client=fake)

    async def call(key, tool, args):
        monkeypatch.setenv("LEDGER_LOCAL_ORG_KEY", key)
        async with Client(srv) as c:
            return await c.call_tool(tool, args)

    def run_(key, tool, args):
        return anyio.run(call, key, tool, args)

    offer = run_(a["api_key"], "ledger_handshake_offer", {
        "counterparty_org_id": b["org_id"], "stream_id": "procurement-agent", "actor": "claude",
        "action_type": "payment", "summary": "Pay $4,800 for 800 brackets, PO-1042", "resource": "PO-1042",
        "details": {"usd": 4800, "qty": 800}}).structured_content
    hid = offer["handshake_id"]
    assert offer["status"] == "offered"

    # bad offers
    assert run_(a["api_key"], "ledger_handshake_offer", {"counterparty_org_id": a["org_id"], "stream_id": "x",
                "actor": "y", "action_type": "payment", "summary": "self"}).is_error
    assert run_(a["api_key"], "ledger_handshake_offer", {"counterparty_org_id": "org_nobody", "stream_id": "x",
                "actor": "y", "action_type": "payment", "summary": "ghost"}).is_error

    inbox = run_(b["api_key"], "ledger_handshake_inbox", {}).structured_content
    assert inbox["pending_for_you"] == 1 and inbox["handshakes"][0]["terms"]["details"]["usd"] == 4800

    # only the addressed company can accept
    assert run_(c3["api_key"], "ledger_handshake_accept", {"handshake_id": hid, "stream_id": "s", "actor": "z"}).is_error
    acc = run_(b["api_key"], "ledger_handshake_accept", {"handshake_id": hid, "stream_id": "sales-agent",
                                                         "actor": "claude"}).structured_content
    assert acc["status"] == "accepted" and acc["onchain"]["anchored"] and fake.calls[-1] == [acc["pair_hash"]]
    assert run_(b["api_key"], "ledger_handshake_accept", {"handshake_id": hid, "stream_id": "s", "actor": "z"}).is_error

    # both logs hold matching, cross-referenced entries
    a_log = ledger.entries(a["org_id"], "procurement-agent")
    b_log = ledger.entries(b["org_id"], "sales-agent")
    assert len(a_log) == 2 and len(b_log) == 1
    import json as _j
    assert _j.loads(b_log[0]["details"])["handshake"]["initiator_entry_hash"] == a_log[0]["entry_hash"]
    assert _j.loads(a_log[1]["details"])["handshake"]["counterparty_entry_hash"] == b_log[0]["entry_hash"]

    pub = run_("none", "ledger_handshake_verify", {"handshake_id": hid}).structured_content
    assert pub["both_entries_present"] and pub["pair_hash_valid"] and "terms" not in pub
    assert "usd" not in str(pub) and "PO-1042" not in str(pub) and "brackets" not in str(pub)  # terms stay private

    # one side deletes its record: the public check exposes it
    db = sqlite3.connect(str(tmp_path / "l.db"))
    db.execute("DELETE FROM entries WHERE entry_hash=?", (b_log[0]["entry_hash"],)); db.commit()
    pub2 = run_("none", "ledger_handshake_verify", {"handshake_id": hid}).structured_content
    assert pub2["both_entries_present"] is False

    # rejection path
    o2 = run_(a["api_key"], "ledger_handshake_offer", {"counterparty_org_id": b["org_id"], "stream_id": "procurement-agent",
              "actor": "claude", "action_type": "data_access", "summary": "Request QA records"}).structured_content
    rj = run_(b["api_key"], "ledger_handshake_reject", {"handshake_id": o2["handshake_id"], "reason": "not covered by NDA"})
    assert rj.structured_content["status"] == "rejected"
    last = ledger.entries(a["org_id"], "procurement-agent")[-1]
    assert last["outcome"] == "blocked" and "rejected" in last["summary"]


def test_self_serve_free_limit_then_paid_pro(ledger, monkeypatch):
    monkeypatch.setenv("LEDGER_FREE_MONTHLY", "3")
    fac = FakeFacilitator()
    srv = build_server(Settings(pay_to=PAY_TO), ledger, fac)

    async def call(key, tool, args, meta=None):
        if key is None:
            monkeypatch.delenv("LEDGER_LOCAL_ORG_KEY", raising=False)
        else:
            monkeypatch.setenv("LEDGER_LOCAL_ORG_KEY", key)
        async with Client(srv) as c:
            return await c.call_tool(tool, args, meta=meta)

    run_ = lambda *a, **k: anyio.run(lambda: call(*a, **k))
    su = run_(None, "ledger_signup", {"organization_name": "Startup Inc"}).structured_content
    key = su["api_key"]
    assert su["plan"]["plan"] == "free" and su["plan"]["monthly_limit"] == 3

    rec = {"stream_id": "agent", "actor": "claude", "action_type": "tool_call", "summary": "did a thing"}
    for _ in range(3):
        assert not run_(key, "ledger_record_action", rec).is_error
    blocked = run_(key, "ledger_record_action", rec)
    assert blocked.is_error and "ledger_upgrade_pro" in blocked.structured_content["upgrade"]

    need = run_(key, "ledger_upgrade_pro", {})
    assert need.is_error and need.structured_content["accepts"][0]["amount"] == "29000000"   # $29 USDC
    pay = {"x402Version": 2, "resource": need.structured_content["resource"],
           "accepted": need.structured_content["accepts"][0], "payload": {}}
    up = run_(key, "ledger_upgrade_pro", {}, meta={"x402/payment": pay})
    assert not up.is_error and up.structured_content["plan"] == "pro" and up.structured_content["paid_until"]
    assert up.meta["x402/payment-response"]["success"] and fac.calls == ["verify", "settle"]

    assert not run_(key, "ledger_record_action", rec).is_error          # unlimited now
    plan = run_(key, "ledger_plan", {}).structured_content
    assert plan["plan"] == "pro" and plan["monthly_limit"] is None
    org = ledger.org_for_key(key)
    assert ledger.entries(org["org_id"], "privi-billing")[0]["action_type"] == "payment"

    # a second purchase stacks another 30 days
    first_until = plan["paid_until"]
    up2 = run_(key, "ledger_upgrade_pro", {}, meta={"x402/payment": pay}).structured_content
    assert up2["paid_until"] > first_until

    # admin-created orgs stay unlimited (enterprise)
    ent = ledger.create_org("Big Co")
    assert run_(ent["api_key"], "ledger_plan", {}).structured_content["plan"] == "enterprise"


def test_gov_ai_inventory_m25_21(ledger, monkeypatch):
    agency = ledger.create_org("Department of Examples")
    monkeypatch.setenv("LEDGER_LOCAL_ORG_KEY", agency["api_key"])
    fake = FakeAnchorWithVerify()
    srv = build_server(Settings(pay_to=PAY_TO), ledger, FakeFacilitator(), anchor_client=fake)

    async def call(tool, args):
        async with Client(srv) as c:
            return await c.call_tool(tool, args)

    run_ = lambda tool, args: anyio.run(call, tool, args)
    benefits = {"use_case_id": "DOE-2026-001", "name": "Benefits eligibility triage", "stage": "deployed",
                "high_impact": True, "purpose": "Prioritize benefit applications for review",
                "outputs": "Priority score per application", "sourcing": "vendor", "vendor_name": "Acme AI",
                "involves_pii": True, "custom_code": False, "monitoring_streams": ["triage-agent"],
                "practices": {"pre_deployment_testing": {"done": True, "evidence": "Test report TR-14"}}}
    s1 = run_("gov_ai_usecase_save", {"use_case": benefits, "actor": "CAIO office"}).structured_content
    assert s1["version"] == 1 and s1["changed"]

    # bad input is rejected
    assert run_("gov_ai_usecase_save", {"use_case": {**benefits, "stage": "live"}, "actor": "x"}).is_error
    assert run_("gov_ai_usecase_save", {"use_case": {**benefits, "color": "blue"}, "actor": "x"}).is_error

    chk = run_("gov_ai_inventory_check", {}).structured_content
    assert chk["ready_for_submission"] is False and chk["finding_counts"]["critical"] == 7   # 7 practices unmet
    texts = " ".join(f["finding"] for f in chk["findings"])
    assert "Privacy Impact Assessment" in texts and "no activity in the last 30 days" in texts

    # fix it: PIA, the remaining practices (one waived), and monitoring activity
    done = {p: {"done": True, "evidence": f"doc-{p}"} for p in
            ["impact_assessment", "independent_review", "ongoing_monitoring", "operator_training",
             "fail_safe", "appeal_process"]}
    s2 = run_("gov_ai_usecase_save", {"actor": "CAIO office", "use_case": {
        "use_case_id": "DOE-2026-001", "pia_link": "https://example.gov/pia/14", "practices": done,
        "waivers": [{"practice": "public_feedback", "justification": "CAIO determination 2026-03"}]}}).structured_content
    assert s2["version"] == 2 and "pia_link" in s2["changed_fields"]
    ledger.record(agency["org_id"], "triage-agent", "triage model", "decision", "Scored application 551")
    assert run_("gov_ai_inventory_check", {}).structured_content["ready_for_submission"] is True

    # every change is in the tamper-evident log
    log = ledger.entries(agency["org_id"], "ai-inventory")
    assert [e["summary"].split(" (")[0] for e in log] == ["Added AI use case DOE-2026-001", "Updated AI use case DOE-2026-001"]

    # internal-only use case is withheld from the public file
    run_("gov_ai_usecase_save", {"actor": "x", "use_case": {"use_case_id": "DOE-2026-002", "name": "Internal search",
         "stage": "pilot", "high_impact": False, "purpose": "Search", "outputs": "Results", "sourcing": "in_house",
         "involves_pii": False, "custom_code": True, "withhold_from_public": True}})
    ex = run_("gov_ai_inventory_export", {}).structured_content
    import csv as _csv, io as _io
    rows = list(_csv.DictReader(_io.StringIO(ex["csv"])))
    assert len(rows) == 1 and rows[0]["use_case_id"] == "DOE-2026-001" and rows[0]["practice_public_feedback"] == "Waived"
    assert ex["attestation"]["anchored"] and fake.calls[-1] == [ex["attestation"]["export_hash"]]

    ok = run_("gov_ai_verify_export", {"csv_text": ex["csv"]}).structured_content
    assert ok["valid"] and ok["rows"] == 1
    bad = run_("gov_ai_verify_export", {"csv_text": ex["csv"].replace("Yes", "No", 1)}).structured_content
    assert bad["valid"] is False


def test_quantum_ready_pqc_plan(ledger, monkeypatch):
    agency = ledger.create_org("Department of Examples")
    monkeypatch.setenv("LEDGER_LOCAL_ORG_KEY", agency["api_key"])
    fake = FakeAnchorWithVerify()
    srv = build_server(Settings(pay_to=PAY_TO), ledger, FakeFacilitator(), anchor_client=fake)

    async def call(tool, args):
        async with Client(srv) as c:
            return await c.call_tool(tool, args)

    run_ = lambda tool, args: anyio.run(call, tool, args)

    cls = run_("gov_pqc_classify", {"algorithms": ["RSA-2048", "X25519MLKEM768", "ML-DSA-65"]}).structured_content
    assert [r["class"] for r in cls["results"]] == ["quantum_vulnerable", "hybrid", "post_quantum"]

    hva = {"system_id": "BEN-01", "name": "Benefits portal", "high_value_asset": True, "high_impact": True,
           "sensitive_until_year": 2045, "assets": [
               {"asset_id": "tls-edge", "kind": "protocol", "algorithm": "ECDHE-RSA-AES256-GCM", "protocol": "TLS 1.2"},
               {"asset_id": "doc-sign", "kind": "signature", "algorithm": "RSA-3072", "target_date": "2032-06-30"},
               {"asset_id": "vpn", "kind": "key_establishment", "algorithm": "X25519MLKEM768", "status": "hybrid"},
               {"asset_id": "db-enc", "kind": "symmetric", "algorithm": "AES-256-GCM"}]}
    low = {"system_id": "INT-09", "name": "Internal wiki", "assets": [
               {"asset_id": "tls", "kind": "protocol", "algorithm": "ECDHE-ECDSA", "protocol": "TLS 1.3",
                "target_date": "2029-06-30"}]}
    assert run_("gov_pqc_system_save", {"system": hva, "actor": "scanner"}).structured_content["quantum_vulnerable_assets"] == 2
    run_("gov_pqc_system_save", {"system": low, "actor": "scanner"})
    assert run_("gov_pqc_system_save", {"system": {**low, "assets": [{"asset_id": "x", "kind": "magic", "algorithm": "RSA"}]},
                                        "actor": "s"}).is_error

    plan = run_("gov_pqc_plan", {}).structured_content
    q = plan["migration_queue"]
    assert [(i["system_id"], i["asset_id"]) for i in q][:2] == [("BEN-01", "tls-edge"), ("BEN-01", "doc-sign")]
    assert q[0]["deadline"] == "2030-12-31" and q[1]["deadline"] == "2031-12-31" and q[-1]["system_id"] == "INT-09"
    m = plan["metrics"]
    assert m["quantum_vulnerable"] == 3 and m["hybrid"] == 1 and m["tls_below_1_3"] == 1 and m["migration_progress_pct"] == 25.0
    texts = [f["finding"] for f in plan["findings"]]
    assert any("after the 2031-12-31 deadline" in t for t in texts)          # signature target 2032 is too late
    assert any("TLS 1.2" in t for t in texts) and any("no target date" in t for t in texts)

    ex = run_("gov_pqc_export", {}).structured_content
    assert ex["attestation"]["anchored"] and fake.calls[-1] == [ex["attestation"]["export_hash"]]
    assert run_("gov_pqc_verify_export", {"document": ex["document"]}).structured_content["valid"]
    import copy
    doc2 = copy.deepcopy(ex["document"]); doc2["plan"]["metrics"]["quantum_vulnerable"] = 0
    assert run_("gov_pqc_verify_export", {"document": doc2}).structured_content["valid"] is False
    assert [e["summary"].split(" (")[0] for e in ledger.entries(agency["org_id"], "pqc-inventory")][:2] == [
        "Added cryptographic inventory for BEN-01", "Added cryptographic inventory for INT-09"]


# ---------------- Privi Passport ----------------

def test_passport_issue_verify_gate_revoke(ledger, monkeypatch):
    acme, other = ledger.create_org("Acme"), ledger.create_org("Other")
    for i in range(20):
        ledger.record(acme["org_id"], "ops-agent", "claude", "payment" if i % 4 else "approval",
                      f"step {i}", "", "failure" if i == 7 else "success")

    def run_(key, name, args):
        as_org(monkeypatch, key)

        async def go():
            async with Client(server(ledger)) as c:
                return await c.call_tool(name, args)
        return anyio.run(go)

    # enterprise orgs (create_org default) issue for free
    r = run_(acme["api_key"], "passport_issue", {"stream_id": "ops-agent"})
    assert not r.is_error, r
    pp = r.structured_content
    assert pp["passport_id"].startswith("pp_") and 0 < pp["score"] <= 1000 and pp["grade"] in "ABCDE"
    assert pp["passport"]["components"]["integrity"]["points"] == 250
    assert pp["passport"]["facts"]["entry_count"] == 20 and pp["passport"]["facts"]["failures"] == 1
    assert pp["attestation"]["anchored"] is False  # no anchor client in tests

    # whole-org passport, and empty stream refused
    assert not run_(acme["api_key"], "passport_issue", {}).is_error
    assert "error" in run_(acme["api_key"], "passport_issue", {"stream_id": "nothing"}).structured_content

    # anyone can verify, by id or by document
    v = run_(None, "passport_verify", {"passport_id": pp["passport_id"]}).structured_content
    assert v["valid"] and v["signature_valid"] and v["hash_matches_issued"] and not v["expired"]
    assert v["live"]["score"] == pp["score"] and v["live"]["drift"] == 0
    v2 = run_(None, "passport_verify", {"passport": pp["passport"]}).structured_content
    assert v2["valid"] and v2["passport_id"] == pp["passport_id"]
    edited = dict(pp["passport"], score=1000)
    assert run_(None, "passport_verify", {"passport": edited}).structured_content["valid"] is False
    assert run_(None, "passport_verify", {"passport_id": "pp_nope"}).structured_content["valid"] is False

    # gate: allow at a reachable bar, deny above it; decision is logged when the checker sends a key
    g = run_(other["api_key"], "passport_gate", {"passport_id": pp["passport_id"], "min_score": 100,
                                                 "purpose": "pay invoice"}).structured_content
    assert g["allow"] and g["recorded_in_your_log"]["stream_id"] == "privi-passport"
    g2 = run_(None, "passport_gate", {"passport_id": pp["passport_id"], "min_score": 1000}).structured_content
    assert not g2["allow"] and "below the required 1000" in g2["reasons"][0]
    g3 = run_(None, "passport_gate", {"passport_id": pp["passport_id"], "min_grade": "A", "min_score": 0}).structured_content
    assert g3["allow"] == (pp["grade"] == "A")
    assert run_(None, "passport_gate", {"passport_id": pp["passport_id"], "require_anchored": True,
                                        "min_score": 0}).structured_content["allow"] is False

    # tampering after issue is caught by the live re-score
    ledger._db.execute("UPDATE entries SET summary='edited' WHERE org_id=? AND seq=3", (acme["org_id"],))
    ledger._db.commit()
    v3 = run_(None, "passport_verify", {"passport_id": pp["passport_id"]}).structured_content
    assert v3["valid"] is False and v3["history_still_intact"] is False and v3["live"]["score"] < pp["score"]

    # list and revoke (only the owner)
    lst = run_(acme["api_key"], "passport_list", {}).structured_content
    assert len(lst["passports"]) == 2 and lst["issuer"]["public_key_hex"]
    assert run_(other["api_key"], "passport_revoke", {"passport_id": pp["passport_id"]}).is_error
    rv = run_(acme["api_key"], "passport_revoke", {"passport_id": pp["passport_id"], "reason": "retired"}).structured_content
    assert rv["revoked"]
    assert run_(None, "passport_verify", {"passport_id": pp["passport_id"]}).structured_content["revoked"] is True


def test_passport_free_plan_pays(ledger, monkeypatch):
    fac = FakeFacilitator()
    as_org(monkeypatch, None)

    async def go():
        async with Client(server(ledger, fac)) as c:
            org = (await c.call_tool("ledger_signup", {"organization_name": "Tiny Co"})).structured_content
            monkeypatch.setenv("LEDGER_LOCAL_ORG_KEY", org["api_key"])
            await c.call_tool("ledger_record_action", {"stream_id": "a", "actor": "x", "action_type": "tool_call", "summary": "s"})
            r = await c.call_tool("passport_issue", {})
            assert r.is_error  # 402: payment required on the free plan
            assert "payment" in json.dumps(r.structured_content).lower()
    anyio.run(go)


def test_passport_badge_and_issuer_routes(ledger):
    from starlette.testclient import TestClient
    acme = ledger.create_org("Acme")
    ledger.record(acme["org_id"], "a", "x", "tool_call", "s")
    app = server(ledger).streamable_http_app(stateless_http=True, json_response=True)
    with TestClient(app) as http:
        iss = http.get("/.well-known/privi-passport.json").json()
        assert iss["public_key_hex"] and iss["key_id"].startswith("pk_")
        assert http.get("/passports/pp_missing").status_code == 404
        assert http.get("/passports/pp_missing/badge.svg").headers["content-type"].startswith("image/svg")


# ---------------- Privi KYA ----------------

def _eth_wallet():
    """A throwaway secp256k1 wallet and a personal_sign function, using only `cryptography`."""
    from cryptography.hazmat.primitives.asymmetric import ec, utils
    from cryptography.hazmat.primitives import hashes
    from privi_ledger.kya import keccak256, personal_hash, recover_address
    k = ec.generate_private_key(ec.SECP256K1())
    pub = k.public_key().public_numbers()
    addr = "0x" + keccak256(pub.x.to_bytes(32, "big") + pub.y.to_bytes(32, "big"))[-20:].hex()
    N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141

    def sign(message: str) -> str:
        h = personal_hash(message)
        r, s = utils.decode_dss_signature(k.sign(h, ec.ECDSA(utils.Prehashed(hashes.SHA256()))))
        s = N - s if s > N // 2 else s
        for v in (27, 28):
            sig = r.to_bytes(32, "big") + s.to_bytes(32, "big") + bytes([v])
            try:
                if recover_address(h, sig) == addr:
                    return "0x" + sig.hex()
            except ValueError:
                pass
        raise AssertionError("could not produce recoverable signature")
    return addr, sign


def test_kya_bind_and_check(ledger, monkeypatch):
    acme, bank = ledger.create_org("Acme"), ledger.create_org("Bank")
    for i in range(12):
        ledger.record(acme["org_id"], "treasury-agent", "claude", "approval" if i % 3 == 0 else "payment", f"p{i}")

    def run_(key, name, args):
        as_org(monkeypatch, key)

        async def go():
            async with Client(server(ledger)) as c:
                return await c.call_tool(name, args)
        return anyio.run(go)

    addr, sign = _eth_wallet()
    # unknown wallet is denied
    d0 = run_(None, "kya_check", {"address": addr}).structured_content
    assert d0["known"] is False and d0["allow"] is False and d0["signature"]

    # bind with a real wallet signature
    ch = run_(acme["api_key"], "kya_challenge", {"address": addr}).structured_content
    assert ch["challenge_id"].startswith("kyc_") and addr.lower()[2:10] in ch["message"].lower()
    bad = run_(acme["api_key"], "kya_bind_wallet", {"address": addr, "challenge_id": ch["challenge_id"],
                                                     "signature": "0x" + "11" * 65}).structured_content
    assert "error" in bad
    b = run_(acme["api_key"], "kya_bind_wallet", {"address": addr, "challenge_id": ch["challenge_id"],
                                                   "signature": sign(ch["message"]), "stream_id": "treasury-agent",
                                                   "label": "hot wallet"}).structured_content
    assert b["bound"] and b["proof"] == "signature"
    # challenge is single-use
    assert "error" in run_(acme["api_key"], "kya_bind_wallet", {"address": addr, "challenge_id": ch["challenge_id"],
                                                                 "signature": sign(ch["message"])}).structured_content

    # no passport yet -> denied with a pointer
    d1 = run_(None, "kya_check", {"address": addr, "min_score": 0}).structured_content
    assert d1["known"] and not d1["allow"] and "passport_issue" in d1["reasons"][0]

    # issue passport -> allowed; bank logs the check
    pp = run_(acme["api_key"], "passport_issue", {"stream_id": "treasury-agent"}).structured_content
    d2 = run_(bank["api_key"], "kya_check", {"address": addr.upper().replace("0X", "0x"), "min_score": 100,
                                              "purpose": "settle invoice"}).structured_content
    assert d2["allow"] and d2["passport_id"] == pp["passport_id"] and d2["proof"] == "signature"
    assert d2["recorded_in_your_log"]["stream_id"] == "privi-kya"
    assert d2["attestation"]["allow"] is True and len(d2["signature"]) == 128
    # internal streams do not change the score
    v = run_(None, "passport_verify", {"passport_id": pp["passport_id"]}).structured_content
    assert v["live"]["drift"] == 0

    # declared binding (no signature) is refused when require_signed
    addr2, _ = _eth_wallet()
    run_(acme["api_key"], "kya_bind_wallet", {"address": addr2})
    assert run_(None, "kya_check", {"address": addr2, "min_score": 0}).structured_content["allow"] is False
    assert run_(None, "kya_check", {"address": addr2, "min_score": 0, "require_signed": False}).structured_content["allow"] is True

    # another org cannot steal a proven wallet without a signature
    assert "error" in run_(bank["api_key"], "kya_bind_wallet", {"address": addr}).structured_content

    # unbind -> denied
    assert len(run_(acme["api_key"], "kya_wallets", {}).structured_content["wallets"]) == 2
    assert run_(bank["api_key"], "kya_unbind_wallet", {"address": addr}).is_error
    assert run_(acme["api_key"], "kya_unbind_wallet", {"address": addr}).structured_content["unbound"]
    assert run_(None, "kya_check", {"address": addr, "min_score": 0}).structured_content["allow"] is False


def test_kya_http_routes(ledger):
    from starlette.testclient import TestClient
    app = server(ledger).streamable_http_app(stateless_http=True, json_response=True)
    with TestClient(app) as http:
        r = http.get("/kya/0x1990589FD200E043b8C6FD9ec5956c61b3071048")
        assert r.status_code == 200 and r.json()["known"] is False and r.json()["signature"]
        assert http.get("/kya/nope").status_code == 400
        assert http.get("/kya/0x1990589FD200E043b8C6FD9ec5956c61b3071048/badge.svg").headers["content-type"].startswith("image/svg")


def test_kya_connect_page_and_http_bind(ledger):
    from starlette.testclient import TestClient
    acme = ledger.create_org("Acme")
    ledger.record(acme["org_id"], "a", "x", "tool_call", "s")
    addr, sign = _eth_wallet()
    app = server(ledger).streamable_http_app(stateless_http=True, json_response=True)
    with TestClient(app) as http:
        page = http.get("/kya/connect")
        assert page.status_code == 200 and "personal_sign" in page.text
        assert http.post("/kya/challenge", json={"address": addr}).status_code == 401
        auth = {"Authorization": "Bearer " + acme["api_key"]}
        ch = http.post("/kya/challenge", json={"address": addr}, headers=auth).json()
        assert ch["challenge_id"].startswith("kyc_")
        assert http.post("/kya/bind", json={"address": addr, "challenge_id": ch["challenge_id"]}, headers=auth).status_code == 400
        b = http.post("/kya/bind", json={"address": addr, "challenge_id": ch["challenge_id"],
                                         "signature": sign(ch["message"]), "label": "owner"}, headers=auth).json()
        assert b["bound"] and b["proof"] == "signature"
        assert http.get(f"/kya/{addr}?min_score=0").json()["known"] is True


# ---------------- Privi Mandates ----------------

def test_mandate_lifecycle(ledger, monkeypatch):
    from starlette.testclient import TestClient
    shop = ledger.create_org("ShopBot Inc")
    human, human_sign = _eth_wallet()
    stranger, stranger_sign = _eth_wallet()

    def run_(key, name, args):
        as_org(monkeypatch, key)

        async def go():
            async with Client(server(ledger)) as c:
                return await c.call_tool(name, args)
        return anyio.run(go)

    # draft: validation
    assert run_(shop["api_key"], "mandate_create", {"stream_id": "shopper", "principal_wallet": human,
                                                    "max_total_usdc": "10", "max_per_payment_usdc": "20",
                                                    "purpose": "x"}).is_error
    assert run_(None, "mandate_create", {"stream_id": "shopper", "principal_wallet": human,
                                         "max_total_usdc": "10", "purpose": "x"}).is_error
    d = run_(shop["api_key"], "mandate_create", {
        "stream_id": "shopper", "principal_wallet": human, "max_total_usdc": "100", "max_per_payment_usdc": "40",
        "payees": ["https://store.example.com/checkout", "0x1990589FD200E043b8C6FD9ec5956c61b3071048"],
        "purpose": "Buy office supplies", "days": 7}).structured_content
    mid = d["mandate_id"]
    assert d["status"] == "draft" and "store.example.com" in d["message"] and d["sign_url"].endswith(f"/mandates/{mid}/sign")

    # not spendable until signed
    assert run_(shop["api_key"], "mandate_spend", {"mandate_id": mid, "amount_usdc": "5",
                                                   "payee": "store.example.com"}).is_error
    c0 = run_(None, "mandate_check", {"mandate_id": mid, "amount_usdc": "5", "payee": "store.example.com"}).structured_content
    assert not c0["allow"] and "not signed" in c0["reasons"][0]

    app = server(ledger).streamable_http_app(stateless_http=True, json_response=True)
    with TestClient(app) as http:
        assert "personal_sign" in http.get(f"/mandates/{mid}/sign").text
        # wrong signer refused
        assert http.post(f"/mandates/{mid}/activate", json={"signature": stranger_sign(d["message"])}).status_code == 400
        act = http.post(f"/mandates/{mid}/activate", json={"signature": human_sign(d["message"])}).json()
        assert act["status"] == "active" and act["principal_signature_valid"] and act["privi_signature"]
        assert http.post(f"/mandates/{mid}/activate", json={"signature": human_sign(d["message"])}).status_code == 400
        chk = http.get(f"/mandates/{mid}/check", params={"amount": "30", "payee": "store.example.com"}).json()
        assert chk["allow"] and chk["remaining_usdc"] == "100" and len(chk["signature"]) == 128

    # limits
    ok = lambda amt, payee="store.example.com": run_(shop["api_key"], "mandate_spend", {
        "mandate_id": mid, "amount_usdc": amt, "payee": payee, "reference": "order-1"})
    s1 = ok("40").structured_content
    assert s1["allow"] and s1["remaining_usdc"] == "60" and s1["entry_hash"]
    assert "per-payment" in ok("40.01").structured_content["error"]
    assert "not on the mandate" in ok("1", "evil.example").structured_content["error"]
    assert ok("40", "0x1990589fd200e043b8c6fd9ec5956c61b3071048").structured_content["remaining_usdc"] == "20"
    assert "remaining budget" in ok("25").structured_content["error"]
    assert ok("19.5").structured_content["remaining_usdc"] == "0.5"

    # merchant check reflects spend; other orgs can't spend it
    c1 = run_(None, "mandate_check", {"mandate_id": mid, "amount_usdc": "1", "payee": "store.example.com"}).structured_content
    assert not c1["allow"] and c1["remaining_usdc"] == "0.5"
    other = ledger.create_org("Other")
    assert run_(other["api_key"], "mandate_spend", {"mandate_id": mid, "amount_usdc": "0.1",
                                                    "payee": "store.example.com"}).is_error

    # log: approval + 3 payments + blocked attempts, chain intact
    evs = ledger.entries(shop["org_id"], "shopper")
    assert sum(e["action_type"] == "approval" for e in evs) == 1
    assert sum(e["outcome"] == "success" and e["action_type"] == "payment" for e in evs) == 3
    assert sum(e["outcome"] == "blocked" for e in evs) >= 3 and ledger.check_chain(evs).valid

    # human revokes by signature; stranger cannot
    app = server(ledger).streamable_http_app(stateless_http=True, json_response=True)
    with TestClient(app) as http:
        assert http.post(f"/mandates/{mid}/revoke", json={"signature": stranger_sign(f"Revoke Privi Mandate {mid}")}).status_code == 400
        rv = http.post(f"/mandates/{mid}/revoke", json={"signature": human_sign(f"Revoke Privi Mandate {mid}")}).json()
        assert rv["status"] == "revoked"
    assert "revoked" in ok("0.1").structured_content["error"]
    lst = run_(shop["api_key"], "mandate_list", {}).structured_content["mandates"]
    assert lst[0]["mandate_id"] == mid and lst[0]["spent_usdc"] == "99.5"


# ---------------- Privi Fortress ----------------

def test_fortress_pq_log_tpi_bundle(ledger, monkeypatch, tmp_path):
    import subprocess, sys as _sys
    from pathlib import Path
    from starlette.testclient import TestClient
    from cryptography.hazmat.primitives.asymmetric.mldsa import MLDSA87PublicKey
    from privi_ledger.fortress import verify_inclusion, verify_consistency, leaf_hash
    acme, other = ledger.create_org("Acme Defense"), ledger.create_org("Other")
    for i in range(9):
        ledger.record(acme["org_id"], "ops", "claude", "tool_call", f"step {i}")
        ledger.record(other["org_id"], "x", "claude", "tool_call", f"o{i}")
    o1, sign1 = _eth_wallet()
    o2, sign2 = _eth_wallet()
    o3, sign3 = _eth_wallet()

    def run_(key, name, args):
        as_org(monkeypatch, key)

        async def go():
            async with Client(server(ledger)) as c:
                return await c.call_tool(name, args)
        return anyio.run(go)

    # keys + post-quantum co-signed passport
    keys = run_(None, "fortress_keys", {}).structured_content
    assert "ML-DSA-87" in keys["post_quantum"]["algorithm"] and len(bytes.fromhex(keys["post_quantum"]["public_key_hex"])) == 2592
    pp = run_(acme["api_key"], "passport_issue", {"stream_id": "ops"}).structured_content
    MLDSA87PublicKey.from_public_bytes(bytes.fromhex(keys["post_quantum"]["public_key_hex"])).verify(
        bytes.fromhex(pp["post_quantum"]["ml_dsa_87"]), bytes.fromhex(pp["body_hash"]))
    v = run_(None, "passport_verify", {"passport_id": pp["passport_id"]}).structured_content
    assert v["post_quantum_signed"] and v["ml_dsa_87_valid"] and v["ed25519_valid"]
    rep = run_(acme["api_key"], "ledger_compliance_report", {}).structured_content
    assert rep["attestation"]["post_quantum"]["ml_dsa_87"]
    assert run_(None, "ledger_verify_report", {"report": rep["report"]}).structured_content["ml_dsa_87_valid"]

    # transparency log: head, inclusion, consistency
    sth1 = run_(None, "ledger_tree_head", {}).structured_content
    n1 = sth1["tree_head"]["tree_size"]
    MLDSA87PublicKey.from_public_bytes(bytes.fromhex(keys["post_quantum"]["public_key_hex"])).verify(
        bytes.fromhex(sth1["signatures"]["ml_dsa_87"]), bytes.fromhex(sth1["body_hash"]))
    e3 = ledger.entries(acme["org_id"], "ops")[2]["entry_hash"]
    inc = run_(None, "ledger_inclusion_proof", {"entry_hash": e3}).structured_content
    assert inc["verified_here"] and verify_inclusion(leaf_hash(e3), inc["leaf_index"], inc["tree_size"],
                                                     [bytes.fromhex(p) for p in inc["audit_path"]],
                                                     bytes.fromhex(inc["signed_tree_head"]["tree_head"]["root_hash"]))
    for i in range(5):
        ledger.record(other["org_id"], "x", "claude", "tool_call", f"later {i}")
    sth2 = run_(None, "ledger_tree_head", {}).structured_content
    assert sth2["tree_head"]["tree_size"] > n1
    cons = run_(None, "ledger_consistency_proof", {"first": n1}).structured_content
    assert cons["verified_here"] and verify_consistency(n1, cons["second"], bytes.fromhex(cons["first_root"]),
                                                        bytes.fromhex(cons["second_root"]),
                                                        [bytes.fromhex(p) for p in cons["proof"]])
    # rewriting history breaks consistency with the old signed head
    ledger._db.execute("UPDATE entries SET entry_hash=? WHERE entry_hash=?", ("ab" * 32, e3))
    ledger._db.commit()
    forged = run_(None, "ledger_consistency_proof", {"first": n1}).structured_content
    assert forged["verified_here"] is False
    ledger._db.execute("UPDATE entries SET entry_hash=? WHERE entry_hash=?", (e3, "ab" * 32))
    ledger._db.commit()

    # two-person integrity
    assert run_(acme["api_key"], "fortress_tpi_policy", {"name": "wire", "officer_wallets": [o1],
                                                         "required": 2}).is_error
    pol = run_(acme["api_key"], "fortress_tpi_policy", {"name": "wire", "officer_wallets": [o1, o2, o3],
                                                        "required": 2}).structured_content
    assert pol["required"] == 2 and len(pol["officers"]) == 3
    rq = run_(acme["api_key"], "fortress_tpi_request", {"policy": "wire", "stream_id": "ops",
                                                       "summary": "Transfer 50,000 USDC to supplier",
                                                       "details": {"to": "0xabc", "usdc": 50000}}).structured_content
    rid = rq["request_id"]
    assert "error" in run_(acme["api_key"], "fortress_tpi_execute", {"request_id": rid}).structured_content
    outsider, sign_out = _eth_wallet()
    app = server(ledger).streamable_http_app(stateless_http=True, json_response=True)
    with TestClient(app) as http:
        assert "personal_sign" in http.get(f"/tpi/{rid}").text
        assert http.post(f"/tpi/{rid}/approve", json={"signature": sign_out(rq["approve_message"])}).status_code == 400
        a1 = http.post(f"/tpi/{rid}/approve", json={"signature": sign1(rq["approve_message"])}).json()
        assert a1["status"] == "pending" and a1["approvals_count"] == 1
        assert http.post(f"/tpi/{rid}/approve", json={"signature": sign1(rq["approve_message"])}).status_code == 400
        a2 = http.post(f"/tpi/{rid}/approve", json={"signature": sign2(rq["approve_message"])}).json()
        assert a2["status"] == "authorized"
        assert http.get("/log/sth").json()["tree_head"]["tree_size"] > 0
        assert "verify_inclusion" in http.get("/tools/verify_bundle.py").text
    assert run_(other["api_key"], "fortress_tpi_execute", {"request_id": rid}).is_error
    ex = run_(acme["api_key"], "fortress_tpi_execute", {"request_id": rid}).structured_content
    assert ex["status"] == "executed"
    assert run_(acme["api_key"], "fortress_tpi_execute", {"request_id": rid}).is_error  # single use
    rq2 = run_(acme["api_key"], "fortress_tpi_request", {"policy": "wire", "stream_id": "ops",
                                                        "summary": "Delete audit stream"}).structured_content
    app = server(ledger).streamable_http_app(stateless_http=True, json_response=True)
    with TestClient(app) as http:
        vt = http.post(f"/tpi/{rq2['request_id']}/veto", json={"signature": sign3(rq2["veto_message"])}).json()
        assert vt["status"] == "vetoed"
        assert http.post(f"/tpi/{rq2['request_id']}/approve", json={"signature": sign1(rq2["approve_message"])}).status_code == 400

    # evidence bundle verified offline by the standalone script; tampering fails
    b = run_(acme["api_key"], "ledger_evidence_bundle", {"stream_id": "ops"}).structured_content
    script = Path(__file__).resolve().parents[1] / "src" / "privi_ledger" / "verify_bundle.py"
    good = tmp_path / "bundle.json"
    good.write_text(json.dumps(b))
    r = subprocess.run([_sys.executable, str(script), str(good)], capture_output=True, text=True)
    assert r.returncode == 0 and "RESULT: VALID" in r.stdout and "[FAIL]" not in r.stdout, r.stdout
    b["bundle"]["entries"][1]["summary"] = "something else"
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(b))
    r = subprocess.run([_sys.executable, str(script), str(bad)], capture_output=True, text=True)
    assert r.returncode == 1 and "INVALID" in r.stdout


# ---------------- x402 Bazaar discovery + usage stats ----------------

def test_bazaar_declaration_and_settle_payload(ledger, monkeypatch):
    import jsonschema
    fac = FakeFacilitator()
    seen = {}

    async def settle(payload, req):
        seen["payload"] = payload
        return {"success": True, "transaction": "0x" + "cd" * 32, "network": req["network"]}
    fac.settle = settle
    acme = ledger.create_org("Acme")
    ledger.record(acme["org_id"], "agent-a", "claude", "tool_call", "x")
    as_org(monkeypatch, None)

    async def go():
        async with Client(server(ledger, fac)) as c:
            r = await c.call_tool("ledger_audit_stream", {"org_id": acme["org_id"], "stream_id": "agent-a"})
            pr = r.structured_content
            assert r.is_error and pr["resource"]["url"].endswith("/mcp") and pr["resource"]["serviceName"] == "Privi Ledger"
            bz = pr["extensions"]["bazaar"]
            jsonschema.validate(bz["info"], bz["schema"])
            assert bz["info"]["input"]["toolName"] == "ledger_audit_stream"
            jsonschema.validate(bz["info"]["input"]["example"], bz["info"]["input"]["inputSchema"])
            payment = {"x402Version": 2, "accepted": pr["accepts"][0], "payload": {"signature": "0x"}}
            ok = await c.call_tool("ledger_audit_stream", {"org_id": acme["org_id"], "stream_id": "agent-a"},
                                   meta={"x402/payment": payment})
            assert not ok.is_error and ok.structured_content["found"]
    anyio.run(go)
    p = seen["payload"]
    assert p["resource"]["url"].endswith("/mcp") and p["extensions"]["bazaar"]["info"]["input"]["type"] == "mcp"


def test_usage_stats_middleware(ledger):
    from starlette.testclient import TestClient
    from privi_ledger.usage import UsageMiddleware
    app = UsageMiddleware(server(ledger).streamable_http_app(host="0.0.0.0", stateless_http=True, json_response=True),
                          ledger._db, ledger._lock, "privi-ledger")
    hdrs = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    with TestClient(app, base_url="http://localhost") as http:
        for _ in range(3):
            r = http.post("/mcp", headers=hdrs, json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                                      "params": {"name": "fortress_keys", "arguments": {}}})
            assert r.status_code == 200 and "ML-DSA-87" in r.text
        http.post("/mcp", headers=hdrs, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        st = http.get("/stats").json()
    assert st["by_tool_all_time"] == {"fortress_keys": 3} and st["today"] == 3 and st["total_tool_calls"] == 3
