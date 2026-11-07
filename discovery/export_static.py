"""Export every Privi Discovery Hub route as static files (free, always-on fallback).

The live hub (privi-discovery) runs on Render's free plan and sleeps when idle, so agents and
crawlers that arrive during a cold start get HTTP 503. This writes the same documents into
sites/hub/discovery-mirror/ (served by the always-on privi-hub static site), and the Privi Edge
Worker serves that copy whenever the live hub answers 5xx or cannot be reached.

Run from the repo root after changing discovery/manifest.json:
    PUBLIC_BASE_URL=https://privi-discovery.onrender.com python discovery/export_static.py
"""
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("PUBLIC_BASE_URL", "https://privi-discovery.onrender.com")
os.environ["INDEXNOW_DISABLE"] = "1"
sys.path.insert(0, str(Path(__file__).parent))
import app  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "sites" / "hub" / "discovery-mirror"


def mirror_path(route: str) -> str:
    """'/.well-known/agent.json' -> 'well-known/agent.json'; '/' -> 'index.html'."""
    if route == "/":
        return "index.html"
    return route.lstrip("/").replace(".well-known/", "well-known/", 1)


def main() -> None:
    written = []
    for route, fn in sorted(app.ROUTES.items()):
        if route == "/health" or route == f"/{app.INDEXNOW_KEY}.txt":
            continue  # health must reflect the live hub; the IndexNow key stays origin-only
        out = fn()
        if isinstance(out, app.Response):
            body = out.body
        elif isinstance(out, (dict, list)):
            body = json.dumps(out, indent=2)
        else:
            body = out
        dest = OUT / mirror_path(route)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(body if isinstance(body, str) else body.decode())
        written.append(route)
    (OUT / "routes.json").write_text(json.dumps({r: mirror_path(r) for r in written}, indent=2))
    print(f"exported {len(written)} routes to {OUT}")


if __name__ == "__main__":
    main()
