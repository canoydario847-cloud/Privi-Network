"""Privi Car event receipt prototype. No vehicle controls or real payments."""
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

SECRET = os.environ.get("PRIVI_CAR_RECEIPT_KEY", "")
MAX_BYTES = 8192

def receipt(event):
    if not SECRET or len(SECRET) < 32:
        raise RuntimeError("Set PRIVI_CAR_RECEIPT_KEY to at least 32 characters")
    if not isinstance(event, dict) or event.get("type") not in {"maintenance", "charging", "fuel_reservation", "compute_session"}:
        raise ValueError("Unsupported event type")
    if not isinstance(event.get("vehicle_id"), str) or not 1 <= len(event["vehicle_id"]) <= 128:
        raise ValueError("Invalid pseudonymous vehicle_id")
    if event.get("type") == "fuel_reservation" and event.get("payment_status") not in (None, "simulation"):
        raise ValueError("Real payments are not supported")
    payload = {"schema": "privi.car.event.v1", "vehicle_id": event["vehicle_id"],
               "type": event["type"], "data": event.get("data", {}),
               "timestamp": datetime.now(timezone.utc).isoformat(),
               "network": "offchain-prototype"}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return {"event": payload, "sha256": hashlib.sha256(canonical).hexdigest(),
            "signature": hmac.new(SECRET.encode(), canonical, hashlib.sha256).hexdigest(),
            "signature_type": "HMAC-SHA256 (server-only verification)"}

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/health":
            self.send_error(404); return
        self.respond(200, {"status": "ok", "mode": "prototype", "onchain": False})
    def do_POST(self):
        if self.path != "/v1/events":
            self.send_error(404); return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_BYTES: raise ValueError("Invalid body length")
            event = json.loads(self.rfile.read(length))
            self.respond(201, receipt(event))
        except (ValueError, json.JSONDecodeError) as exc:
            self.respond(400, {"error": str(exc)})
        except RuntimeError:
            self.respond(503, {"error": "Receipt signing not configured"})
    def respond(self, status, body):
        encoded = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

if __name__ == "__main__":
    HTTPServer(("127.0.0.1", int(os.environ.get("PORT", "8080"))), Handler).serve_forever()
