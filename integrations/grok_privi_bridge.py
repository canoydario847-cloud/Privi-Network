"""Minimal, read-only Privi MCP bridge for xAI/Grok function calling.

Uses Python stdlib only. No API keys or payments. Run with:
    python integrations/grok_privi_bridge.py
Requires network access to PRIVI_MCP_URL. This is a developer sample, not a hosted service.
"""
import json
import os
import urllib.request
import uuid

MCP_URL = os.environ.get("PRIVI_MCP_URL", "https://privi-verify.onrender.com/mcp")
MAX_RESPONSE = 65536

TOOLS = [
    {"type": "function", "function": {
        "name": "privi_pricing",
        "description": "Read Privi verification tool prices and payment network (free).",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False}
    }},
    {"type": "function", "function": {
        "name": "privi_lookup_fingerprint",
        "description": "Look up a SHA-256 fingerprint in Privi (free).",
        "parameters": {"type": "object", "properties": {
            "fingerprint": {"type": "string", "description": "64 hex characters"}
        }, "required": ["fingerprint"], "additionalProperties": False}
    }},
]

def _rpc(method, params=None):
    body = json.dumps({"jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": method,
                       **({"params": params} if params is not None else {})}).encode()
    req = urllib.request.Request(MCP_URL, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2025-03-26",
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise ValueError("MCP response too large")
        media = resp.headers.get("Content-Type", "")
    if "text/event-stream" in media:
        for line in raw.decode().splitlines():
            if line.startswith("data: "):
                value = json.loads(line[6:])
                if value.get("id") is not None:
                    return value
        raise ValueError("No JSON-RPC result in MCP event stream")
    return json.loads(raw)

def call_privi(name, arguments):
    """Execute ONLY the two allowlisted, free read-only tools."""
    if name not in {"privi_pricing", "privi_lookup_fingerprint"}:
        raise ValueError("Tool not allowed: " + str(name))
    if not isinstance(arguments, dict):
        raise ValueError("Arguments must be an object")
    if name == "privi_pricing":
        if arguments:
            raise ValueError("Pricing takes no arguments")
    else:
        fingerprint = arguments.get("fingerprint")
        if (set(arguments) != {"fingerprint"} or not isinstance(fingerprint, str)
                or len(fingerprint) != 64 or any(c not in "0123456789abcdefABCDEF" for c in fingerprint)):
            raise ValueError("Fingerprint must be 64 hex characters")
    response = _rpc("tools/call", {"name": name, "arguments": arguments})
    if "error" in response:
        raise RuntimeError("MCP error: " + str(response["error"]))
    return response.get("result", {})

if __name__ == "__main__":
    print(json.dumps({"tools": TOOLS, "example": "call_privi('privi_pricing', {})"}, indent=2))
