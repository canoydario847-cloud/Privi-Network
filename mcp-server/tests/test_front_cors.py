# Copyright (c) 2026 Privi World Co. All rights reserved.
"""Browsers can call /mcp: CORS preflight is answered and responses carry CORS headers."""
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from privi_verify.front import QuickGet


async def mcp(request):
    return JSONResponse({"jsonrpc": "2.0", "id": 1, "result": {}}, headers={"mcp-session-id": "s1"})


def client():
    inner = Starlette(routes=[Route("/mcp", mcp, methods=["POST"])])
    return TestClient(QuickGet(inner, "Test", "test", "https://example.test"))


def test_preflight_answered():
    r = client().options("/mcp", headers={"Origin": "https://demo.example", "Access-Control-Request-Method": "POST"})
    assert r.status_code == 204
    assert r.headers["access-control-allow-origin"] == "*"
    assert "POST" in r.headers["access-control-allow-methods"]
    assert "content-type" in r.headers["access-control-allow-headers"].lower()


def test_post_carries_cors_and_passes_through():
    r = client().post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert r.status_code == 200 and r.json()["id"] == 1
    assert r.headers["access-control-allow-origin"] == "*"
    assert "Mcp-Session-Id" in r.headers["access-control-expose-headers"]


def test_get_still_405_with_cors():
    r = client().get("/mcp")
    assert r.status_code == 405 and r.headers["access-control-allow-origin"] == "*"
