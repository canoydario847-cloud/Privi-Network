# Copyright (c) 2026 Privi World Co. All rights reserved.
"""Do-not-call list, calling hours, consent records and the pre-call check."""
import anyio
import pytest
from mcp import Client

from privi_call.outreach import Outreach, OutreachError, calling_hours, normalize_phone
from test_call import make


def test_normalize_phone():
    assert normalize_phone("(313) 555-0142") == "+13135550142" and normalize_phone("1-313-555-0142") == "+13135550142"
    assert normalize_phone("+44 20 7946 0958") == "+442079460958"
    with pytest.raises(OutreachError):
        normalize_phone("555-0142")


def test_calling_hours():
    ok = calling_hours("America/Detroit", "2026-11-13T18:00:00Z")          # 1 p.m. in Detroit
    assert ok["allowed"] and ok["local_time"].startswith("2026-11-13T13:00")
    late = calling_hours("America/Detroit", "2026-11-14T02:30:00Z")        # 9:30 p.m.
    assert not late["allowed"] and late["next_allowed_at"].startswith("2026-11-14T08:00")
    early = calling_hours("America/Los_Angeles", "2026-11-13T14:00:00Z")   # 6 a.m.
    assert not early["allowed"] and early["next_allowed_utc"].startswith("2026-11-13T16:00")
    assert not calling_hours("America/Detroit", "2026-11-14T01:30:00Z", end_hour=20)["allowed"]   # 8:30 p.m., stricter state window
    with pytest.raises(OutreachError):
        calling_hours("Mars/Olympus")
    with pytest.raises(OutreachError):
        calling_hours("America/Detroit", start_hour=6)


def test_lists_and_precheck(tmp_path):
    _, store, _ = make(tmp_path)
    out = Outreach(store)
    key, other = store.new_credit_key(10, "0xtx"), store.new_credit_key(10, "0xtx2")
    noon = "2026-11-13T17:00:00Z"
    with pytest.raises(OutreachError):
        out.dnc_check("pck_notreal", "3135550142")
    p = out.precheck(key, "3135550142", "America/Detroit", "marketing", ai_voice=True, recording=True, when=noon)
    assert not p["go"] and len(p["blockers"]) == 1 and "AI" in p["blockers"][0] and len(p["warnings"]) == 2
    out.consent_record(key, "313-555-0142", "ai_voice", "web_form", "ab" * 32)
    out.consent_record(key, "313-555-0142", "marketing_calls", "web_form")
    p = out.precheck(key, "3135550142", "America/Detroit", "marketing", ai_voice=True, when=noon)
    assert p["go"] and p["warnings"] == [] and p["consents"]["ai_voice"]
    assert not out.precheck(key, "3135550142", "America/Detroit", when="2026-11-14T03:00:00Z")["go"]       # 10 p.m.
    assert out.precheck(key, "3135550142", "America/Detroit", "informational", when="2026-11-14T03:00:00Z")["go"]
    # another customer's key sees none of this
    assert not out.consent_check(other, "3135550142")["consents"]["ai_voice"]["granted"]
    # the person withdraws: consents revoked, number on the do-not-call list
    r = out.consent_revoke(key, "3135550142")
    assert sorted(r["revoked"]) == ["ai_voice", "marketing_calls"] and r["on_do_not_call_list"]
    p = out.precheck(key, "3135550142", "America/Detroit", when=noon)
    assert not p["go"] and "do-not-call" in p["blockers"][0]
    assert out.dnc_check(key, "3135550142")["on_do_not_call_list"] and not out.dnc_check(other, "3135550142")["on_do_not_call_list"]
    assert out.dnc_remove(key, "3135550142")["removed"]
    chain = out.consent_verify_chain(key)
    assert chain == {"intact": True, "records": 4, "head_hash": chain["head_hash"]}
    store._db.execute("UPDATE out_consent SET action='granted' WHERE action='revoked'")
    assert out.consent_verify_chain(key)["intact"] is False
    assert "3135550142" not in str(store._db.execute("SELECT * FROM out_dnc").fetchall())      # numbers are never stored in the clear


def test_outreach_tools(tmp_path, monkeypatch):
    monkeypatch.setenv("CALL_ALL_TOOLS_PAID", "0")
    _, store, mcp = make(tmp_path)
    key = store.new_credit_key(5, "0xtx")

    async def go():
        async with Client(mcp) as c:
            names = {t.name for t in (await c.list_tools()).tools}
            assert {"call_do_not_call", "call_hours_check", "call_consent_record", "call_consent_revoke",
                    "call_consent_check", "call_precheck"} <= names
            a = await c.call_tool("call_do_not_call", {"call_key": key, "phone": "3135550142", "action": "add", "reason": "asked"})
            assert not a.is_error and a.structured_content["list_size"] == 1
            chk = (await c.call_tool("call_do_not_call", {"call_key": key, "phone": "3135550142"})).structured_content
            assert chk["on_do_not_call_list"] and chk["reason"] == "asked"
            pre = (await c.call_tool("call_precheck", {"call_key": key, "phone": "3135550142", "timezone": "America/Detroit",
                                                       "purpose": "informational"})).structured_content
            assert pre["go"] is False
            assert (await c.call_tool("call_precheck", {"call_key": "pck_bad", "phone": "3135550142", "timezone": "America/Detroit"})).is_error
            h = (await c.call_tool("call_hours_check", {"timezone": "America/Chicago", "when": "2026-11-13T18:00:00Z"})).structured_content
            assert h["allowed"]
            assert (await c.call_tool("call_consent_check", {"call_key": key})).structured_content["intact"]
    anyio.run(go)
