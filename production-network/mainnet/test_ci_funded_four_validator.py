#!/usr/bin/env python3
"""Negative/synthetic tests for four-node funded-consensus CI gate."""
import base64
import copy
import json
import unittest
from unittest.mock import patch

from ci_funded_four_validator import (
    COUNT, CAP, synthetic_funded_rows, check_four_funded_genesis,
    private_four_node_comet_config, consensus_evidence, three_of_four_outage_evidence,
    four_node_rejoin_evidence, signing_state_snapshot, validate_safe_restart
)
from test_bech32_accounts import test_address
from test_ci_funded_genesis_positive import synthetic_genesis

IDS = [("%040x" % (i+1)) for i in range(COUNT)]
KEYS = [bytes([i+11])*32 for i in range(COUNT)]
ADDRESSES = [test_address(205+i) for i in range(COUNT)]


def cometcfg():
    return (
        '[rpc]\n'
        'laddr = "tcp://127.0.0.1:26657"\n'
        '[p2p]\n'
        'laddr = "tcp://0.0.0.0:26656"\n'
        'persistent_peers = ""\n'
        'addr_book_strict = true\n'
        'allow_duplicate_ip = false\n'
        'pex = true\n'
        '[mempool]\n'
        'type = "flood"\n'
    )


def genesis():
    rows = synthetic_funded_rows(ADDRESSES)
    raw = synthetic_genesis([{**row, "amount_base_units": row["amount"]} for row in rows])
    raw["app_state"]["bank"]["balances"] = [
        {"address": x["address"], "coins": [{"denom":"aprvi","amount":str(x["amount"])}]}
        for x in rows
    ]
    raw["app_state"]["genutil"]["gen_txs"] = [
        {"body":{"messages":[{
            "@type":"/cosmos.staking.v1beta1.MsgCreateValidator",
            "pubkey":{"@type":"/cosmos.crypto.ed25519.PubKey",
                      "key":base64.b64encode(k).decode("ascii")},
            "validator_address":"privivaloper1"+str(i)*38,
            "value":{"denom":"aprvi","amount":str(10**18)}
        }]}, "auth_info":{}, "signatures":[base64.b64encode(b"x"*64).decode("ascii")]}
        for i,k in enumerate(KEYS)
    ]
    return raw, rows


class FourValidatorCIRehearsalTests(unittest.TestCase):
    def test_exact_cap_with_four_synthetic_accounts_plus_four_bucket_recipients(self):
        doc, rows = genesis()
        self.assertEqual(len(rows), 8)
        self.assertEqual(sum(r["amount"] for r in rows), CAP)
        self.assertEqual(check_four_funded_genesis(doc, rows, KEYS), [])

    def test_duplicate_or_missing_genesis_consensus_key_fails(self):
        doc, rows = genesis()
        doc["app_state"]["genutil"]["gen_txs"][0]["body"]["messages"][0]["pubkey"] = (
            doc["app_state"]["genutil"]["gen_txs"][1]["body"]["messages"][0]["pubkey"])
        self.assertTrue(check_four_funded_genesis(doc, rows, KEYS))
        doc, rows = genesis()
        doc["app_state"]["genutil"]["gen_txs"].pop()
        self.assertTrue(check_four_funded_genesis(doc, rows, KEYS))

    def test_wrong_bank_supply_or_allocation_fails(self):
        doc, rows = genesis()
        doc["app_state"]["bank"]["supply"][0]["amount"] = str(CAP-1)
        self.assertTrue(check_four_funded_genesis(doc, rows, KEYS))
        doc, rows = genesis()
        doc["app_state"]["bank"]["balances"][0]["coins"][0]["amount"] = "1"
        self.assertTrue(check_four_funded_genesis(doc, rows, KEYS))

    def test_four_unique_privi_native_accounts_only(self):
        with self.assertRaises(ValueError):
            synthetic_funded_rows(ADDRESSES[:3])
        with self.assertRaises(ValueError):
            synthetic_funded_rows([ADDRESSES[0]]*4)
        with self.assertRaises(ValueError):
            synthetic_funded_rows(["0x1990589FD200E043b8C6FD9ec5956c61b3071048"] + ADDRESSES[1:])

    def test_ports_peers_and_mempool_are_loopback_and_distinct(self):
        from ci_funded_four_validator import strict_toml
        for i in range(COUNT):
            doc = strict_toml(private_four_node_comet_config(cometcfg(), i, IDS))
            self.assertEqual(doc["p2p"]["laddr"], f"tcp://127.0.0.1:{26656+10*i}")
            self.assertEqual(doc["rpc"]["laddr"], f"tcp://127.0.0.1:{26657+10*i}")
            self.assertEqual(doc["mempool"]["type"], "app")
            self.assertFalse(doc["p2p"]["addr_book_strict"])
            self.assertTrue(doc["p2p"]["allow_duplicate_ip"])
            self.assertFalse(doc["p2p"]["pex"])
            self.assertEqual(len(doc["p2p"]["persistent_peers"].split(",")), 3)

    def test_missing_comet_settings_or_duplicate_peers_rejected(self):
        with self.assertRaises(ValueError):
            private_four_node_comet_config(cometcfg().replace('pex = true\n', ''), 0, IDS)
        with self.assertRaises(ValueError):
            private_four_node_comet_config(cometcfg(), 0, [IDS[0]]*4)

    def test_outage_rehearsal_requires_three_survivor_nodes_and_two_new_blocks(self):
        target = 7
        def rpc(index, path):
            if path == "status":
                return {"result": {"node_info": {"id": IDS[index]},
                                   "sync_info": {"latest_block_height": "8"}}}
            if path.startswith("block?"):
                return {"result": {"block_id": {"hash": "A"*64}}}
            if path.startswith("validators?"):
                return {"result": {"validators": [
                    {"pub_key": {"value": base64.b64encode(k).decode("ascii")},
                     "voting_power": "1"}
                    for k in KEYS
                ]}}
            return None
        with patch("ci_funded_four_validator.local_rpc", side_effect=rpc):
            ev = three_of_four_outage_evidence(KEYS, target)
        self.assertEqual(ev["live_validators"], 3)
        self.assertTrue(ev["consensus_live_with_one_offline"])
        def broken(index, path):
            obj = rpc(index, path)
            if index == 1 and path.startswith("block?"):
                obj["result"]["block_id"]["hash"] = "B"*64
            return obj
        with patch("ci_funded_four_validator.local_rpc", side_effect=broken):
            self.assertIsNone(three_of_four_outage_evidence(KEYS, target))
        def behind(index, path):
            obj = rpc(index, path)
            if index == 2 and path == "status":
                obj["result"]["sync_info"]["latest_block_height"] = "6"
            return obj
        with patch("ci_funded_four_validator.local_rpc", side_effect=behind):
            self.assertIsNone(three_of_four_outage_evidence(KEYS, target))
        with self.assertRaises(ValueError):
            three_of_four_outage_evidence(KEYS, 2)

    def test_original_validator_rejoin_requires_four_shared_post_restart_blocks(self):
        def rpc(i, path):
            if path == "status":
                return {"result": {"node_info": {"id": IDS[i]},
                                   "sync_info": {"latest_block_height": "12"}}}
            if path.startswith("block?"):
                return {"result": {"block_id": {"hash": "A"*64}}}
            if path.startswith("validators?"):
                return {"result": {"validators": [
                    {"pub_key": {"value": base64.b64encode(k).decode()},
                     "voting_power": "1"}
                    for k in KEYS
                ]}}
            return None
        with patch("ci_funded_four_validator.local_rpc", side_effect=rpc):
            evidence = four_node_rejoin_evidence(KEYS, IDS[3], 9)
        self.assertTrue(evidence["all_four_same_block_hash"])
        self.assertTrue(evidence["restarted_node_identity_preserved"])
        self.assertEqual(evidence["post_rejoin_committed_height"], 9)

        def stalled(i, path):
            response = rpc(i, path)
            if i == 3 and path == "status":
                response["result"]["sync_info"]["latest_block_height"] = "8"
            return response
        with patch("ci_funded_four_validator.local_rpc", side_effect=stalled):
            self.assertIsNone(four_node_rejoin_evidence(KEYS, IDS[3], 9))

        def changed_node(i, path):
            response = rpc(i, path)
            if i == 3 and path == "status":
                response["result"]["node_info"]["id"] = IDS[0]
            return response
        with patch("ci_funded_four_validator.local_rpc", side_effect=changed_node):
            self.assertIsNone(four_node_rejoin_evidence(KEYS, IDS[3], 9))

        def diverged(i, path):
            response = rpc(i, path)
            if i == 3 and path.startswith("block?"):
                response["result"]["block_id"]["hash"] = "B"*64
            return response
        with patch("ci_funded_four_validator.local_rpc", side_effect=diverged):
            self.assertIsNone(four_node_rejoin_evidence(KEYS, IDS[3], 9))

        with self.assertRaises(ValueError):
            four_node_rejoin_evidence(KEYS, IDS[3], 2)

    def test_last_sign_state_rollback_or_key_change_blocks_restart(self):
        base = {"identity_hashes": (b"X", b"Y", b"Z"), "sign_state": (7, 0, 2)}
        latest = {"identity_hashes": (b"X", b"Y", b"Z"), "sign_state": (8, 0, 0)}
        self.assertTrue(validate_safe_restart(base, latest))
        rollback = {"identity_hashes": (b"X", b"Y", b"Z"), "sign_state": (6, 99, 99)}
        with self.assertRaisesRegex(ValueError, "rolled backward"):
            validate_safe_restart(base, rollback)
        replaced = {"identity_hashes": (b"other", b"Y", b"Z"), "sign_state": (8, 0, 0)}
        with self.assertRaisesRegex(ValueError, "altered"):
            validate_safe_restart(base, replaced)

    def test_signing_state_snapshot_requires_persisted_state(self):
        from pathlib import Path
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / "config").mkdir()
            (home / "data").mkdir()
            for filename in ("priv_validator_key.json", "node_key.json", "genesis.json"):
                (home / "config" / filename).write_text("test-stub", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "last-sign"):
                signing_state_snapshot(home)
            state = home / "data" / "priv_validator_state.json"
            state.write_text(json.dumps({"height": "7", "round": 0, "step": 2}))
            snapshot = signing_state_snapshot(home)
            self.assertEqual(snapshot["sign_state"], (7, 0, 2))
            state.write_text(json.dumps({"height": "-1", "round": 0, "step": 2}))
            with self.assertRaisesRegex(ValueError, "non-monotonic"):
                signing_state_snapshot(home)

    def test_fake_agreement_requires_all_four_nodes_and_validator_keys(self):
        def fake(index, path):
            if path == "status":
                return {"result":{"node_info":{"id":IDS[index]},
                                  "sync_info":{"latest_block_height":"3"}}}
            if path.startswith("block?"):
                return {"result":{"block_id":{"hash":"A"*64}}}
            if path.startswith("validators?"):
                return {"result":{"validators":[{
                    "pub_key":{"value":base64.b64encode(key).decode()},
                    "voting_power":"1"
                } for key in KEYS]}}
            return None
        with patch("ci_funded_four_validator.local_rpc", side_effect=fake):
            evidence = consensus_evidence(KEYS)
        self.assertEqual(evidence["validators"], 4)
        self.assertTrue(evidence["equal_hash"])
        def fake_mismatch(index, path):
            out = fake(index, path)
            if index == 3 and path.startswith("block?"):
                out["result"]["block_id"]["hash"] = "B"*64
            return out
        with patch("ci_funded_four_validator.local_rpc", side_effect=fake_mismatch):
            self.assertIsNone(consensus_evidence(KEYS))


if __name__ == "__main__":
    unittest.main()
