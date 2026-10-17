#!/usr/bin/env python3
"""Offline positive and tamper-negative checks for unfunded CI allocations."""
import copy
import unittest
from ci_funded_genesis_positive import allocations, check_funded_genesis, CAP, DISTRIBUTION
from test_bech32_accounts import test_address


def synthetic_genesis(rows):
    return {"chain_id": "privi-ci-nonproduction-999", "app_state": {
        "evm": {"params": {"evm_denom": "aprvi",
                           "extended_denom_options": {"extended_denom": "aprvi"}}},
        "staking": {"params": {"bond_denom": "aprvi"}},
        "mint": {"params": {"mint_denom": "aprvi"},
                 "minter": {"inflation": "0.000000000000000000"}},
        "feemarket": {"params": {"no_base_fee": False}},
        "erc20": {"token_pairs": []},
        "bank": {
            "denom_metadata": [{
                "base": "aprvi", "display": "prvi", "name": "Privi", "symbol": "PRVI",
                "denom_units": [{"denom": "aprvi", "exponent": 0},
                                {"denom": "prvi", "exponent": 18}]
            }],
            "balances": [{"address": a["address"],
                          "coins": [{"denom": "aprvi", "amount": str(a["amount_base_units"])}]}
                         for a in rows],
            "supply": [{"denom": "aprvi", "amount": str(CAP)}]
        },
        "genutil": {"gen_txs": [{
            "body": {"messages": [{"@type": "/cosmos.staking.v1beta1.MsgCreateValidator"}]},
            "auth_info": {}, "signatures": ["fake_ci_signing_shape_only"]
        }]}
    }}


class PositiveGenesisRehearsalTests(unittest.TestCase):
    def setUp(self):
        self.rows = allocations(test_address(200))
        self.genesis = synthetic_genesis(self.rows)

    def test_exact_five_category_total_and_real_bech32_checksums(self):
        self.assertEqual(len(self.rows), len(DISTRIBUTION))
        self.assertEqual(sum(x["amount_base_units"] for x in self.rows), CAP)
        self.assertEqual(check_funded_genesis(self.genesis, self.rows), [])

    def test_under_or_over_supply_is_never_approved(self):
        for difference in (-1, 1):
            doc = copy.deepcopy(self.genesis)
            doc["app_state"]["bank"]["supply"][0]["amount"] = str(CAP + difference)
            self.assertTrue(check_funded_genesis(doc, self.rows))

    def test_allocations_must_match_expected_addresses_and_amounts(self):
        doc = copy.deepcopy(self.genesis)
        doc["app_state"]["bank"]["balances"][2]["coins"][0]["amount"] = "1"
        self.assertTrue(any("allocation amounts" in err for err in check_funded_genesis(doc, self.rows)))
        doc = copy.deepcopy(self.genesis)
        doc["app_state"]["bank"]["balances"][4]["address"] = self.rows[1]["address"]
        self.assertTrue(check_funded_genesis(doc, self.rows))

    def test_wrong_denom_and_missing_gentx_rejected(self):
        doc = copy.deepcopy(self.genesis)
        doc["app_state"]["bank"]["balances"][0]["coins"][0]["denom"] = "atest"
        self.assertTrue(check_funded_genesis(doc, self.rows))
        doc = copy.deepcopy(self.genesis)
        doc["app_state"]["genutil"]["gen_txs"] = []
        self.assertTrue(any("gentx" in err for err in check_funded_genesis(doc, self.rows)))

    def test_real_wallet_never_used_as_synthetic_fixture(self):
        self.assertNotIn("0x1990589FD200E043b8C6FD9ec5956c61b3071048",
                         {r["address"] for r in self.rows})


if __name__ == "__main__":
    unittest.main()
