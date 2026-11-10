"""The shared Quantum Ledger reporter: what it reports, what it never reports, and that it cannot break a service."""

import hashlib
import hmac
import json
from pathlib import Path

import anyio

from privi_verify.ledger_report import (LedgerReporter, ReportMiddleware, SETTLEMENT_HEADER, mask_path,
                                        settlement_token)

KEY = "k" * 40
ROOT = Path(__file__).resolve().parents[2]
COPIES = ["mcp-server/src/privi_verify", "anchor-server/src/privi_anchor", "quantum-server/src/privi_quantum",
          "call-server/src/privi_call", "wallet-server/src/privi_wallet"]


def _reporter(sent, key=KEY):
    def post(url, k, body):
        sent.append(body)
        return {"accepted": len(body["events"])}
    return LedgerReporter("privi-verify", "https://ledger.example", key, "0.4.0", post=post)


def _call(mw, method, path, body=b"", status=200, response=b"{}", headers=()):
    async def app(scope, receive, send):
        got = b""
        while True:
            m = await receive()
            got += m.get("body", b"")
            if not m.get("more_body"):
                break
        assert got == body                                   # the app still sees the whole request
        await send({"type": "http.response.start", "status": status, "headers": []})
        await send({"type": "http.response.body", "body": response})

    mw.app = app
    out = []

    async def run():
        chunks = [body[:5], body[5:]]

        async def receive():
            c = chunks.pop(0)
            return {"type": "http.request", "body": c, "more_body": bool(chunks)}

        async def send(m):
            out.append(m)

        await mw({"type": "http", "method": method, "path": path, "headers": list(headers)}, receive, send)

    anyio.run(run)
    return out


def _events(rep, sent):
    rep.flush()
    return [e for b in sent for e in b["events"]]


def test_tool_calls_are_reported_by_name_with_a_keyed_fingerprint_only():
    sent = []
    rep = _reporter(sent)
    mw = ReportMiddleware(None, rep)
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": "verify_lot", "arguments": {"lot_id": "SECRET-LOT-77"}}}).encode()
    out = _call(mw, "POST", "/mcp", body, response=b'{"result":{"isError":false}}')
    assert out[0]["status"] == 200 and out[1]["body"] == b'{"result":{"isError":false}}'    # response untouched
    _call(mw, "POST", "/mcp", body, response=b'{"result":{"isError": true}}')
    _call(mw, "POST", "/mcp", body, status=402)
    _call(mw, "POST", "/mcp", b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}')              # not activity
    _call(mw, "GET", "/health")
    evs = _events(rep, sent)
    assert [(e["kind"], e["name"], e["outcome"]) for e in evs] == [
        ("tool_call", "verify_lot", "success"), ("tool_call", "verify_lot", "failure"), ("tool_call", "verify_lot", "blocked")]
    assert evs[0]["hash"] == hmac.new(KEY.encode(), body, hashlib.sha256).hexdigest()
    assert evs[0]["hash"] != hashlib.sha256(body).hexdigest()         # cannot be guessed back without the key
    assert "SECRET-LOT-77" not in json.dumps(sent) and sent[0]["service"] == "privi-verify"


def test_http_changes_are_reported_by_route_with_ids_masked():
    sent = []
    rep = _reporter(sent)
    mw = ReportMiddleware(None, rep, skip_paths=("/voice/turn",))
    _call(mw, "POST", "/api/wallets/0x1990589FD200E043b8C6FD9ec5956c61b3071048/send", b'{"amount":"5"}')
    _call(mw, "POST", "/humans/approve/req_8f3a2b1c9d0e/finish", b"{}", status=403)
    _call(mw, "POST", "/wp-login.php", b"x=1", status=404)            # bots probing: not activity
    _call(mw, "POST", "/voice/turn", b"Digits=1")                     # skipped by the service
    assert [(e["name"], e["outcome"]) for e in _events(rep, sent)] == [
        ("POST /api/wallets/{id}/send", "success"), ("POST /humans/approve/{id}/finish", "blocked")]
    assert mask_path("/voice/inbound") == "/voice/inbound" and mask_path("/reports/rpt_1ad650b63f4cb902.pdf") == "/reports/{id}"


def test_the_ledgers_own_settlement_calls_are_not_reported_back():
    sent = []
    rep = _reporter(sent)
    mw = ReportMiddleware(None, rep)
    body = b'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"anchor_hashes","arguments":{}}}'
    _call(mw, "POST", "/mcp", body, headers=[(SETTLEMENT_HEADER, settlement_token(KEY).encode())])
    _call(mw, "POST", "/mcp", body, headers=[(SETTLEMENT_HEADER, b"forged")])
    _call(mw, "POST", "/mcp", body)
    assert len(_events(rep, sent)) == 2                               # only the marked call is skipped


def test_off_without_a_key_and_never_breaks_the_service(monkeypatch):
    sent = []
    off = _reporter(sent, key="")
    mw = ReportMiddleware(None, off)
    assert _call(mw, "POST", "/mcp", b'{"method":"tools/call"}')[0]["status"] == 200
    off.report("tool_call", "x")
    assert off.flush() == 0 and not sent and not off.enabled

    def boom(url, key, body):
        raise RuntimeError("ledger exploded")
    rep = LedgerReporter("privi-verify", "https://ledger.example", KEY, post=boom)
    mw = ReportMiddleware(None, rep)
    assert _call(mw, "POST", "/mcp", b"not json at all")[0]["status"] == 200
    assert _call(mw, "POST", "/x", b"{}")[0]["status"] == 200
    assert rep.flush() == 0 and rep.pending() == 1 and "ledger exploded" in rep.last_error


def test_bursts_are_throttled_into_one_count(monkeypatch):
    import privi_verify.ledger_report as lr
    sent, clock = [], [1_000_000.0]
    monkeypatch.setattr(lr, "MAX_PER_MIN", 5)
    monkeypatch.setattr(lr.time, "time", lambda: clock[0])
    rep = _reporter(sent)
    for i in range(50):
        rep.report("tool_call", f"t{i}")
    assert rep.pending() == 5
    clock[0] += 61
    rep.report("tool_call", "next-minute")
    evs = _events(rep, sent)
    assert len(evs) == 7 and evs[5]["name"] == "reports.throttled" and evs[5]["meta"]["not_reported"] == 45


def test_every_service_ships_the_same_reporter():
    files = [ROOT / c / "ledger_report.py" for c in COPIES]
    if not all(f.exists() for f in files):
        return                                                         # built from a single-service checkout
    assert len({f.read_bytes() for f in files}) == 1
