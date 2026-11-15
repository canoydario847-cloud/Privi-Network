"""Privi Network catalog-only MCP server for reproducible Glama inspection.

No network calls, credentials, paid tool execution, or customer data access.
Commercial services are hosted separately at their documented endpoints.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

CATALOG_PATH = Path(__file__).with_name("catalog.json")
CATALOG = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
SERVICES = {item["id"]: item for item in CATALOG["services"]}
VERSION = "0.1.0"
PROTOCOL = "2025-06-18"
MAX_LINE_BYTES = 1_000_000

TOOLS = [
    {
        "name": "privi_network_service_directory",
        "description": (
            "Find current Privi Ledger, Verify, Anchor, Quantum, Call or Agent Survival "
            "MCP endpoints and their Glama listings. This is informational discovery only; "
            "the tool does not invoke, pay for, or grant access to commercial services."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "service_id": {
                    "type": "string",
                    "enum": sorted(SERVICES),
                    "description": (
                        "Optional exact Privi service identifier; omit to return all six "
                        "distinct hosted MCP services."
                    ),
                }
            },
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "privi_network_access_information",
        "description": (
            "Show Privi's published human-review pricing and limitations on paid API access. "
            "No checkout, API credential, entitlement, or external paid action is created."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
]


def call_tool(params: object) -> dict:
    if not isinstance(params, dict):
        return _tool_error("Tool parameters must be an object.")
    name, arguments = params.get("name"), params.get("arguments") or {}
    if not isinstance(arguments, dict):
        return _tool_error("Tool arguments must be an object.")
    if name == "privi_network_service_directory":
        if any(k != "service_id" for k in arguments):
            return _tool_error("Only service_id is accepted.")
        service_id = arguments.get("service_id")
        if service_id is None:
            output = {"services": CATALOG["services"], "disclaimer": CATALOG["disclaimer"]}
        elif isinstance(service_id, str) and service_id in SERVICES:
            output = {"service": SERVICES[service_id], "disclaimer": CATALOG["disclaimer"]}
        else:
            return _tool_error("Unknown service_id; use an identifier returned by tools/list.")
    elif name == "privi_network_access_information":
        if arguments:
            return _tool_error("This tool does not accept arguments.")
        output = {
            "publisher": CATALOG["publisher"],
            "contact": CATALOG["support_email"],
            "human_service_offers": CATALOG["human_service_offers"],
            "disclaimer": CATALOG["disclaimer"],
        }
    else:
        return _tool_error("Unknown tool. This server does not execute commercial Privi tools.")
    return {
        "content": [{"type": "text", "text": json.dumps(output, ensure_ascii=False)}],
        "structuredContent": output,
        "isError": False,
    }


def _tool_error(message: str) -> dict:
    return {"content": [{"type": "text", "text": message}], "isError": True}


def dispatch(request: dict) -> object:
    method = request.get("method")
    if method == "initialize":
        return {
            "protocolVersion": PROTOCOL,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "privi-network-directory", "title": "Privi Network", "version": VERSION},
            "instructions": (
                "Read-only catalog of six distinct, remote Privi MCP servers. "
                "The catalog is not an execution proxy and never bypasses paid-service access. "
                "Use each service's current MCP endpoint under that service's own payment and authentication terms."
            ),
        }
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        return call_tool(request.get("params"))
    if method == "resources/list":
        return {"resources": []}
    if method == "prompts/list":
        return {"prompts": []}
    return None


def main() -> None:
    for line in sys.stdin.buffer:
        if not line.strip():
            continue
        if len(line) > MAX_LINE_BYTES:
            continue
        try:
            request = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(request, dict):
            continue
        if "id" not in request:
            # MCP notifications must not generate JSON-RPC responses.
            continue
        result = dispatch(request)
        if result is None:
            response = {
                "jsonrpc": "2.0", "id": request["id"],
                "error": {"code": -32601, "message": "Method not found"},
            }
        else:
            response = {"jsonrpc": "2.0", "id": request["id"], "result": result}
        sys.stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
