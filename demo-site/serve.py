# Copyright (c) 2026 Privi World Co. All rights reserved.
"""Static server for the Privi demo site (Railway sets $PORT)."""
import http.server, mimetypes, os, socketserver
mimetypes.add_type("video/webm", ".webm")
ROOT = os.path.dirname(os.path.abspath(__file__))
HIDDEN = ("/recorder", "/serve.py", "/Dockerfile", "/railway.json", "/README.md")

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=ROOT, **k)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/health":
            body = b'{"ok":true,"service":"privi-demo"}'
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
        if path.startswith(HIDDEN):
            self.send_error(404); return
        rng = self.headers.get("Range")
        if rng and path.startswith("/videos/"):
            return self._range(path, rng)
        super().do_GET()

    def _range(self, path, rng):
        fp = self.translate_path(path)
        if not os.path.isfile(fp):
            self.send_error(404); return
        size = os.path.getsize(fp)
        try:
            a, b = rng.replace("bytes=", "").split(",")[0].split("-")
            start = int(a) if a else max(0, size - int(b))
            end = min(int(b), size - 1) if a and b else size - 1
            if start > end or start >= size:
                raise ValueError
        except ValueError:
            self.send_response(416); self.send_header("Content-Range", f"bytes */{size}"); self.end_headers(); return
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(fp));
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}"); self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        with open(fp, "rb") as f:
            f.seek(start); left = end - start + 1
            while left > 0:
                chunk = f.read(min(65536, left))
                if not chunk:
                    break
                self.wfile.write(chunk); left -= len(chunk)

    def end_headers(self):
        p = self.path.split("?", 1)[0]
        self.send_header("Cache-Control", "public, max-age=86400" if p.startswith("/videos/") else "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        if p.startswith("/videos/"):
            self.send_header("Accept-Ranges", "bytes")
        super().end_headers()

class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    print(f"privi-demo listening on :{port}", flush=True)
    Server(("0.0.0.0", port), Handler).serve_forever()
