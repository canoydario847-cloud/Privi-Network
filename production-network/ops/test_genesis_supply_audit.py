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

if __name__=="__main__": unittest.main()
