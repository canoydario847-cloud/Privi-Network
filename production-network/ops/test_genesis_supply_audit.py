"""Synthetic fixtures only: verify initial PRVI supply accounting fails closed."""
import importlib.util
import unittest
import tempfile
from pathlib import Path

p=Path(__file__).with_name("genesis_supply_audit.py")
spec=importlib.util.spec_from_file_location("genesis_supply_audit",p)
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
UNIT=10**18

def fixture(amount=100*UNIT):
    return {"chain_id":"privi-candidate-1",
            "app_state":{"bank":{
                "balances":[{"address":"privi1example","coins":[{"denom":"aprvi","amount":str(amount)}]}],
                "supply":[{"denom":"aprvi","amount":str(amount)}]}}}


def periodic_genesis(original=60*UNIT, first=20*UNIT, second=40*UNIT):
    g=fixture()
    g["app_state"]["bank"]["balances"][0]["address"]="privi1vestingexample"
    g["app_state"]["auth"]={"accounts":[{
        "@type":"/cosmos.vesting.v1beta1.PeriodicVestingAccount",
        "base_vesting_account":{
            "base_account":{"address":"privi1vestingexample"},
            "original_vesting":[{"denom":"aprvi","amount":str(original)}],
            "end_time":"400"
        },
        "start_time":"100",
        "vesting_periods":[
            {"length":"100","amount":[{"denom":"aprvi","amount":str(first)}]},
            {"length":"200","amount":[{"denom":"aprvi","amount":str(second)}]}
        ]
    }]}
    return g

class SupplyAuditTests(unittest.TestCase):
    def check(self,g):return mod.audit(g,"aprvi","privi-candidate-1")
    def test_valid_allocation(self):
        self.assertEqual(self.check(fixture())["genesis_bank_audit"],"PASS")
    def test_cap_breach(self):
        with self.assertRaisesRegex(ValueError,"exceeds"):
            self.check(fixture(mod.CAP_BASE+1))
    def test_supply_balance_mismatch(self):
        g=fixture()
        g["app_state"]["bank"]["supply"][0]["amount"]="1"
        with self.assertRaisesRegex(ValueError,"differs"):
            self.check(g)
    def test_unexpected_chain(self):
        with self.assertRaisesRegex(ValueError,"chain_id"):
            self.check({"chain_id":"another-network","app_state":fixture()["app_state"]})
    def test_negative_amount(self):
        with self.assertRaisesRegex(ValueError,"nonnegative"):
            self.check(fixture(-1))
    def test_duplicate_account(self):
        g=fixture()
        g["app_state"]["bank"]["balances"].append(g["app_state"]["bank"]["balances"][0].copy())
        with self.assertRaisesRegex(ValueError,"duplicate bank address"):
            self.check(g)
    def test_missing_supply(self):
        g=fixture()
        g["app_state"]["bank"]["supply"]=[]
        with self.assertRaisesRegex(ValueError,"missing"):
            self.check(g)
    def test_zero_rejected(self):
        with self.assertRaisesRegex(ValueError,"zero"):
            self.check(fixture(0))
    def test_invalid_genesis_state(self):
        with self.assertRaises((ValueError,AttributeError)):
            self.check({"chain_id":"privi-candidate-1","app_state":None})

    def test_exact_cap_still_accepted(self):
        self.assertEqual(self.check(fixture(mod.CAP_BASE))["genesis_supply_base_units"], str(mod.CAP_BASE))

    def test_nonnative_balance_and_supply_must_match_too(self):
        g = fixture()
        g["app_state"]["bank"]["balances"][0]["coins"].append({"denom": "uatom", "amount": "5"})
        g["app_state"]["bank"]["supply"].append({"denom": "uatom", "amount": "6"})
        with self.assertRaisesRegex(ValueError, "across denominations"):
            self.check(g)
        g["app_state"]["bank"]["supply"][-1]["amount"] = "5"
        self.assertEqual(self.check(g)["bank_denominations_reconciled"], 2)

    def test_nonnative_supply_duplicate_denom_rejected(self):
        g = fixture()
        g["app_state"]["bank"]["supply"] += [
            {"denom": "uatom", "amount": "1"}, {"denom": "uatom", "amount": "1"}]
        with self.assertRaisesRegex(ValueError, "duplicate denomination"):
            self.check(g)

    def test_oversized_decimal_rejected_before_integer_conversion(self):
        with self.assertRaisesRegex(ValueError, "noncanonical"):
            self.check(fixture("9" * 10000))

    def test_leading_zero_and_unicode_digits_rejected(self):
        for amount in ("0100", "\u0661\u0662\u0663"):
            with self.subTest(amount=amount):
                with self.assertRaisesRegex(ValueError, "noncanonical"):
                    self.check(fixture(amount))

    def test_zero_other_denom_rejected(self):
        g = fixture()
        g["app_state"]["bank"]["balances"][0]["coins"].append({"denom": "uatom", "amount": "0"})
        g["app_state"]["bank"]["supply"].append({"denom": "uatom", "amount": "0"})
        with self.assertRaisesRegex(ValueError, "zero"):
            self.check(g)

    def test_duplicate_genesis_json_key_rejected_before_audit(self):
        raw = b'{"app_state":{"bank":{"supply":[],"supply":[]}}}'
        with self.assertRaisesRegex(ValueError, "duplicate genesis JSON key"):
            mod.parse_strict_json_bytes(raw)

    def test_non_json_numeric_constant_rejected(self):
        for constant in (b'NaN', b'Infinity', b'-Infinity'):
            with self.subTest(constant=constant):
                with self.assertRaisesRegex(ValueError, "invalid JSON numeric"):
                    mod.parse_strict_json_bytes(b'{"x":' + constant + b'}')

    def test_unbounded_or_invalid_utf8_input_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            oversized = Path(temp) / "oversized.json"
            with oversized.open("wb") as stream:
                stream.seek(mod.MAX_GENESIS_FILE_BYTES)
                stream.write(b"x")
            with self.assertRaisesRegex(ValueError, "8 MB"):
                mod.load_strict_genesis(oversized)
        with self.assertRaises(UnicodeError):
            mod.parse_strict_json_bytes(b'{"x":"\xff"}')

    def test_strict_loader_round_trip(self):
        with tempfile.TemporaryDirectory() as temp:
            candidate = Path(temp) / "genesis.json"
            import json
            candidate.write_text(json.dumps(fixture()), encoding="utf-8")
            self.assertEqual(self.check(mod.load_strict_genesis(candidate))["genesis_bank_audit"], "PASS")


    def test_periodic_vesting_sums_and_release_dates_reconcile(self):
        outcome=self.check(periodic_genesis())
        self.assertEqual(outcome["periodic_vesting_accounts_checked"],1)
        self.assertIs(outcome["vesting_execution_verified"],False)

    def test_no_auth_accounts_never_claims_vesting_verified(self):
        outcome=self.check(fixture())
        self.assertEqual(outcome["periodic_vesting_accounts_checked"],0)
        self.assertIs(outcome["vesting_execution_verified"],False)

    def test_empty_periodic_original_vesting_rejected(self):
        g=periodic_genesis()
        g["app_state"]["auth"]["accounts"][0]["base_vesting_account"]["original_vesting"]=[]
        with self.assertRaisesRegex(ValueError,"nonempty original_vesting"):
            self.check(g)

    def test_empty_periodic_release_amount_rejected(self):
        g=periodic_genesis()
        g["app_state"]["auth"]["accounts"][0]["vesting_periods"][0]["amount"]=[]
        with self.assertRaisesRegex(ValueError,"nonempty amount"):
            self.check(g)

    def test_vesting_address_must_have_own_genesis_bank_allocation(self):
        g=periodic_genesis()
        g["app_state"]["bank"]["balances"][0]["address"]="privi1unrelated"
        with self.assertRaisesRegex(ValueError,"own genesis bank balance"):
            self.check(g)

    def test_vesting_address_cannot_borrow_other_accounts_bank_balance(self):
        g=periodic_genesis()
        bank=g["app_state"]["bank"]
        bank["balances"][0]["coins"][0]["amount"]=str(40*UNIT)
        bank["balances"].append({"address":"privi1unrelated",
                                 "coins":[{"denom":"aprvi","amount":str(60*UNIT)}]})
        # Total bank supply remains 100 PRVI, but only 40 belong to
        # the account claiming 60 PRVI of original vesting.
        with self.assertRaisesRegex(ValueError,"own genesis bank balance"):
            self.check(g)

    def test_periodic_vesting_amount_mismatch_fails_closed(self):
        with self.assertRaisesRegex(ValueError,"periodic vesting amounts"):
            self.check(periodic_genesis(second=39*UNIT))

    def test_periodic_vesting_incorrect_end_time_fails_closed(self):
        g=periodic_genesis()
        g["app_state"]["auth"]["accounts"][0]["base_vesting_account"]["end_time"]="401"
        with self.assertRaisesRegex(ValueError,"end_time"):
            self.check(g)

    def test_periodic_vesting_overallocations_exceed_bank_supply(self):
        # All period coins agree with original, but genesis cannot vest more
        # than its entire bank supply of that denomination.
        with self.assertRaisesRegex(ValueError,"allocations exceed bank supply"):
            self.check(periodic_genesis(original=101*UNIT,first=50*UNIT,second=51*UNIT))

    def test_noncanonical_times_and_zero_length_rejected(self):
        for field, value in (("start_time","0100"),("start_time",100),
                             ("start_time","-100"),("start_time","9223372036854775808")):
            with self.subTest(field=field,value=value):
                g=periodic_genesis()
                g["app_state"]["auth"]["accounts"][0][field]=value
                with self.assertRaisesRegex(ValueError,"time"):
                    self.check(g)
        g=periodic_genesis()
        g["app_state"]["auth"]["accounts"][0]["vesting_periods"][0]["length"]="0"
        with self.assertRaisesRegex(ValueError,"time out of bounds"):
            self.check(g)

    def test_periodic_vesting_rejects_time_overflow(self):
        g=periodic_genesis()
        account=g["app_state"]["auth"]["accounts"][0]
        account["start_time"]=str(mod.MAX_TIME_SECONDS-100)
        with self.assertRaisesRegex(ValueError,"time overflow"):
            self.check(g)

    def test_duplicate_periodic_vesting_addresses_rejected(self):
        import copy
        g=periodic_genesis()
        g["app_state"]["auth"]["accounts"].append(
            copy.deepcopy(g["app_state"]["auth"]["accounts"][0]))
        with self.assertRaisesRegex(ValueError,"duplicate periodic vesting"):
            self.check(g)

    def test_periodic_vesting_address_cannot_duplicate_base_auth_account(self):
        for base_first in (True, False):
            with self.subTest(base_first=base_first):
                g=periodic_genesis()
                base={"@type":mod.BASE_ACCOUNT_TYPE,"address":"privi1vestingexample"}
                accounts=g["app_state"]["auth"]["accounts"]
                if base_first:
                    accounts.insert(0, base)
                else:
                    accounts.append(base)
                with self.assertRaisesRegex(ValueError,"duplicate auth account address"):
                    self.check(g)

    def test_duplicate_base_auth_accounts_rejected(self):
        g=fixture()
        base={"@type":mod.BASE_ACCOUNT_TYPE,"address":"privi1same"}
        g["app_state"]["auth"]={"accounts":[base, dict(base)]}
        with self.assertRaisesRegex(ValueError,"duplicate auth account address"):
            self.check(g)

    def test_distinct_base_and_periodic_auth_accounts_allowed(self):
        g=periodic_genesis()
        g["app_state"]["auth"]["accounts"].append(
            {"@type":mod.BASE_ACCOUNT_TYPE,"address":"privi1different"})
        self.assertEqual(self.check(g)["periodic_vesting_accounts_checked"],1)

    def test_unsupported_cosmos_vesting_type_requires_manual_review(self):
        g=periodic_genesis()
        g["app_state"]["auth"]["accounts"][0]["@type"]="/cosmos.vesting.v1beta1.ContinuousVestingAccount"
        with self.assertRaisesRegex(ValueError,"unsupported vesting"):
            self.check(g)

    def test_missing_auth_account_type_rejected(self):
        g=periodic_genesis()
        del g["app_state"]["auth"]["accounts"][0]["@type"]
        with self.assertRaisesRegex(ValueError,"missing account type"):
            self.check(g)

if __name__=="__main__": unittest.main()
