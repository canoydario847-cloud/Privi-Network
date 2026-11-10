"""One ledger for every Privi service: push reports, the health watch, and what Privi Quantum Scan shows."""

import importlib.util
import json
import sqlite3
from pathlib import Path

import anyio
import pytest

from privi_ledger.config import Settings
from privi_ledger.network import NETWORK_ORG_ID, Network, NetworkError, settlement_token, source_of
from privi_ledger.server import build_server
from privi_ledger.store import Ledger

PAY_TO = "0x1990589FD200E043b8C6FD9ec5956c61b3071048"
SERVICES = {"privi-verify": {"title": "Privi Verify", "url": "https://verify.example", "health": "/health", "push": True},
            "privi-discovery": {"title": "Privi Discovery Hub", "url": "https://hub.example", "health": "/health"}}
REPORTER = Path(__file__).resolve().parents[2] / "mcp-server" / "src" / "privi_verify" / "ledger_report.py"


def _ev(i, **kw):
    return {"id": f"evt-{i:08d}", "kind": "tool_call", "name": "verify_lot", "outcome": "success",
            "hash": "ab" * 32, "meta": {"status": 200}, **kw}


def test_ingest_records_entries_once_and_chains_them(tmp_path):
    ledger = Ledger(str(tmp_path / "n.db"))
    net = Network(ledger, SERVICES)
    r = net.ingest("privi-verify", [_ev(1), _ev(2, kind="http", name="POST /lots/{id}")], "0.4.0")
    assert r["accepted"] == 2 and not r["rejected"]
    again = net.ingest("privi-verify", [_ev(1), _ev(3)])
    assert again["accepted"] == 1 and again["duplicates"] == 1          # a retried event is never recorded twice
    assert again["receipts"][0]["entry_hash"] == r["receipts"][0]["entry_hash"]
    entries = ledger.entries(NETWORK_ORG_ID, "privi-verify")
    assert [e["seq"] for e in entries] == [1, 2, 3] and entries[0]["action_type"] == "tool_call"
    det = entries[0]["details"]
    assert (json.loads(det) if isinstance(det, str) else det)["request_fingerprint"] == "ab" * 32
    assert ledger.check_chain(entries).valid
    assert ledger.org_for_key("anything") is None                        # no API key opens the network organization


def test_ingest_rejects_bad_input_without_losing_good_events(tmp_path):
    net = Network(Ledger(str(tmp_path / "n.db")), SERVICES)
    r = net.ingest("privi-call", [_ev(1), {"id": "x"}, _ev(2, outcome="great"), _ev(3, hash="nothex"),
                                  _ev(4, meta={"nested": {"a": 1}})])
    assert r["accepted"] == 1 and len(r["rejected"]) == 4
    for bad in ("ledger", "privi-ledger", "privi-scan", "Privi Verify", "../x"):
        with pytest.raises(NetworkError):
            net.ingest(bad, [])
    with pytest.raises(NetworkError):
        net.ingest("privi-call", [_ev(i) for i in range(201)])


def test_watch_records_changes_only(tmp_path):
    ledger = Ledger(str(tmp_path / "n.db"))
    state = {"down": set(), "version": "1.0"}

    def fetch(url):
        if any(url.startswith(SERVICES[s]["url"]) for s in state["down"]):
            raise TimeoutError("timed out")
        return {"status": 200, "version": state["version"]}

    net = Network(ledger, SERVICES, fetch)
    assert net.watch_once() == 2                     # first sighting of each service
    assert net.watch_once() == 0                     # nothing changed: nothing recorded
    state["down"].add("privi-discovery")
    assert net.watch_once() == 0                     # one failed check is a blip (free services sleep)
    assert net.watch_once() == 1                     # two in a row is down
    assert net.watch_once() == 0
    state["down"].clear()
    assert net.watch_once() == 1                     # back up
    state["version"] = "1.1"
    assert net.watch_once() == 2                     # both services changed version
    summaries = [e["summary"] for e in ledger.entries(NETWORK_ORG_ID, "privi-discovery")]
    assert [s.split(":")[0] for s in summaries] == ["service.up", "service.down", "service.up", "service.version"]


def test_summary_shows_every_service_and_its_link(tmp_path):
    ledger = Ledger(str(tmp_path / "n.db"))
    net = Network(ledger, SERVICES, lambda url: {"status": 200, "version": None})
    net.watch_once()
    s = net.summary()                                # Verify runs the reporter but has not reported yet
    assert {x["service"]: x for x in s["services"]}["privi-verify"]["status"] == "not reporting" and not s["all_linked"]
    net.ingest("privi-verify", [_ev(1)], "0.4.0")
    s = net.summary()
    by = {x["service"]: x for x in s["services"]}
    assert set(by) == {"privi-ledger", "privi-scan", "privi-verify", "privi-discovery"}
    assert by["privi-verify"]["status"] == "reporting" and by["privi-verify"]["link"] == "push + watch"
    assert by["privi-verify"]["entries"] == 2 and by["privi-verify"]["version"] == "0.4.0"
    assert by["privi-discovery"]["status"] == "watched" and by["privi-discovery"]["health"] == "up"
    assert s["all_linked"] and s["linked"] == s["total"] == 4
    ledger._db.execute("UPDATE network_services SET last_seen='2020-01-01T00:00:00+00:00' WHERE service='privi-verify'")
    s = net.summary()
    assert {x["service"]: x for x in s["services"]}["privi-verify"]["status"] == "silent" and not s["all_linked"]
    assert "org_" not in json.dumps(s)               # never an organization id


def test_source_labels_never_reveal_customers():
    assert source_of(NETWORK_ORG_ID, "privi-call") == "privi-call"
    assert source_of("org_5ca95ca95ca95ca9", "mcp-registry") == "privi-scan"
    assert source_of("org_customer", "secret-agent-stream") == "privi-ledger"


class FakeFacilitator:
    async def verify(self, payload, req):
        return {"isValid": True}

    async def settle(self, payload, req):
        return {"success": True, "transaction": "0x" + "ab" * 32, "network": req["network"]}


def _client(monkeypatch, tmp_path, key="k" * 40):
    from starlette.testclient import TestClient
    monkeypatch.setenv("LEDGER_REPORT_KEY", key)
    ledger = Ledger(str(tmp_path / "h.db"))
    srv = build_server(Settings(pay_to=PAY_TO), ledger, FakeFacilitator())
    return TestClient(srv.streamable_http_app(stateless_http=True, json_response=True)), srv, ledger


def test_http_report_needs_the_key_and_lands_on_quantum_scan(monkeypatch, tmp_path):
    http, srv, ledger = _client(monkeypatch, tmp_path)
    with http:
        body = {"service": "privi-quantum", "version": "0.10.0", "events": [_ev(1, name="quantum_optimize")]}
        assert http.post("/quantum-ledger/report", json=body).status_code == 401
        assert http.post("/quantum-ledger/report", json=body, headers={"Authorization": "Bearer wrong"}).status_code == 401
        ok = http.post("/quantum-ledger/report", json=body, headers={"Authorization": "Bearer " + "k" * 40})
        assert ok.status_code == 200 and ok.json()["accepted"] == 1
        h = ok.json()["receipts"][0]["entry_hash"]
        assert http.post("/quantum-ledger/report", json={"service": "nope"},
                         headers={"Authorization": "Bearer " + "k" * 40}).status_code == 400
        org = ledger.create_org("Acme")["org_id"]
        ledger.record(org, "agent", "claude", "payment", "Paid invoice 1")
        srv.privi_qledger.seal(force=True)
        entries = http.get("/quantum-ledger/entries").json()["entries"]
        assert [(e["service"], e["block"]) for e in entries] == [("privi-ledger", 0), ("privi-quantum", 0)]
        assert entries[1]["entry_hash"] == h and "Acme" not in json.dumps(entries) and org not in json.dumps(entries)
        assert srv.privi_qledger.entry_proof(h)["valid"]                 # sealed in a quantum block like any entry
        svc = {x["service"]: x for x in http.get("/quantum-ledger/services").json()["services"]}
        assert svc["privi-quantum"]["status"] == "reporting" and svc["privi-quantum"]["last_entry_hash"] == h
        assert "Services" in http.get("/quantum-scan").text


def test_http_report_is_off_without_a_key(monkeypatch, tmp_path):
    http, _, _ = _client(monkeypatch, tmp_path, key="")
    with http:
        assert http.post("/quantum-ledger/report", json={"service": "privi-call"}).status_code == 503


@pytest.mark.skipif(not REPORTER.exists(), reason="shared reporter not in this checkout")
def test_reporter_outbox_delivers_to_ingest_after_an_outage(tmp_path):
    spec = importlib.util.spec_from_file_location("ledger_report", REPORTER)
    lr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lr)
    net = Network(Ledger(str(tmp_path / "n.db")), SERVICES)
    up = {"ok": False}

    def post(url, key, body):
        if not up["ok"]:
            raise ConnectionError("ledger restarting")
        assert key == "k" * 40 and url.endswith("/quantum-ledger/report")
        return net.ingest(body["service"], body["events"], body["version"])

    rep = lr.LedgerReporter("privi-call", "https://ledger.example", "k" * 40, "0.1.0",
                            str(tmp_path / "outbox.db"), post=post)
    for i in range(3):
        rep.report("tool_call", f"call_agent_{i}", request_hash="cd" * 32, meta={"status": 200})
    assert rep.flush() == 0 and rep.pending() == 3 and rep.last_error      # ledger down: nothing lost
    rep2 = lr.LedgerReporter("privi-call", "https://ledger.example", "k" * 40, "0.1.0",
                             str(tmp_path / "outbox.db"), post=post)        # the service itself restarts
    up["ok"] = True
    assert rep2.pending() == 3 and rep2.flush() == 3 and rep2.pending() == 0
    assert len(net.ledger.entries(NETWORK_ORG_ID, "privi-call")) == 3
    assert lr.settlement_token("k" * 40) == settlement_token("k" * 40)     # Ledger and Anchor agree on the marker
