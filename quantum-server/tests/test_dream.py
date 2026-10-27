# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Quantum - https://priviflow.us - dariocanoy@priviflow.us
"""The Privi quantum realm: Privilege (directory), Dream Weaver (race), Dream Scape (workspace + WebSocket)."""
import asyncio
import json

import anyio
import httpx2
from mcp import Client
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from privi_quantum.attest import Attestor
from privi_quantum.server import Settings, build_server, http_app

SMALL = {"jobs": [{"name": n, "minutes": m} for n, m in zip("ABCDEF", [42, 17, 33, 8, 25, 61])]}
ADMIN = "adm_test_key"


def make_server(tmp_path, name="d.db"):
    db = str(tmp_path / name)
    return build_server(Settings(db_path=db, admin_key=ADMIN, dream_allow_private=True, rate_per_min=1000,
                                 inspector_mode="off"),   # the Inspector itself is tested in test_inspector.py
                        Attestor(db))


def fake_node(delay: float = 0.0, fail: bool = False):
    """A remote Privi Quantum node speaking MCP: answers quantum_optimize after `delay` seconds."""
    async def mcp_(request: Request):
        body = json.loads(await request.body())
        rid, method = body.get("id"), body.get("method")
        if method == "initialize":
            return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": {"protocolVersion": "2025-06-18",
                                 "capabilities": {}, "serverInfo": {"name": "privi-quantum", "version": "0.3.0"}}})
        if rid is None:
            return JSONResponse({}, status_code=202)
        if method == "tools/call":
            await asyncio.sleep(delay)
            if fail:
                return JSONResponse({"jsonrpc": "2.0", "id": rid, "error": {"code": -32000, "message": "node overloaded"}})
            sc = {"decision": {"line_1": ["A", "D", "E"], "line_2": ["B", "C", "F"]},
                  "quality": {"found_optimum": True, "approximation_ratio": 1.0, "probability_of_optimum": 0.4},
                  "quantum_run": {"qubits": 6, "runtime_ms": 5, "angles": {"gamma": [1.0], "beta": [0.5]}},
                  "attestation": {"id": "qa_node1", "attestation_url": "https://node.test/attestations/qa_node1"}}
            return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": json.dumps(sc)}], "structuredContent": sc}})
        return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": {}})
    return Starlette(routes=[Route("/mcp", mcp_, methods=["POST"])])


def call(server, tool, args):
    async def go():
        async with Client(server) as c:
            return await c.call_tool(tool, args)
    return anyio.run(go)


def test_privilege_directory_and_first_mode(tmp_path):
    srv = make_server(tmp_path)
    d = call(srv, "privilege_directory", {}).structured_content
    assert {r["realm_id"] for r in d["realms"]} == {"dreamscape-exact", "dreamscape-swift"}
    assert all(r["status"] == "untested" for r in d["realms"])

    r = call(srv, "dreamweaver_run", {"problem": "balance_lines", "data": SMALL, "mode": "first", "fanout": 2}).structured_content
    assert r["ok"] and r["qubits"] == 6 and r["winner"]["realm_id"] in ("dreamscape-exact", "dreamscape-swift")
    assert set(r["decision"]) and r["attestation"]["id"].startswith("qa_") and "attestation_url" in r["attestation"]
    assert sum(1 for a in r["attempts"] if a["status"] == "won") == 1

    v = call(srv, "quantum_verify", {"attestation_id": r["attestation"]["id"]}).structured_content
    assert v["valid"] is True

    d2 = call(srv, "privilege_directory", {}).structured_content
    winner = next(x for x in d2["realms"] if x["realm_id"] == r["winner"]["realm_id"])
    assert winner["status"] == "ready" and winner["wins"] == 1 and winner["latency_ms"] is not None

    bad = call(srv, "dreamweaver_run", {"problem": "balance_lines", "data": {"jobs": []}})
    assert bad.is_error
    assert call(srv, "dreamweaver_run", {"problem": "balance_lines", "data": SMALL, "realms": ["nope"]}).is_error


def test_remote_node_best_mode_failover_and_admin(tmp_path):
    from starlette.testclient import TestClient
    srv = make_server(tmp_path)
    privilege, weaver, _ = srv._dream
    with TestClient(http_app(srv)) as http:
        assert http.post("/privilege/realms", json={"name": "Dream Scape EU", "url": "http://node.test/mcp"}).status_code == 401
        h = {"Authorization": f"Bearer {ADMIN}"}
        n = http.post("/privilege/realms", headers=h, json={"name": "Dream Scape EU", "url": "http://node.test/mcp",
                                                            "location": "eu-west"})
        assert n.status_code == 201 and n.json()["realm_id"] == "node-dream-scape-eu"
        http.post("/privilege/realms", headers=h, json={"name": "Broken Node", "url": "http://broken.test/mcp"})
        assert http.delete("/privilege/realms/dreamscape-exact", headers=h).status_code == 400
        assert len(http.get("/privilege").json()["realms"]) == 4
        assert "Dream Scape" in http.get("/dreamscape").text

    routes = {"node.test": fake_node(0.0), "broken.test": fake_node(fail=True)}

    class Router(httpx2.AsyncBaseTransport):
        async def handle_async_request(self, request):
            return await httpx2.ASGITransport(app=routes[request.url.host]).handle_async_request(request)

    weaver._client = httpx2.AsyncClient(transport=Router())
    r = call(srv, "dreamweaver_run", {"problem": "balance_lines", "data": SMALL, "mode": "best", "fanout": 4}).structured_content
    assert r["ok"] and r["mode"] == "best"
    st = {a["realm_id"]: a["status"] for a in r["attempts"]}
    assert st["node-broken-node"] == "failed" and st["node-dream-scape-eu"] in ("won", "answered")
    assert r["quality"]["found_optimum"] is True          # best mode keeps an optimal answer
    if r["winner"]["realm_id"] == "node-dream-scape-eu":
        assert r["node_attestation"]["id"] == "qa_node1"

    # only the node, which answers: first mode
    r2 = call(srv, "dreamweaver_run", {"problem": "balance_lines", "data": SMALL, "realms": ["node-dream-scape-eu"]}).structured_content
    assert r2["ok"] and r2["winner"]["realm_id"] == "node-dream-scape-eu"
    # hedging: the top-ranked realm fails, so the next one starts at once instead of after the 8 s hedge delay
    routes["node.test"], routes["broken.test"] = fake_node(fail=True), fake_node(0.0)
    r3 = call(srv, "dreamweaver_run", {"problem": "balance_lines", "data": SMALL, "hedge_ms": 8000, "fanout": 2,
                                       "realms": ["node-broken-node", "node-dream-scape-eu"]}).structured_content
    assert r3["attempts"][-1]["realm_id"] == "node-dream-scape-eu" or any(
        a["realm_id"] == "node-dream-scape-eu" and a["status"] == "failed" for a in r3["attempts"])
    assert r3["ok"] and r3["winner"]["realm_id"] == "node-broken-node" and r3["total_ms"] < 8000
    eu = next(x for x in privilege.directory()["realms"] if x["realm_id"] == "node-dream-scape-eu")
    assert eu["failures"] == 1 and eu["last_error"] == "node overloaded"


def test_dreamscape_workspace_and_websocket(tmp_path):
    from starlette.testclient import TestClient
    srv = make_server(tmp_path)
    sc = call(srv, "dreamscape_open", {"name": "Plant 2 scheduling"}).structured_content
    sid, key = sc["scape_id"], sc["scape_key"]
    assert sc["websocket"].endswith("/dreamscape/ws")
    assert call(srv, "dreamscape_submit", {"scape_id": sid, "scape_key": "wrong", "problem": "balance_lines",
                                           "data": SMALL}).is_error
    job = call(srv, "dreamscape_submit", {"scape_id": sid, "scape_key": key, "problem": "balance_lines", "data": SMALL,
                                          "fanout": 2}).structured_content
    assert job["status"] == "done" and job["job_id"].startswith("job_")
    lst = call(srv, "dreamscape_jobs", {"scape_id": sid, "scape_key": key}).structured_content
    assert lst["jobs"][0]["job_id"] == job["job_id"] and lst["jobs"][0]["winner"]
    one = call(srv, "dreamscape_jobs", {"scape_id": sid, "scape_key": key, "job_id": job["job_id"]}).structured_content
    assert one["result"]["attestation"]["id"] == job["attestation"]["id"]
    assert call(srv, "dreamscape_jobs", {"scape_id": sid, "scape_key": "x"}).is_error

    with TestClient(http_app(srv)) as http:
        with http.websocket_connect("/dreamscape/ws") as ws:
            assert ws.receive_json()["type"] == "hello"
            ws.send_json({"type": "weave", "ref": "x", "problem": "balance_lines", "data": SMALL})
            assert ws.receive_json()["error"] == "authenticate first"
            ws.send_json({"type": "auth", "scape_id": sid, "key": "wrong"})
            assert ws.receive_json()["ok"] is False
            ws.send_json({"type": "auth", "scape_id": sid, "key": key})
            assert ws.receive_json()["ok"] is True
            for ref in ("a", "b", "c"):                     # three jobs in flight on one socket
                ws.send_json({"type": "weave", "ref": ref, "problem": "balance_lines", "data": SMALL, "fanout": 2})
            done, seen = {}, set()
            while len(done) < 3:
                m = ws.receive_json()
                seen.add(m["type"])
                if m["type"] == "weave.done":
                    done[m["ref"]] = m
            assert set(done) == {"a", "b", "c"} and all(m["ok"] for m in done.values())
            assert {"job.accepted", "realm.started", "realm.result"} <= seen
            ws.send_json({"type": "directory"})
            assert ws.receive_json()["directory"] == "Privilege"
    assert len(call(srv, "dreamscape_jobs", {"scape_id": sid, "scape_key": key}).structured_content["jobs"]) == 4


def test_benchmark_is_rate_limited(tmp_path):
    srv = make_server(tmp_path)

    async def go():
        async with Client(srv) as c:
            first = await c.call_tool("privilege_benchmark", {})
            second = await c.call_tool("privilege_benchmark", {})
            return first, second
    first, second = anyio.run(go)
    assert not first.is_error and first.structured_content["benchmark"]["ok"]
    assert all(r["runs"] >= 1 for r in first.structured_content["directory"]["realms"])
    assert second.is_error and "2 minutes" in second.structured_content["error"]
