"""Offline regressions for four distinct CometBFT signing identities.

These mocked RPC responses are not a substitute for real PoP BFT testing.
"""
import unittest
from unittest.mock import patch

import consensus_audit


class LocalValidatorSignerTests(unittest.TestCase):
    def setUp(self):
        self.urls = [f"http://node{i}" for i in range(4)]
        self.signers = [f"{i + 1:040X}" for i in range(4)]
        self.voters = {address: 10 for address in self.signers}
        self.statuses = {
            url: {
                "node_info": {"id": f"peer{i}", "network": "local-4221"},
                "sync_info": {"latest_block_height": "6", "catching_up": False},
                "validator_info": {"address": self.signers[i], "voting_power": "10"},
            }
            for i, url in enumerate(self.urls)
        }

    def run_audit(self):
        def fake_get(url, route):
            if route == "/status":
                return self.statuses[url]
            if route.startswith("/block?"):
                return {"block_id": {"hash": "ABC"}}
            if route.startswith("/commit?"):
                return {"signed_header": {"commit": {
                    "block_id": {"hash": "ABC"},
                    "signatures": [
                        {"validator_address": addr, "block_id_flag": 2, "signature": "signed"}
                        for addr in self.signers
                    ],
                }}}
            raise AssertionError(f"Unexpected route: {route}")

        with patch.object(consensus_audit, "get", side_effect=fake_get), \
             patch.object(consensus_audit, "validator_set", return_value=self.voters):
            return consensus_audit.audit(self.urls)

    def test_four_distinct_active_signers_pass(self):
        result = self.run_audit()
        self.assertEqual(result["votingValidators"], 4)
        self.assertEqual(result["signedVotingPower"], 40)

    def test_two_rpc_peers_cannot_claim_same_signing_identity(self):
        self.statuses[self.urls[3]]["validator_info"]["address"] = self.signers[0]
        with self.assertRaisesRegex(ValueError, "Duplicate validator signing identities"):
            self.run_audit()

    def test_sentry_rpc_endpoint_is_not_a_validator_signer(self):
        self.statuses[self.urls[3]]["validator_info"]["address"] = "F" * 40
        with self.assertRaisesRegex(ValueError, "not a voting validator signer"):
            self.run_audit()

    def test_local_signer_power_must_match_validator_set(self):
        self.statuses[self.urls[3]]["validator_info"]["voting_power"] = "9"
        with self.assertRaisesRegex(ValueError, "power disagrees"):
            self.run_audit()


if __name__ == "__main__":
    unittest.main()
