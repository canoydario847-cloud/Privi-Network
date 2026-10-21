"""Privi Live: approvals, kill switch, streams, trust feed, gateway, rooms."""
import json
import time

import anyio
import httpx2
import pytest
from mcp import Client
from starlette.requests import Request
from starlette.testclient import TestClient

from privi_ledger import gateway as gw_mod
from privi_ledger import live as live_mod
from privi_ledger.live import make_filter, mount_ws
from test_ledger import _eth_wallet, as_org, server


def mk(ledger):
    s = server(ledger)
    app = s.streamable_http_app(host="0.0.0.0", stateless_http=True, json_response=True)
    mount_ws(app, s.privi_ws_routes)
    return s, app


def runner(ledger, monkeypatch):
    def run_(key, name, args):
        as_org(monkeypatch, key)

        async def go():
            async with Client(server(ledger)) as c:
                return await c.call_tool(name, args)
        return anyio.run(go)
    return run_


def recv(ws, want, limit=12):
    """Read frames until one of the wanted type arrives (skipping heartbeats and presence)."""
    for _ in range(limit):
        f = ws.receive_json()
        if f["type"] == want:
            return f
    raise AssertionError(f"no {want} frame")


# ---------------- approvals, policy, kill switch ----------------

def test_live_approvals_policy_and_kill_switch(ledger, monkeypatch):
    shop = ledger.create_org("ShopBot Inc")
    human, human_sign = _eth_wallet()
    stranger, stranger_sign = _eth_wallet()
    run_ = runner(ledger, monkeypatch)
    key = shop["api_key"]
    d = run_(key, "mandate_create", {"stream_id": "shopper", "principal_wallet": human, "max_total_usdc": "500",
                                     "max_per_payment_usdc": "100", "payees": ["store.example.com"],
                                     "purpose": "Buy supplies", "days": 7}).structured_content
    mid = d["mandate_id"]
    s, app = mk(ledger)
    live = s.privi_live
    ok = lambda amt, **kw: run_(key, "mandate_spend", {"mandate_id": mid, "amount_usdc": amt, "payee": "store.example.com", **kw})

    with TestClient(app) as http:
        assert http.post(f"/mandates/{mid}/activate", json={"signature": human_sign(d["message"])}).status_code == 200
        assert not run_(key, "approval_policy_set", {"stream_id": "shopper", "approve_over_usdc": "10"}).is_error
        assert run_(None, "approval_policy_set", {"stream_id": "shopper", "approve_over_usdc": "10"}).is_error

        assert ok("5").structured_content["allow"]                       # under threshold: normal
        held = ok("20")                                                   # over: held for a human
        h = held.structured_content
        assert held.is_error and h["approval_required"] and h["approve_url"].endswith(h["approval_id"])
        aid = h["approval_id"]
        st = run_(None, "approval_status", {"approval_id": aid}).structured_content
        assert st["status"] == "pending" and st["approver"].lower() == human.lower() and st["mandate_id"] == mid
        assert "personal_sign" in http.get(f"/approve/{aid}").text
        j = http.get(f"/approvals/{aid}").json()

        # only the mandate's principal can decide, and only for the decision they signed
        dec = lambda who, decision, msg: http.post(f"/approvals/{aid}/decide", json={"decision": decision, "signature": who(msg)})
        assert dec(stranger_sign, "approve", j["messages"]["approve"]).status_code == 400
        assert dec(human_sign, "approve", j["messages"]["deny"]).status_code == 400
        assert ok("20", approval_id=aid).is_error                         # still pending
        r = dec(human_sign, "approve", j["messages"]["approve"])
        assert r.status_code == 200 and r.json()["status"] == "approved" and r.json()["use_until"]
        assert dec(human_sign, "approve", j["messages"]["approve"]).status_code == 400   # already decided

        # an approval is for exactly one payment, once
        good = ok("20", approval_id=aid).structured_content
        assert good["allow"] and good["spend_id"]
        assert "already used" in ok("20", approval_id=aid).structured_content["error"]
        a2 = ok("30").structured_content["approval_id"]
        j2 = http.get(f"/approvals/{a2}").json()
        assert http.post(f"/approvals/{a2}/decide", json={"decision": "approve", "signature": human_sign(j2["messages"]["approve"])}).status_code == 200
        assert "different payment" in ok("31", approval_id=a2).structured_content["error"]
        assert ok("30", approval_id=a2).structured_content["allow"]
        a3 = ok("40").structured_content["approval_id"]
        j3 = http.get(f"/approvals/{a3}").json()
        assert http.post(f"/approvals/{a3}/decide", json={"decision": "deny", "signature": human_sign(j3["messages"]["deny"])}).json()["status"] == "denied"
        assert "denied" in ok("40", approval_id=a3).structured_content["error"]

        # a failed spend gives the approval back
        a4 = ok("90").structured_content["approval_id"]
        j4 = http.get(f"/approvals/{a4}").json()
        http.post(f"/approvals/{a4}/decide", json={"decision": "approve", "signature": human_sign(j4["messages"]["approve"])})
        assert run_(key, "mandate_spend", {"mandate_id": mid, "amount_usdc": "90", "payee": "store.example.com",
                                           "approval_id": a4}).structured_content["allow"]

        # waiting: decided returns at once; pending times out
        assert run_(None, "approval_wait", {"approval_id": a4, "timeout_s": 1}).structured_content["status"] == "approved"
        free = run_(key, "approval_request", {"stream_id": "shopper", "action": "Delete the staging database",
                                              "approver_wallet": human, "ttl_s": 60}).structured_content
        t0 = time.monotonic()
        w = run_(None, "approval_wait", {"approval_id": free["approval_id"], "timeout_s": 1}).structured_content
        assert w["status"] == "pending" and time.monotonic() - t0 >= 0.9
        assert run_(key, "approval_request", {"stream_id": "shopper", "action": "x"}).is_error      # no decider named
        assert run_(key, "approval_cancel", {"approval_id": free["approval_id"]}).structured_content["status"] == "cancelled"

        # kill switch
        k = run_(key, "live_kill", {"stream_id": "shopper", "reason": "rogue loop"})
        assert not k.is_error and k.structured_content["killed"]
        blocked = ok("1")
        assert blocked.is_error and blocked.structured_content["killed"] and "rogue loop" in blocked.structured_content["error"]
        assert run_(None, "live_kill", {"stream_id": "*"}).is_error
        assert run_(key, "live_status", {}).structured_content["killed"][0]["stream_id"] == "shopper"
        assert run_(key, "live_resume", {"stream_id": "shopper"}).structured_content["resumed"]
        assert ok("1").structured_content["allow"]

    types = [e["type"] for e in live.bus.recent(f"org:{shop['org_id']}", 100)]
    for t in ("approval.requested", "approval.approved", "approval.denied", "agent.killed", "agent.resumed"):
        assert t in types, t
    entries = ledger.entries(shop["org_id"], "shopper")
    assert ledger.check_chain(entries).valid and any(e["outcome"] == "blocked" for e in entries)


# ---------------- streams ----------------

def test_websocket_stream_org_tail_and_kill(ledger, monkeypatch):
    acme, other = ledger.create_org("Acme"), ledger.create_org("Other")
    s, app = mk(ledger)
    live = s.privi_live
    with TestClient(app, base_url="http://localhost") as http:
        with http.websocket_connect("/live/ws") as ws:
            ws.send_json({"type": "subscribe", "channels": ["org"]})
            assert "needs your organization API key" in recv(ws, "error")["error"]
            ws.send_json({"type": "auth", "key": "nope"})
            assert recv(ws, "auth")["ok"] is False
            ws.send_json({"type": "auth", "key": acme["api_key"]})
            assert recv(ws, "auth")["ok"] is True
            ws.send_json({"type": "subscribe", "channels": [f"org:{other['org_id']}"]})
            assert "own organization" in recv(ws, "error")["error"]
            ws.send_json({"type": "subscribe", "channels": ["org", "trust"]})
            assert recv(ws, "subscribed")["delay_seconds"] == 0
            ws.send_json({"type": "ping"})
            assert recv(ws, "pong")

            ledger.record(acme["org_id"], "agent-1", "claude", "payment", "Paid invoice 7")          # live tail
            live.emit_trust("passport.issued", {"passport_id": "pp_x", "org_id": acme["org_id"], "score": 700}, None)
            got = {recv(ws, "event")["event"] for _ in range(2)}
            assert got == {"entry.recorded", "passport.issued"}

            ws.send_json({"type": "kill", "stream_id": "agent-1", "reason": "test"})
            assert recv(ws, "kill")["killed"] is True
            assert live.is_killed(acme["org_id"], "agent-1")
            assert recv(ws, "event")["event"] == "agent.killed"
            ws.send_json({"type": "resume", "stream_id": "agent-1"})
            assert recv(ws, "resume")["resumed"] is True
            ws.send_json({"type": "bogus"})
            assert recv(ws, "error")
        # replay and filters on a fresh anonymous connection
        with http.websocket_connect("/live/ws") as ws:
            monkeypatch.setattr(live_mod, "FREE_DELAY_S", 0.0)
            ws.send_json({"type": "subscribe", "channels": ["trust"], "replay": 5, "filter": {"passport_id": "pp_x"}})
            assert recv(ws, "subscribed")
            assert recv(ws, "event")["data"]["passport_id"] == "pp_x"
    assert live._org_subs.get(acme["org_id"], 0) == 0       # tail stops when the last listener leaves
    assert live._conns.get("anon", 0) == 0


def test_free_and_anonymous_get_delayed_trust_feed(ledger, monkeypatch):
    s, app = mk(ledger)
    live = s.privi_live
    free = live.plans.signup("Tiny Co")
    pro = ledger.create_org("Big Co")                                  # enterprise = real time
    monkeypatch.setattr(live_mod, "FREE_DELAY_S", 3600.0)
    assert live.public_delay(None) == 3600 and live.public_delay(free) == 3600 and live.public_delay(pro) == 0
    live.emit_trust("passport.revoked", {"passport_id": "pp_late"}, None)
    assert live.bus.since("trust", 0, 3600) == []
    assert live.bus.since("trust", 0, 0)[0]["type"] == "passport.revoked"
    with TestClient(app, base_url="http://localhost") as http:
        body = http.get("/live/trust/recent").json()
        assert body["delay_seconds"] == 3600 and body["events"] == []
        body = http.get("/live/trust/recent", headers={"Authorization": f"Bearer {pro['api_key']}"}).json()
        assert body["delay_seconds"] == 0 and body["events"][0]["data"]["passport_id"] == "pp_late"
        assert http.get("/live/trust/recent", headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert http.get("/live/events?channels=org").status_code == 401
        assert http.get("/live/events?channels=nope").status_code == 400
        assert "WebSocket" in http.get("/live").text
    specs, err = live.resolve_channels(["trust"], free)
    assert specs == [("trust", 3600.0)] and err is None


def test_sse_stream_replay_and_live(ledger, monkeypatch):
    s, _ = mk(ledger)
    live = s.privi_live
    acme = ledger.create_org("Acme")
    live.emit_trust("passport.issued", {"passport_id": "pp_old"}, None)

    async def go():
        scope = {"type": "http", "method": "GET", "path": "/live/events", "query_string": b"channels=org,trust&replay=5",
                 "headers": [(b"authorization", f"Bearer {acme['api_key']}".encode())], "client": ("1.2.3.4", 1),
                 "server": ("t", 80), "scheme": "http"}
        resp = await live.sse(Request(scope))
        assert resp.media_type == "text/event-stream"
        it = resp.body_iterator
        assert "connected" in await it.__anext__()
        first = await it.__anext__()
        assert "event: passport.issued" in first and "pp_old" in first and first.startswith("id: ")
        live.emit_trust("passport.revoked", {"passport_id": "pp_new"}, acme["org_id"])
        seen = ""
        for _ in range(3):
            seen += await it.__anext__()
            if "pp_new" in seen:
                break
        assert "event: passport.revoked" in seen
        await it.aclose()
    anyio.run(go)
    assert live._conns.get(acme["org_id"], 0) == 0


# ---------------- trust feed ----------------

def test_trust_feed_events_and_watcher(ledger, monkeypatch):
    acme = ledger.create_org("Acme")
    for i in range(12):
        ledger.record(acme["org_id"], "treasury-agent", "claude", "approval" if i % 3 == 0 else "payment", f"p{i}")
    run_ = runner(ledger, monkeypatch)
    key = acme["api_key"]
    addr, sign = _eth_wallet()
    human, human_sign = _eth_wallet()
    s, app = mk(ledger)
    live, watcher = s.privi_live, s.privi_trust

    ch = run_(key, "kya_challenge", {"address": addr}).structured_content
    assert run_(key, "kya_bind_wallet", {"address": addr, "challenge_id": ch["challenge_id"], "signature": sign(ch["message"]),
                                         "stream_id": "treasury-agent"}).structured_content["bound"]
    pp = run_(key, "passport_issue", {"stream_id": "treasury-agent"}).structured_content
    events = live.bus.recent("trust", 50)
    by = {e["type"]: e for e in events}
    assert by["kya.bound"]["data"]["address"].lower() == addr.lower()
    assert by["passport.issued"]["data"]["passport_id"] == pp["passport_id"]
    assert addr.lower() in [a.lower() for a in by["passport.issued"]["data"]["addresses"]]
    f = make_filter({"address": addr})
    assert f(by["passport.issued"]) and f(by["kya.bound"]) and not make_filter({"address": human})(by["kya.bound"])
    assert make_filter({"types": ["passport."]})(by["passport.issued"]) and not make_filter({"types": ["passport."]})(by["kya.bound"])
    assert run_(key, "trust_events", {"address": addr}).structured_content["events"]

    # watcher: first sight is silent, tampering is announced to the public feed and the owner
    assert watcher.run_once() == 0
    assert watcher.run_once() == 0
    ledger._db.execute("UPDATE entries SET summary='tampered' WHERE org_id=? AND stream_id='treasury-agent' AND seq=3", (acme["org_id"],))
    ledger._db.commit()
    assert watcher.run_once() == 1
    ev = live.bus.recent("trust", 1)[0]
    assert ev["type"] == "passport.state_changed" and ev["data"]["to"] == "broken" and ev["data"]["passport_id"] == pp["passport_id"]
    assert addr.lower() in [a.lower() for a in ev["data"]["addresses"]]
    assert live.bus.recent(f"org:{acme['org_id']}", 1)[0]["type"] == "passport.state_changed"
    assert watcher.run_once() == 0                                       # no repeat announcements

    # revocation and unbinding are pushed
    assert not run_(key, "kya_unbind_wallet", {"address": addr}).is_error
    assert not run_(key, "passport_revoke", {"passport_id": pp["passport_id"], "reason": "retired"}).is_error
    types = [e["type"] for e in live.bus.recent("trust", 50)]
    assert "kya.unbound" in types and "passport.revoked" in types

    # mandate events land on the trust feed and on the mandate's own channel
    d = run_(key, "mandate_create", {"stream_id": "treasury-agent", "principal_wallet": human, "max_total_usdc": "10",
                                     "purpose": "x"}).structured_content
    mid = d["mandate_id"]
    with TestClient(app) as http:
        assert http.post(f"/mandates/{mid}/activate", json={"signature": human_sign(d["message"])}).status_code == 200
        assert http.post(f"/mandates/{mid}/revoke", json={"signature": human_sign(f"Revoke Privi Mandate {mid}")}).status_code == 200
    assert [e["type"] for e in live.bus.recent(f"mandate:{mid}", 10)] == ["mandate.activated", "mandate.revoked"]
    assert "mandate.revoked" in [e["type"] for e in live.bus.recent("trust", 50)]


# ---------------- gateway ----------------

def make_upstream(seen):
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse, Response
    from starlette.routing import Route

    async def mcp_(request):
        seen.append({"method": request.method, "headers": dict(request.headers)})
        if request.method == "DELETE":
            return Response(status_code=204)
        body = await request.json()
        rid = body.get("id")
        if body.get("method") == "tools/call":
            name = body["params"]["name"]
            if name == "echo":
                return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": {"content": [
                    {"type": "text", "text": json.dumps(body["params"].get("arguments"))}]}}, headers={"Mcp-Session-Id": "sess-1"})
            if name == "paid":
                return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": {"isError": True, "content": [],
                                     "structuredContent": {"x402Version": 2, "accepts": [{"scheme": "exact"}]}}})
            if name == "stream":
                return Response("event: message\ndata: " + json.dumps({"jsonrpc": "2.0", "id": rid, "result": {"content": []}})
                                + "\n\n", media_type="text/event-stream")
            if name == "sse_echo":
                return Response("event: message\ndata: " + json.dumps({"jsonrpc": "2.0", "id": rid, "result": {"content": [
                    {"type": "text", "text": json.dumps(body["params"].get("arguments"))}]}}) + "\n\n", media_type="text/event-stream")
            if name == "boom":
                return JSONResponse({"jsonrpc": "2.0", "id": rid, "error": {"code": -32000, "message": "boom"}})
        return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": {"tools": []}})
    return Starlette(routes=[Route("/mcp", mcp_, methods=["POST", "DELETE"])])


CALL = lambda name, rid=1, **args: {"jsonrpc": "2.0", "id": rid, "method": "tools/call", "params": {"name": name, "arguments": args}}


def test_gateway_proxy_meter_gate_rate_kill(ledger, monkeypatch):
    from privi_ledger.usage import UsageMiddleware
    monkeypatch.setenv("GW_ALLOW_PRIVATE", "1")
    acme = ledger.create_org("Acme")
    for i in range(12):
        ledger.record(acme["org_id"], "treasury-agent", "claude", "approval" if i % 3 == 0 else "payment", f"p{i}")
    run_ = runner(ledger, monkeypatch)
    key = acme["api_key"]
    seen = []
    s, app = mk(ledger)
    gws = s.privi_gateways
    gws._client = httpx2.AsyncClient(transport=httpx2.ASGITransport(app=make_upstream(seen)), base_url="http://up.test")
    wrapped = UsageMiddleware(app, ledger._db, ledger._lock, "privi-ledger")

    g = run_(key, "gateway_create", {"name": "acme-search", "upstream_url": "http://up.test/mcp"}).structured_content
    gid = g["gw_id"]
    assert g["http_url"].endswith(f"/gw/{gid}/mcp") and g["ws_url"].startswith(("ws://", "wss://")) and g["upstream_host"] == "up.test"
    assert run_(None, "gateway_create", {"name": "x", "upstream_url": "http://up.test/mcp"}).is_error
    hdrs = {"Accept": "application/json, text/event-stream", "Authorization": "Bearer upstream-secret"}

    with TestClient(wrapped, base_url="http://localhost") as http:
        r = http.post(f"/gw/{gid}/mcp", headers=hdrs, json=CALL("echo", q="hi"))
        assert r.status_code == 200 and r.json()["result"]["content"][0]["text"] == '{"q": "hi"}'
        assert r.headers["x-privi-gateway"] == gid and r.headers["mcp-session-id"] == "sess-1"
        up = seen[-1]["headers"]
        assert up["authorization"] == "Bearer upstream-secret" and "x-privi-wallet" not in up and up["accept-encoding"] == "identity"
        assert http.post(f"/gw/{gid}/mcp", headers=hdrs, json=CALL("paid")).status_code == 200
        assert "event: message" in http.post(f"/gw/{gid}/mcp", headers=hdrs, json=CALL("stream")).text
        assert http.post(f"/gw/{gid}/mcp", headers=hdrs, json=CALL("boom")).json()["error"]["message"] == "boom"
        assert http.post(f"/gw/{gid}/mcp", headers=hdrs, json={"jsonrpc": "2.0", "id": 9, "method": "tools/list"}).json()["result"] == {"tools": []}
        assert http.post(f"/gw/{gid}/mcp", content=b"not json").status_code == 400
        assert http.get(f"/gw/{gid}/mcp").status_code == 405
        assert http.post("/gw/gw_nope/mcp", json=CALL("echo")).status_code == 404
        assert http.get(f"/gw/{gid}").json()["gw_id"] == gid
        # other people's tools are not counted as Privi's own tool calls
        assert http.get("/stats").json()["total_tool_calls"] == 0

        st = run_(key, "gateway_stats", {"gw_id": gid}).structured_content
        tools = {t["tool"]: t for t in st["by_tool"]}
        assert tools["echo"]["calls"] == 1 and tools["paid"]["payment_required"] == 1 and tools["boom"]["errors"] == 1
        assert tools["stream"]["calls"] == 1
        entries = ledger.entries(acme["org_id"], st["log_stream"])
        assert ledger.check_chain(entries).valid
        assert sum(e["action_type"] == "tool_call" for e in entries) == 4 and "echo" in "".join(e["summary"] for e in entries)
        assert any(e["outcome"] == "failure" for e in entries)

        # websocket front door: same JSON-RPC, one persistent connection, session id carried between frames
        with http.websocket_connect(f"/gw/{gid}/ws") as ws:
            ws.send_json(CALL("echo", 5, via="ws"))
            assert json.loads(ws.receive_json()["result"]["content"][0]["text"]) == {"via": "ws"}
            ws.send_json(CALL("stream", 6))
            assert ws.receive_json()["id"] == 6
            ws.send_json(CALL("echo", 7, again=True))
            assert ws.receive_json()["id"] == 7
            assert seen[-1]["headers"].get("mcp-session-id") == "sess-1"
            ws.send_text("{nope")
            assert ws.receive_json()["error"]["code"] == -32700
        assert http.delete(f"/gw/{gid}/mcp").status_code == 204

        # kill switch stops the gateway at once
        run_(key, "live_kill", {"stream_id": "*", "reason": "incident"})
        r = http.post(f"/gw/{gid}/mcp", headers=hdrs, json=CALL("echo"))
        assert r.status_code == 503 and "incident" in r.json()["error"]["message"]
        run_(key, "live_resume", {"stream_id": "*"})
        assert http.post(f"/gw/{gid}/mcp", headers=hdrs, json=CALL("echo")).status_code == 200

        # rate limit per caller
        g2 = run_(key, "gateway_create", {"name": "slow", "upstream_url": "http://up.test/mcp", "rate_per_min": 2}).structured_content
        codes = [http.post(f"/gw/{g2['gw_id']}/mcp", json=CALL("echo")).status_code for _ in range(3)]
        assert codes == [200, 200, 429]

        # Passport gate: callers must prove a KYA wallet whose passport scores high enough
        addr, sign = _eth_wallet()
        stranger, stranger_sign = _eth_wallet()
        g3 = run_(key, "gateway_create", {"name": "members", "upstream_url": "http://up.test/mcp", "min_score": 100}).structured_content
        g3id = g3["gw_id"]
        assert g3["caller_gate"]["required"]
        anon = http.post(f"/gw/{g3id}/mcp", json=CALL("echo"))
        assert anon.status_code == 401 and "Passport" in anon.json()["error"]["message"]

        def proof(who, signer, gwid=g3id, ts=None):
            ts = ts or int(time.time())
            return {"X-Privi-Wallet": who, "X-Privi-Timestamp": str(ts),
                    "X-Privi-Signature": signer(f"Privi Gateway {gwid}\nTimestamp: {ts}")}
        # wallet not bound yet -> KYA denies
        assert "KYA denied" in http.post(f"/gw/{g3id}/mcp", headers=proof(addr, sign), json=CALL("echo")).json()["error"]["message"]
        ch = run_(key, "kya_challenge", {"address": addr}).structured_content
        run_(key, "kya_bind_wallet", {"address": addr, "challenge_id": ch["challenge_id"], "signature": sign(ch["message"]),
                                      "stream_id": "treasury-agent"})
        run_(key, "passport_issue", {"stream_id": "treasury-agent"})
        good = proof(addr, sign)
        assert http.post(f"/gw/{g3id}/mcp", headers=good, json=CALL("echo")).status_code == 200
        assert "already used" in http.post(f"/gw/{g3id}/mcp", headers=good, json=CALL("echo")).json()["error"]["message"]
        forged = proof(addr, stranger_sign)
        assert "not from that wallet" in http.post(f"/gw/{g3id}/mcp", headers=forged, json=CALL("echo")).json()["error"]["message"]
        old = proof(addr, sign, ts=int(time.time()) - 3600)
        assert "5 minutes" in http.post(f"/gw/{g3id}/mcp", headers=old, json=CALL("echo")).json()["error"]["message"]
        with http.websocket_connect(f"/gw/{g3id}/ws") as ws:                 # in-band proof over the websocket
            ws.send_json(CALL("echo", 1))
            assert ws.receive_json()["error"]["code"] == -32001
            p = proof(addr, sign)
            ws.send_json({"type": "privi.auth", "wallet": p["X-Privi-Wallet"], "timestamp": p["X-Privi-Timestamp"],
                          "signature": p["X-Privi-Signature"]})
            assert ws.receive_json()["ok"] is True
            ws.send_json(CALL("echo", 2))
            assert ws.receive_json()["result"]

        # management
        assert len(run_(key, "gateway_list", {}).structured_content["gateways"]) == 3
        other = ledger.create_org("Other")
        assert run_(other["api_key"], "gateway_stats", {"gw_id": gid}).is_error
        assert run_(other["api_key"], "gateway_delete", {"gw_id": gid}).is_error
        assert run_(key, "gateway_delete", {"gw_id": g2["gw_id"]}).structured_content["disabled"]
        assert http.post(f"/gw/{g2['gw_id']}/mcp", json=CALL("echo")).status_code == 404


def test_gateway_free_quota_and_upstream_safety(ledger, monkeypatch):
    run_ = runner(ledger, monkeypatch)
    # upstream safety: private, loopback and plain-http targets are refused
    monkeypatch.delenv("GW_ALLOW_PRIVATE", raising=False)
    acme = ledger.create_org("Acme")
    for url in ("https://127.0.0.1/mcp", "https://10.0.0.5/mcp", "https://169.254.169.254/latest", "http://example.com/mcp",
                "https://localhost/mcp", "https://user:pw@example.com/mcp", "https://service.internal/mcp"):
        r = run_(acme["api_key"], "gateway_create", {"name": "bad", "upstream_url": url})
        assert r.is_error, url

    # free plan: monthly cap on proxied tool calls, max two gateways
    monkeypatch.setenv("GW_ALLOW_PRIVATE", "1")
    monkeypatch.setattr(gw_mod, "FREE_MONTHLY", 2)
    s, app = mk(ledger)
    free = s.privi_live.plans.signup("Tiny Co")
    s.privi_gateways._client = httpx2.AsyncClient(transport=httpx2.ASGITransport(app=make_upstream([])), base_url="http://up.test")
    g = run_(free["api_key"], "gateway_create", {"name": "a", "upstream_url": "http://up.test/mcp"}).structured_content
    run_(free["api_key"], "gateway_create", {"name": "b", "upstream_url": "http://up.test/mcp"})
    assert "allows 2 gateways" in run_(free["api_key"], "gateway_create", {"name": "c", "upstream_url": "http://up.test/mcp"}).structured_content["error"]
    with TestClient(app, base_url="http://localhost") as http:
        codes = [http.post(f"/gw/{g['gw_id']}/mcp", json=CALL("echo")).status_code for _ in range(3)]
        assert codes == [200, 200, 429]
        r = http.post(f"/gw/{g['gw_id']}/mcp", json=CALL("echo"))
        assert r.json()["error"]["code"] == -32004 and r.json()["error"]["data"]["free_monthly_limit"] == 2
        # protocol messages are never metered
        assert http.post(f"/gw/{g['gw_id']}/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).status_code == 200


# ---------------- rooms ----------------

def test_rooms_paid_live_conversation_sealed(ledger, monkeypatch):
    seller, buyer, outsider = ledger.create_org("Seller Co"), ledger.create_org("Buyer Co"), ledger.create_org("Outsider")
    human, human_sign = _eth_wallet()
    run_ = runner(ledger, monkeypatch)
    s, app = mk(ledger)
    live = s.privi_live

    # buyer's human authorizes up to 1 USDC for this seller
    d = run_(buyer["api_key"], "mandate_create", {"stream_id": "buyer-agent", "principal_wallet": human, "max_total_usdc": "1",
                                                  "payees": ["seller.example.com"], "purpose": "Pay per message"}).structured_content
    mid = d["mandate_id"]
    assert run_(seller["api_key"], "room_open", {"title": "x", "price_per_message_usdc": "0.1"}).is_error     # payee required
    room = run_(seller["api_key"], "room_open", {"title": "Negotiate lot 4471", "counterparty_org_id": buyer["org_id"],
                                                 "price_per_message_usdc": "0.25", "payee": "seller.example.com"}).structured_content
    rid = room["room_id"]
    assert "join_code" not in room and room["ws_url"].endswith(f"/rooms/{rid}/ws") and room["status"] == "open"

    with TestClient(app, base_url="http://localhost") as http:
        assert http.post(f"/mandates/{mid}/activate", json={"signature": human_sign(d["message"])}).status_code == 200
        assert http.get(f"/rooms/{rid}").json()["title"] == "Negotiate lot 4471"
        with http.websocket_connect(f"/rooms/{rid}/ws") as out:
            out.send_json({"type": "auth", "key": outsider["api_key"]})
            assert recv(out, "auth")["ok"] is False
            out.send_json({"type": "msg", "body": "hi"})
            assert "authenticate first" in recv(out, "error")["error"]

        with http.websocket_connect(f"/rooms/{rid}/ws") as a, http.websocket_connect(f"/rooms/{rid}/ws") as b:
            a.send_json({"type": "auth", "key": seller["api_key"]})
            assert recv(a, "joined")["role"] == "owner"
            b.send_json({"type": "auth", "key": buyer["api_key"], "mandate_id": mid})
            assert recv(b, "joined")["role"] == "guest"

            b.send_json({"type": "msg", "body": "Can you do 500 units by Friday?", "ref": "r1"})
            m_b, m_a = recv(b, "msg"), recv(a, "msg")
            assert m_a["seq"] == 1 and m_a["body"].startswith("Can you") and m_a["charged_usdc"] == "0.25"
            assert m_b["ref"] == "r1" and "ref" not in m_a
            a.send_json({"type": "msg", "body": "Yes, at 12 USDC/unit.", "kind": "offer"})
            assert recv(a, "msg")["charged_usdc"] is None and recv(b, "msg")["kind"] == "offer"

            # the buyer's mandate is the meter: 0.25 so far
            assert run_(buyer["api_key"], "mandate_get", {"mandate_id": mid}).structured_content["spent_usdc"] == "0.25"
            # a kill switch on the buyer stops their messages (and charges)
            live.kill(buyer["org_id"], "*", "stop")
            b.send_json({"type": "msg", "body": "more"})
            assert "kill switch" in recv(b, "error")["error"]
            live.resume(buyer["org_id"], "*")
            # budget enforcement: 0.75 left -> three more messages fit, the fourth is refused by the mandate
            for i in range(3):
                b.send_json({"type": "msg", "body": f"q{i}"})
                recv(b, "msg"); recv(a, "msg")
            b.send_json({"type": "msg", "body": "one too many"})
            assert "remaining budget" in recv(b, "error")["error"]
            b.send_json({"type": "history", "since": 3})
            assert [m["seq"] for m in recv(b, "history")["messages"]] == [4, 5]

            a.send_json({"type": "close"})
            assert recv(a, "close")["status"] == "closed"
            closed = recv(b, "closed")
            assert closed["message_count"] == 5 and len(closed["seal_hash"]) == 64
            b.send_json({"type": "msg", "body": "after close"})
            assert "closed" in recv(b, "error")["error"]

    # sealed transcript
    tr = run_(buyer["api_key"], "room_transcript", {"room_id": rid}).structured_content
    assert tr["verification"]["valid"] and tr["verification"]["message_count"] == 5
    assert run_(outsider["api_key"], "room_transcript", {"room_id": rid}).is_error
    v = run_(None, "room_verify", {"room_id": rid, "messages": tr["messages"]}).structured_content
    assert v["sealed"] and v["seal_hash_ok"] and v["signature_valid"] and v["transcript"]["matches_seal"]
    assert v["seal"]["message_count"] == 5 and v["seal"]["head_hash"] == tr["verification"]["head_hash"]
    forged = json.loads(json.dumps(tr["messages"]))
    forged[0]["body"] = "Can you do 5 units by Friday?"
    assert not run_(None, "room_verify", {"room_id": rid, "messages": forged}).structured_content["transcript"]["matches_seal"]
    assert not run_(None, "room_verify", {"room_id": rid, "messages": tr["messages"][:-1]}).structured_content["transcript"]["matches_seal"]
    assert run_(None, "room_verify", {"room_id": rid}).structured_content["sealed"]
    for org in (seller, buyer):                                        # both sides hold a sealed record
        log = ledger.entries(org["org_id"], f"room-{rid}")
        assert any("sealed" in e["summary"] for e in log) and ledger.check_chain(log).valid
    assert any(e["type"] == "room.closed" for e in live.bus.recent(f"org:{seller['org_id']}", 20))


def test_rooms_join_code_and_limits(ledger, monkeypatch):
    a, b, c = ledger.create_org("A"), ledger.create_org("B"), ledger.create_org("C")
    run_ = runner(ledger, monkeypatch)
    s, app = mk(ledger)
    room = run_(a["api_key"], "room_open", {"title": "open call", "max_messages": 2}).structured_content
    rid, code = room["room_id"], room["join_code"]
    assert run_(a["api_key"], "room_open", {"title": "t", "counterparty_org_id": "org_nope"}).is_error
    with TestClient(app, base_url="http://localhost") as http:
        with http.websocket_connect(f"/rooms/{rid}/ws") as wa, http.websocket_connect(f"/rooms/{rid}/ws") as wb, \
                http.websocket_connect(f"/rooms/{rid}/ws") as wc:
            wa.send_json({"type": "auth", "key": a["api_key"]})
            recv(wa, "joined")
            wb.send_json({"type": "auth", "key": b["api_key"], "join_code": "wrong"})
            assert recv(wb, "auth")["ok"] is False
            wb.send_json({"type": "auth", "key": b["api_key"], "join_code": code})
            assert recv(wb, "joined")["role"] == "guest"
            wc.send_json({"type": "auth", "key": c["api_key"], "join_code": code})
            assert "two parties" in recv(wc, "auth")["error"]
            wb.send_json({"type": "msg", "body": "one"})
            recv(wb, "msg")
            wa.send_json({"type": "msg", "body": "two"})
            recv(wa, "msg")
            wa.send_json({"type": "msg", "body": "three"})
            assert "message limit" in recv(wa, "error")["error"]
            wa.send_json({"type": "msg", "body": ""})
            assert "body must be" in recv(wa, "error")["error"]
    assert run_(a["api_key"], "room_close", {"room_id": rid}).structured_content["status"] == "closed"
    assert run_(b["api_key"], "room_list", {}).structured_content["rooms"][0]["room_id"] == rid
    assert run_(None, "room_info", {"room_id": rid}).structured_content["seal"]["body"]["message_count"] == 2
    assert run_(None, "live_info", {}).structured_content["streams"]["websocket"].endswith("/live/ws")
