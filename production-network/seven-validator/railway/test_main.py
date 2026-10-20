"""Offline, no-Docker safeguards for Railway Privi seven-validator staging."""
import importlib.util
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

modpath = Path(__file__).with_name("main.py")
spec = importlib.util.spec_from_file_location("privi_railway_main", modpath)
rail = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rail)


class RailwayStagingTests(unittest.TestCase):
    def test_guard_rejects_missing_and_duplicate_bootstrap_tokens(self):
        with patch.dict(os.environ, {"PRIVI_BOOTSTRAP_TOKENS_JSON": "{}"}):
            with self.assertRaises(SystemExit):
                rail.require_tokens()
        vals = {str(i): ("z" * 64) for i in range(7)}
        with patch.dict(os.environ, {"PRIVI_BOOTSTRAP_TOKENS_JSON": json.dumps(vals)}):
            with self.assertRaises(SystemExit):
                rail.require_tokens()
        vals = {str(i): str(i) * 64 for i in range(7)}
        with patch.dict(os.environ, {"PRIVI_BOOTSTRAP_TOKENS_JSON": json.dumps(vals)}):
            self.assertEqual(rail.require_tokens(), vals)

    def test_railway_peer_config_is_private_ipv6_and_seven_unique_nodes(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            (home / "config").mkdir()
            (home / "config/genesis.json").write_text("{}")
            config = ("""
[rpc]
laddr = "tcp://127.0.0.1:26657"
[p2p]
laddr = "tcp://0.0.0.0:26656"
persistent_peers = ""
addr_book_strict = true
pex = true
[mempool]
type = "flood"
""")
            (home / "config/config.toml").write_text(config)
            ids = [("%040x" % (n + 1)) for n in range(7)]
            rail.configure_node(home, 3, ids)
            updated = (home / "config/config.toml").read_text()
            self.assertIn("tcp://[::]:26656", updated)
            self.assertIn("tcp://[::]:26657", updated)
            self.assertIn('type = "app"', updated)
            self.assertEqual(updated.count(".railway.internal:26656"), 6)
            self.assertNotIn(ids[3], updated)
            self.assertIn("addr_book_strict = false", updated)

    def test_unknown_upstream_section_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "config.toml"
            path.write_text("[p2p]\nladdr = \"tcp://0.0.0.0:26656\"\n")
            with self.assertRaises(SystemExit):
                rail.edit_section(path, "p2p", {"persistent_peers": "x"})

    def test_refuse_archive_traversal(self):
        with tempfile.TemporaryDirectory() as d:
            b = io.BytesIO()
            with tarfile.open(fileobj=b, mode="w:gz") as tar:
                info = tarfile.TarInfo("evmd/../../escape")
                payload = b"x"
                info.size = len(payload)
                tar.addfile(info, io.BytesIO(payload))
            with self.assertRaises(SystemExit):
                rail.extract_bundle(b.getvalue(), Path(d) / "out")
            self.assertFalse((Path(d) / "escape").exists())

    def test_node_names_are_fixed_internal_dns(self):
        self.assertEqual(len(set(rail.NODE_NAMES)), 7)
        self.assertTrue(all(n.endswith(".railway.internal") for n in rail.NODE_NAMES))
        self.assertEqual(rail.CHAIN, "local-privi-seven-4221")


if __name__ == "__main__":
    unittest.main()
