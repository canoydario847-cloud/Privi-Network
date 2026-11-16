#!/usr/bin/env python3
"""Public, read-only MCP handshake test for Privi's six distinct hosted endpoints.

This tests initialize, notifications/initialized and tools/list only.
Never executes tools/call, sends credentials, or accepts paid access.
Designed for GitHub Actions with Python stdlib and no secret variables.
"""
import argparse
import concurrent.futures
import json
from pathlib import Path
import sys
import urllib.error
import urllib.request

CATALOG = Path(__file__).resolve().parent.parent / "glama-directory" / "catalog.json"
MAX_BYTES = 2_000_000
CLIENT_VERSION = "2025-06-18"
DEFAULT_TIMEOUT_SECONDS = 75


class McpHealthError(Exception):
    pass


def parse_message(data: bytes, content_type: str):
    """Parse JSON or standard SSE data lines without executing anything."""
    if len(data) > MAX_BYTES:
        raise McpHealthError("response_too_large")
    try:
        payload = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise McpHealthError("non_utf8_response") from exc
    if "text/event-stream" in content_type.lower():
        records = []
        for block in payload.replace("\r\n", "\n").split("\n\n"):
            event_data = "\n".join(line[5:].lstrip(" ") for line in block.splitlines()
                                   if line.startswith("data:"))
            if event_data and event_data != "[DONE]":
                try:
                    records.append(json.loads(event_data))
                except json.JSONDecodeError:
                    continue
        if not records:
            raise McpHealthError("sse_json_response_missing")
        # The response may contain events other than the final JSON-RPC envelope.
        obj = next((value for value in records if isinstance(value, dict)
                    and ("result" in value or "error" in value)), None)
    else:
        try:
            obj = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise McpHealthError("invalid_json_response") from exc
    if not isinstance(obj, dict):
        raise McpHealthError("invalid_jsonrpc_envelope")
    if obj.get("jsonrpc") != "2.0":
        raise McpHealthError("invalid_jsonrpc_version")
    if "error" in obj:
        raise McpHealthError("jsonrpc_error")
    if not isinstance(obj.get("result"), dict):
        raise McpHealthError("missing_jsonrpc_result")
    return obj


def post(url: str, body: dict, session=None, timeout=DEFAULT_TIMEOUT_SECONDS):
    data = json.dumps(body, separators=(",", ":")).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "User-Agent": "Privi-MCP-Discovery-Check/1.0",
    }
    if session:
        headers["Mcp-Session-Id"] = session
        headers["MCP-Protocol-Version"] = CLIENT_VERSION
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status not in (200, 202):
                raise McpHealthError("http_%s" % response.status)
            data = response.read(MAX_BYTES + 1)
            return response.status, response.headers.get("Content-Type", ""), data, response.headers.get("Mcp-Session-Id")
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise McpHealthError("auth_required") from exc
        raise McpHealthError("http_%s" % exc.code) from exc
    except urllib.error.URLError as exc:
        raise McpHealthError("network_or_timeout") from exc
    except TimeoutError as exc:
        raise McpHealthError("network_or_timeout") from exc


def check_service(service, timeout=DEFAULT_TIMEOUT_SECONDS):
    endpoint = service["endpoint"]
    service_id = service["id"]
    if not endpoint.startswith("https://") or not endpoint.endswith("/mcp"):
        raise McpHealthError("invalid_catalog_endpoint")
    initialization = {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": CLIENT_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "privi-mcp-public-health", "version": "1.0"},
        },
    }
    status, ct, data, session = post(endpoint, initialization, timeout=timeout)
    if status != 200:
        raise McpHealthError("initialize_not_200")
    response = parse_message(data, ct)
    details = response["result"]
    if not isinstance(details.get("serverInfo"), dict):
        raise McpHealthError("missing_server_info")
    if not isinstance(details.get("protocolVersion"), str):
        raise McpHealthError("missing_protocol_version")
    # Sessionful servers need initialized notification before tool discovery.
    # If a server responds with 202, that is a normal MCP notification response.
    notification = {"jsonrpc": "2.0", "method": "notifications/initialized"}
    post(endpoint, notification, session=session, timeout=timeout)
    status, ct, data, _ = post(endpoint, {
        "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {},
    }, session=session, timeout=timeout)
    if status != 200:
        raise McpHealthError("tools_list_not_200")
    catalog = parse_message(data, ct)["result"]
    tools = catalog.get("tools")
    if not isinstance(tools, list) or not tools:
        raise McpHealthError("empty_or_invalid_tools_catalog")
    if not all(isinstance(t, dict) and isinstance(t.get("name"), str) for t in tools):
        raise McpHealthError("invalid_tool_schema")
    return {"id": service_id, "status": "OK", "tools": len(tools),
            "protocol": details["protocolVersion"], "url": endpoint}


def run(services, timeout=DEFAULT_TIMEOUT_SECONDS):
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(check_service, service, timeout): service for service in services}
        for future in concurrent.futures.as_completed(futures):
            service = futures[future]
            try:
                results.append(future.result())
            except (McpHealthError, Exception) as exc:
                # Do not print underlying network errors, tokens, customer data or response bodies.
                code = str(exc) if isinstance(exc, McpHealthError) else "unexpected_error"
                results.append({"id": service["id"], "status": "FAIL", "reason": code,
                                "url": service["endpoint"]})
    return sorted(results, key=lambda item: item["id"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.timeout < 5 or args.timeout > 180:
        parser.error("timeout must be 5..180 seconds")
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    services = data["services"]
    if len(services) != 6 or len({s["endpoint"] for s in services}) != 6:
        parser.error("the Privi MCP catalog must contain six unique remote endpoints")
    results = run(services, timeout=args.timeout)
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for item in results:
            detail = ("tools="+str(item["tools"])+" protocol="+item["protocol"]
                      if item["status"] == "OK" else item["reason"])
            print(item["id"].ljust(17), item["status"].ljust(4), detail, item["url"])
    return 1 if any(item["status"] != "OK" for item in results) else 0


if __name__ == "__main__":
    sys.exit(main())
