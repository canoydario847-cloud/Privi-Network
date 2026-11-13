"""The installable web app: page, manifest, icons, Play asset links, and that every screen points at a real tool.
(Generated copy; the master is apps/test_webapp_template.py.)"""
import json

import anyio
from mcp import Client
from starlette.testclient import TestClient

from privi_call import webapp
from privi_call.webapp import load_config


def _check(srv, monkeypatch):
    cfg = load_config()
    monkeypatch.delenv(cfg["android"]["fingerprint_env"], raising=False)
    http = TestClient(srv.streamable_http_app())
    r = http.get("/app", follow_redirects=False)
    assert r.status_code == 308 and r.headers["location"] == "/app/"
    page = http.get("/app/")
    assert page.status_code == 200 and "/*PRIVI_APP_CONFIG*/null" not in page.text and cfg["name"] in page.text
    m = http.get("/app/manifest.webmanifest").json()
    assert m["start_url"].startswith("/app/") and m["scope"] == "/app/" and m["display"] == "standalone"
    for icon in m["icons"]:
        png = http.get(icon["src"])
        assert png.status_code == 200 and png.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert "addEventListener('fetch'" in http.get("/app/sw.js").text
    links = http.get("/.well-known/assetlinks.json").json()
    assert all(x["target"]["package_name"] != cfg["android"]["package"] for x in links)      # nothing until the owner sets it
    monkeypatch.setenv(cfg["android"]["fingerprint_env"], "aa:bb, cc:dd")
    mine = [x for x in http.get("/.well-known/assetlinks.json").json() if x["target"]["package_name"] == cfg["android"]["package"]]
    assert mine and mine[0]["target"]["sha256_cert_fingerprints"] == ["AA:BB", "CC:DD"]

    async def tools():
        async with Client(srv) as c:
            return {t.name: t for t in (await c.list_tools()).tools}
    have = anyio.run(tools)
    wanted = [t for f in cfg["features"] for t in f["tools"]]
    assert not [t for t in wanted if t not in have], "app.json names a tool this server does not have"
    assert len(wanted) == len(set(wanted))
    for ref in cfg.get("file_lists", {}):
        tool, arg = ref.split(".")
        assert arg in have[tool].input_schema["properties"]
    if cfg.get("key", {}).get("mode") == "arg":
        assert any(cfg["key"]["arg"] in have[t].input_schema["properties"] for t in wanted)
    assert json.dumps(cfg)          # plain JSON only


def test_web_app(tmp_path, monkeypatch):
    from test_call import make
    _check(make(tmp_path)[2], monkeypatch)
