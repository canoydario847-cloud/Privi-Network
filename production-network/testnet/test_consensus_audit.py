"""Offline adversarial tests for valueless upstream CometBFT RPC agreement.

These fixtures do not cryptographically verify signatures and are NOT PoP.
"""
import copy
import unittest
from unittest.mock import patch
import consensus_audit as audit

URLS = ["http://node%d" % n for n in range(4)]
HASH = "A" * 64
VALIDATORS = [{"address": "%040X" % (n + 1), "voting_power": "1"} for n in range(4)]

def commit_with_signers(count=3):
    return {
        "height": "11",
        "block_id": {"hash": HASH},
        "signatures": [
            {"validator_address": v["address"],
             "block_id_flag": 2 if i < count else 1,
             "signature": "AQ==" if i < count else None}
            for i,v in enumerate(VALIDATORS)
        ],
    }

class CometRPCQuorumTests(unittest.TestCase):
    def setUp(self):
        self.commits = {url: commit_with_signers() for url in URLS}

    def fake_get(self, url, route):
        if route == "/status":
            return {
                "node_info": {"id": "unique-" + url, "network": "local-4221"},
                "sync_info": {"latest_block_height": "12", "catching_up": False},
            }
        if route.startswith("/block?height="):
            return {"block_id": {"hash": HASH}}
        if route.startswith("/validators?"):
            return {"validators": copy.deepcopy(VALIDATORS), "total": "4"}
        if route.startswith("/commit?height="):
            return {"signed_header": {"commit": copy.deepcopy(self.commits[url])}}
        raise AssertionError("unexpected test RPC " + route)

    def verify(self):
        with patch.object(audit, "get", side_effect=self.fake_get):
            return audit.audit(URLS)

    def test_all_four_endpoints_have_matching_quorum(self):
        result = self.verify()
        self.assertEqual(result["commitEndpointsChecked"], 4)
        self.assertEqual(result["signedVotingPower"], 3)
        self.assertEqual(result["totalVotingPower"], 4)
        self.assertEqual(result["consensusType"], "UPSTREAM_COMETBFT_NOT_NATIVE_POP")

    def test_one_endpoint_conflicting_commit_hash_fails(self):
        self.commits[URLS[3]]["block_id"]["hash"] = "B" * 64
        with self.assertRaisesRegex(ValueError, "Commit hash mismatch"):
            self.verify()

    def test_one_endpoint_wrong_commit_height_fails(self):
        self.commits[URLS[2]]["height"] = "10"
        with self.assertRaisesRegex(ValueError, "Commit height mismatch"):
            self.verify()

    def test_one_endpoint_lacks_two_thirds_quorum(self):
        self.commits[URLS[1]] = commit_with_signers(2)
        with self.assertRaisesRegex(ValueError, "Insufficient signatures"):
            self.verify()

    def test_duplicate_validator_votes_fail(self):
        self.commits[URLS[0]]["signatures"].append(
            copy.deepcopy(self.commits[URLS[0]]["signatures"][0])
        )
        with self.assertRaisesRegex(ValueError, "Duplicate validator vote"):
            self.verify()

    def test_unknown_signed_validator_fails(self):
        self.commits[URLS[0]]["signatures"][0]["validator_address"] = "F" * 40
        with self.assertRaisesRegex(ValueError, "Unknown or unsigned"):
            self.verify()

    def test_missing_signed_commit_fails(self):
        self.commits[URLS[2]] = None
        with self.assertRaisesRegex(ValueError, "Commit height mismatch"):
            self.verify()

if __name__ == "__main__":
    unittest.main()
