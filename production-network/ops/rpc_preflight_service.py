"""Read-only status service; never authorizes financial mainnet."""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from check_rpc_identity import sample

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        status = 200
        result = {"mainnet_authorized": False, "mode": "read-only-preflight"}
        if self.path == "/health":
            result["service"] = "ok"
        elif self.path == "/":
            keys = ("COMET_RPC", "EVM_RPC", "COSMOS_CHAIN_ID", "EVM_CHAIN_ID")
            if not all(os.environ.get(k) for k in keys):
                result["rpc_preflight"] = "UNCONFIGURED"
            else:
                try:
                    args = SimpleNamespace(comet=os.environ[keys[0]], evm=os.environ[keys[1]],
                        cosmos_id=os.environ[keys[2]], evm_id=int(os.environ[keys[3]]))
                    result["heights"] = sample(args)
                    result["rpc_snapshot"] = "PASS"
                except Exception:
                    result["rpc_snapshot"] = "FAIL"
                    status = 503
        else:
            status = 404
        body = json.dumps(result).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "10000"))), Handler).serve_forever()
