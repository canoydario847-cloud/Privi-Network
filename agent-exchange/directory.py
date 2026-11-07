"""Zero-cost, standard-library prototype of Privi Agent Exchange directory.

Run: python agent-exchange/directory.py
Endpoints: GET /health, GET /v1/agents, GET /v1/agents/{id}
Registration intentionally disabled until authentication and durable storage exist.
No WebSocket support yet: do not advertise this as a live socket gateway.
"""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

AGENTS = [
    {"id": "privi-call", "name": "Privi Call", "capabilities": ["mcp", "agent-calls"], "endpoint": "https://privi-call.onrender.com/mcp", "verified": False},
    {"id": "privi-quantum", "name": "Privi Quantum", "capabilities": ["mcp", "compute"], "endpoint": "https://privi-quantum.onrender.com/mcp", "verified": False},
]
class Handler(BaseHTTPRequestHandler):
    def reply(self, code, data):
        body = json.dumps(data, separators=(",", ":")).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/health":
            return self.reply(200, {"status": "ok", "mode": "directory-prototype", "registered": len(AGENTS)})
        if u.path == "/v1/agents":
            capability = parse_qs(u.query).get("capability", [""])[0]
            matches = [a for a in AGENTS if not capability or capability in a["capabilities"]]
            return self.reply(200, {"agents": matches, "count": len(matches), "note": "Listed endpoints have not been independently verified"})
        if u.path.startswith("/v1/agents/"):
            key = u.path.removeprefix("/v1/agents/")
            for agent in AGENTS:
                if agent["id"] == key:
                    return self.reply(200, agent)
        return self.reply(404, {"error": "not_found"})
    def do_POST(self):
        return self.reply(403, {"error": "registration_disabled_until_authentication"})
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
