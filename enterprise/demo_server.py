"""Read-only, no-secret Privi receipt demonstration HTTP service."""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from agent_execution_evidence import canonical, receipt_hash

SAMPLE = {
    "tenant": "demo-only", "agent_id": "privi-example-agent", "request_id": "demo-001",
    "policy_version": "example-v1", "software_digest": "sha256:example-not-a-real-binary",
    "action": "read-public-demo", "authorization": "approved",
    "execution": "reported_success", "timestamp": "2026-11-07T00:00:00+00:00",
    "previous_hash": "0" * 64
}

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            status, data = 200, {"status": "ok", "mode": "demo-only"}
        elif self.path == "/demo":
            status, data = 200, {
                "mode": "demo-only", "not_proof_of_execution": True,
                "receipt": SAMPLE, "canonical_sha256": receipt_hash(SAMPLE),
                "note": "Example hash only. No real authorization, external attestation or signing."
            }
        else:
            status, data = 404, {"error": "not_found"}
        body = canonical(data)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
