"""Offline tests for read-only remote MCP health-check parser and probe logic."""
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

PATH = Path(__file__).resolve().parent / "check_remote_mcp_health.py"
SPEC = importlib.util.spec_from_file_location("check_remote_mcp_health", PATH)
mcp = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mcp)


class RemoteMcpHealthTests(unittest.TestCase):
    def test_valid_json_and_sse_responses(self):
        obj = {"jsonrpc": "2.0", "id": 1,
               "result": {"serverInfo": {"name": "test"}, "protocolVersion": "2025-06-18"}}
        self.assertEqual(mcp.parse_message(json.dumps(obj).encode(), "application/json"), obj)
        sse = ("event: message\ndata: " + json.dumps(obj) + "\n\n").encode()
        self.assertEqual(mcp.parse_message(sse, "text/event-stream"), obj)

    def test_bad_responses_fail_closed(self):
        cases = [
            (b'{"jsonrpc":"2.0","id":1,"error":{"code":-32000}}', "application/json"),
            (b'{not-json}', "application/json"),
            (b'{"id":1,"result":{}}', "application/json"),
            (b'event: ping\n\n', "text/event-stream"),
        ]
        for raw, typ in cases:
            with self.assertRaises(mcp.McpHealthError):
                mcp.parse_message(raw, typ)

    def test_probe_initialization_and_discovery_not_tool_execution(self):
        called = []
        def fake_post(url, body, session=None, timeout=75):
            called.append((url, body["method"], session))
            if body["method"] == "initialize":
                return 200, "application/json", json.dumps({
                    "jsonrpc": "2.0", "id": 1,
                    "result": {"serverInfo": {"name": "Privi Example"},
                               "protocolVersion": "2025-06-18"},
                }).encode(), "safe_session"
            if body["method"] == "notifications/initialized":
                return 202, "", b"", None
            if body["method"] == "tools/list":
                return 200, "application/json", json.dumps({
                    "jsonrpc": "2.0", "id": 2,
                    "result": {"tools": [{"name": "privi_status",
                                         "inputSchema": {"type": "object"}}]},
                }).encode(), None
            raise AssertionError("attempted unsafe MCP operation")
        with patch.object(mcp, "post", side_effect=fake_post):
            result = mcp.check_service({"id": "test", "endpoint": "https://example.com/mcp"})
        self.assertEqual(result["tools"], 1)
        self.assertEqual([x[1] for x in called],
                         ["initialize", "notifications/initialized", "tools/list"])
        self.assertTrue(all(method != "tools/call" for _, method, _ in called))
        self.assertEqual(called[-1][2], "safe_session")

    def test_readonly_checks_report_auth_required_without_leaking(self):
        def blocked(*args, **kwargs):
            raise mcp.McpHealthError("auth_required")
        with patch.object(mcp, "post", side_effect=blocked):
            results = mcp.run([{"id": "blocked", "endpoint": "https://example.com/mcp"}])
        self.assertEqual(results[0]["reason"], "auth_required")
        self.assertEqual(results[0]["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
