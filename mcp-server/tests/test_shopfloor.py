"""ChainFlow Shop Floor: recall trace, certificates of conformance, lot documents, NCRs, gauge calibration."""
import hashlib
from datetime import datetime, timedelta, timezone

import anyio
import pytest
from mcp import Client
from starlette.testclient import TestClient

from privi_verify.server import build_server
from privi_verify.shopfloor import ShopError, ShopFloor
from test_server import settings, store  # noqa: F401

PH = "Port Huron, MI"


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


def test_recall_trace(store):
    shop = ShopFloor(store)
    store.record_event("COIL-9", "received", PH, "Acme Steel", product="Steel coil")
    shop.link("COIL-9", "LOT-1", "Blue Water Fab", PH, "1 t")
    shop.link("LOT-1", "ASSY-7", "Blue Water Fab", PH)
    shop.link("COIL-9", "LOT-2", "Blue Water Fab", PH)
    with pytest.raises(ShopError, match="loop"):
        shop.link("ASSY-7", "COIL-9", "x y", PH)
    with pytest.raises(ShopError, match="no events"):
        shop.link("NOPE", "LOT-1", "x y", PH)
    t = shop.trace("COIL-9")
    assert [(x["lot_code"], x["steps_away"]) for x in t["made_into"]] == [("LOT-1", 1), ("LOT-2", 1), ("ASSY-7", 2)]
    assert t["already_shipped"] == ["LOT-1"] and t["made_from"] == []
    assert [x["lot_code"] for x in shop.trace("ASSY-7")["made_from"]] == ["LOT-1", "COIL-9"]
    assert store.check_chain(store.events("LOT-1")).valid and store.events("ASSY-7")[0]["notes"] == "Made from lot LOT-1"


def test_documents_ncr_and_certificate(store):
    shop = ShopFloor(store, "https://v.example")
    d = shop.attach("LOT-1", "mill_test_report", sha("mtr"), "Acme Steel", "QA", PH, "Heat 4471")
    assert d["attached"] and shop.document_check(sha("mtr"))["attached_to"][0]["lot_code"] == "LOT-1"
    assert not shop.document_check(sha("edited"))["known"]
    assert shop.documents("LOT-1")["missing_common"] == ["inspection_report"]
    with pytest.raises(ShopError):
        shop.attach("LOT-1", "mill_test_report", sha("mtr"), "Acme Steel", "QA", PH)
    ncr = shop.ncr_open("LOT-1", "Hole diameter oversize on 12 pcs", "major", "QA Lead", PH, "12 pcs")
    with pytest.raises(ShopError, match="open non-conformance"):
        shop.coc_issue("LOT-1", "Detroit OEM", "DWG A-12 rev C", "Dana Q", "Quality Manager", PH)
    closed = shop.ncr_close(ncr["ncr_id"], "scrap", "Drill bit replaced; 12 pcs scrapped", "QA Lead", PH)
    assert closed["status"] == "closed" and shop.ncr_list("LOT-1")["open"] == 0
    with pytest.raises(ShopError):
        shop.ncr_close(ncr["ncr_id"], "scrap", "again", "QA Lead", PH)
    c = shop.coc_issue("LOT-1", "Detroit OEM", "DWG A-12 rev C", "Dana Q", "Quality Manager", PH, "788 pcs", "PO-5512")
    cert = c["certificate"]
    assert cert["supporting_documents"][0]["sha256"] == sha("mtr") and c["certificate_sha256"] == sha(c["certificate_json"])
    assert shop.coc_verify(cert["coc_id"])["valid"] and shop.coc_verify("", c["certificate_json"])["valid"]
    assert not shop.coc_verify("", c["certificate_json"].replace("788", "800"))["valid"]
    store.record_event("LOT-1", "recalled", PH, "Blue Water Fab")
    v = shop.coc_verify(cert["coc_id"])
    assert not v["valid"] and v["lot_recalled"]
    with pytest.raises(ShopError, match="recalled"):
        shop.coc_issue("LOT-1", "Detroit OEM", "DWG A-12 rev C", "Dana Q", "Quality Manager", PH)
    assert not shop.coc_revoke(cert["coc_id"], "issued in error", "Dana Q", PH)["valid"]
    assert store.check_chain(store.events("LOT-1")).valid


def test_gauges(store):
    shop = ShopFloor(store)
    assert shop.gauge_save("MIC-014", "0-1 in micrometer", 365)["status"] == "never_calibrated"
    old = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
    assert shop.gauge_calibrated("MIC-014", sha("c1"), "Cal Lab", "pass", old)["status"] == "overdue"
    g = shop.gauge_calibrated("MIC-014", sha("c2"), "Cal Lab")
    assert g["status"] == "in_calibration" and g["usable"] and 364 < g["days_left"] <= 365
    shop.gauge_save("CAL-2", "Caliper", 180)
    shop.gauge_calibrated("CAL-2", sha("c3"), "Cal Lab", "fail")
    due = shop.gauges_due()
    assert due["do_not_use"] == ["CAL-2"] and due["counts"]["failed_last_calibration"] == 1
    with pytest.raises(ShopError):
        shop.gauge_calibrated("MIC-014", sha("c"), "Cal Lab", calibrated_at="2999-01-01")


def test_tools_need_manufacturer_key(store, monkeypatch):
    monkeypatch.setenv("PRIVI_ALL_TOOLS_PAID", "0")
    srv = build_server(settings(), store)

    async def go():
        async with Client(srv) as c:
            names = {t.name for t in (await c.list_tools()).tools}
            assert {"chainflow_link_lots", "chainflow_recall_trace", "chainflow_coc_issue", "chainflow_coc_verify",
                    "chainflow_attach_document", "chainflow_ncr_open", "chainflow_gauges_due"} <= names
            args = {"lot_code": "LOT-1", "defect": "Burrs on edge", "severity": "minor", "opened_by": "QA", "location": PH}
            monkeypatch.delenv("PRIVI_ALLOW_LOCAL_WRITES", raising=False)
            assert "manufacturer key" in (await c.call_tool("chainflow_ncr_open", args)).structured_content["error"]
            assert (await c.call_tool("chainflow_ncr_list", {})).is_error and (await c.call_tool("chainflow_gauges_due", {})).is_error
            assert not (await c.call_tool("chainflow_recall_trace", {"lot_code": "LOT-1"})).is_error
            monkeypatch.setenv("PRIVI_ALLOW_LOCAL_WRITES", "1")
            r = await c.call_tool("chainflow_ncr_open", args)
            assert not r.is_error and r.structured_content["status"] == "open"
            assert (await c.call_tool("chainflow_ncr_list", {"status": "open"})).structured_content["open"] == 1
            assert (await c.call_tool("chainflow_coc_verify", {})).is_error
    anyio.run(go)
    http = TestClient(srv.streamable_http_app())
    assert http.get("/coc/coc_nope").status_code == 404


def test_shopfloor_tools_are_paid(store, monkeypatch):
    monkeypatch.setenv("PRIVI_ALL_TOOLS_PAID", "1")
    from test_server import FakeFacilitator

    async def go():
        async with Client(build_server(settings(), store, FakeFacilitator())) as c:
            need = await c.call_tool("chainflow_recall_trace", {"lot_code": "LOT-1"})
            assert need.is_error and need.structured_content["accepts"][0]["amount"] == "10000"
    anyio.run(go)
