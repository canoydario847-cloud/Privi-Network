"""Offline tests for Glama's catalog-only, fail-closed MCP runner."""
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def run_protocol(*requests):
    data = "".join(json.dumps(x) + "\n" for x in requests)
    process = subprocess.run(
        [sys.executable, "-u", str(ROOT / "server.py")],
        input=data, capture_output=True, encoding="utf-8", timeout=10, check=True,
    )
    assert not process.stderr, process.stderr
    return [json.loads(line) for line in process.stdout.splitlines() if line.strip()]


class GlamaDirectoryTests(unittest.TestCase):
    def test_initialization_and_tool_discovery(self):
        outputs = run_protocol(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18",
                        "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "resources/list"},
            {"jsonrpc": "2.0", "id": 4, "method": "prompts/list"},
        )
        self.assertEqual(len(outputs), 4)
        self.assertEqual(outputs[0]["result"]["protocolVersion"], "2025-06-18")
        names = {t["name"] for t in outputs[1]["result"]["tools"]}
        self.assertEqual(names, {"privi_network_service_directory", "privi_network_access_information"})
        self.assertEqual(outputs[2]["result"]["resources"], [])
        self.assertEqual(outputs[3]["result"]["prompts"], [])

    def test_six_servers_and_no_paid_tool_proxy(self):
        outputs = run_protocol(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
             "params": {"name": "privi_network_service_directory", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "privi_verify_lot", "arguments": {"lot_code": "DEMO"}}},
        )
        catalog = outputs[0]["result"]["structuredContent"]
        self.assertEqual(len(catalog["services"]), 6)
        self.assertEqual(len({s["endpoint"] for s in catalog["services"]}), 6)
        self.assertTrue(all(s["endpoint"].startswith("https://") and s["endpoint"].endswith("/mcp")
                            for s in catalog["services"]))
        self.assertTrue(outputs[1]["result"]["isError"])
        self.assertNotIn("structuredContent", outputs[1]["result"])

    def test_read_only_access_terms_and_unknown_service_rejected(self):
        outputs = run_protocol(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
             "params": {"name": "privi_network_access_information", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "privi_network_service_directory", "arguments": {"service_id": "unknown"}}},
            {"jsonrpc": "2.0", "id": 3, "method": "tool/not-real"},
        )
        self.assertIn("19.99", outputs[0]["result"]["structuredContent"]["human_service_offers"]["security_review_usd"])
        self.assertTrue(outputs[1]["result"]["isError"])
        self.assertEqual(outputs[2]["error"]["code"], -32601)


if __name__ == "__main__":
    unittest.main()
