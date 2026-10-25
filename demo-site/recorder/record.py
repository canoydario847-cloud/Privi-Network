"""Record the walkthrough videos: python recorder/record.py (needs playwright + chromium)."""
import json, pathlib, shutil, subprocess, sys, threading, time, http.server, functools, socketserver
from playwright.sync_api import sync_playwright
HERE = pathlib.Path(__file__).parent; OUT = HERE.parent / "videos"; OUT.mkdir(exist_ok=True)
flows = list(json.load(open(HERE / "flows.json"))["flows"]) if len(sys.argv) < 2 else sys.argv[1:]
handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(HERE))
srv = socketserver.TCPServer(("127.0.0.1", 0), handler); port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
with sync_playwright() as p:
    b = p.chromium.launch()
    for f in flows:
        tmp = HERE / "_tmp"; shutil.rmtree(tmp, ignore_errors=True)
        ctx = b.new_context(viewport={"width": 1280, "height": 720}, record_video_dir=str(tmp), record_video_size={"width": 1280, "height": 720})
        pg = ctx.new_page(); pg.goto(f"http://127.0.0.1:{port}/player.html?flow={f}")
        pg.wait_for_function("window.__done === true", timeout=180000)
        pg.screenshot(path=str(OUT / f"{f}.jpg"), type="jpeg", quality=80) if False else None
        ctx.close(); vid = next(tmp.glob("*.webm")); shutil.move(str(vid), OUT / f"{f}.webm"); shutil.rmtree(tmp)
        print("recorded", f, (OUT / f"{f}.webm").stat().st_size // 1024, "KB", flush=True)
    b.close()
srv.shutdown()
