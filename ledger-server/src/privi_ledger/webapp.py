"""The installable web app for this Privi service (generated copy; the master is apps/webapp.py).

Routes:
    GET /app/                        the app (one page; it talks to this server's own /mcp endpoint)
    GET /app/manifest.webmanifest    so phones and computers can install it
    GET /app/sw.js                   keeps the app shell available when the network is slow
    GET /app/icon-192.png, icon-512.png
    GET /.well-known/assetlinks.json lets the Google Play app (a Trusted Web Activity) open without a browser bar,
                                     once the owner sets the app signing fingerprint in the env var named in app.json

The page adds no new way in: every action is a normal MCP tool call, so the same keys, prices and paywall apply.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

HERE = Path(__file__).parent / "webapp"
SW = """const CACHE = 'privi-app-%s';
self.addEventListener('install', e => { self.skipWaiting(); e.waitUntil(caches.open(CACHE).then(c => c.addAll(['/app/', '/app/icon-192.png']))); });
self.addEventListener('activate', e => e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim())));
self.addEventListener('fetch', e => {
  const u = new URL(e.request.url);
  if (e.request.method !== 'GET' || !u.pathname.startsWith('/app')) return;
  e.respondWith(fetch(e.request).then(r => { const copy = r.clone(); caches.open(CACHE).then(c => c.put(e.request, copy)); return r; })
    .catch(() => caches.match(e.request).then(r => r || caches.match('/app/'))));
});
"""


def load_config() -> dict:
    return json.loads((HERE / "app.json").read_text(encoding="utf-8"))


def asset_statements(cfg: dict | None = None) -> list[dict]:
    """Digital Asset Links entries for this app's Android package (empty until the fingerprint env var is set)."""
    cfg = cfg or load_config()
    fps = [f.strip().upper() for f in os.getenv(cfg["android"]["fingerprint_env"], "").split(",") if f.strip()]
    return [{"relation": ["delegate_permission/common.handle_all_urls"],
             "target": {"namespace": "android_app", "package_name": cfg["android"]["package"],
                        "sha256_cert_fingerprints": fps}}] if fps else []


def register(mcp, version: str = "1", assetlinks: bool = True) -> dict:
    cfg = load_config()
    page_cfg = {k: cfg[k] for k in ("slug", "name", "tagline", "intro", "site", "features", "key", "file_lists", "plan_note")
                if k in cfg}
    page_cfg["mcp_path"] = "/mcp"
    html = (HERE / "app.html").read_text(encoding="utf-8").replace(
        "/*PRIVI_APP_CONFIG*/null", json.dumps(page_cfg).replace("</", "<\\/"))
    icons = {n: (HERE / n).read_bytes() for n in ("icon-192.png", "icon-512.png")}
    route = mcp.custom_route

    @route("/app", methods=["GET"], include_in_schema=False)
    async def app_redirect(request: Request) -> Response:
        q = request.url.query
        return RedirectResponse("/app/" + (f"?{q}" if q else ""), status_code=308)

    @route("/app/", methods=["GET"], include_in_schema=False)
    async def app_page(_: Request) -> Response:
        return HTMLResponse(html, headers={"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff",
                                           "Referrer-Policy": "no-referrer"})

    @route("/app/manifest.webmanifest", methods=["GET"], include_in_schema=False)
    async def app_manifest(_: Request) -> Response:
        return JSONResponse({
            "name": cfg["name"], "short_name": cfg["short_name"], "description": cfg["tagline"],
            "start_url": "/app/?source=pwa", "scope": "/app/", "id": "/app/", "display": "standalone",
            "background_color": "#0E1B33", "theme_color": "#0E1B33",
            "icons": [{"src": "/app/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
                      {"src": "/app/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
                      {"src": "/app/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}]},
            media_type="application/manifest+json", headers={"Cache-Control": "max-age=3600"})

    @route("/app/sw.js", methods=["GET"], include_in_schema=False)
    async def app_sw(_: Request) -> Response:
        return Response(SW % version, media_type="text/javascript", headers={"Cache-Control": "no-cache"})

    def _icon(name: str):
        async def icon(_: Request) -> Response:
            return Response(icons[name], media_type="image/png", headers={"Cache-Control": "max-age=86400"})
        return icon

    for n in icons:
        route(f"/app/{n}", methods=["GET"], include_in_schema=False)(_icon(n))

    if assetlinks:
        @route("/.well-known/assetlinks.json", methods=["GET"], include_in_schema=False)
        async def app_assetlinks(_: Request) -> Response:
            return JSONResponse(asset_statements(cfg), headers={"Cache-Control": "max-age=300"})

    return cfg
