import importlib.util
from pathlib import Path
import json
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("pop_mainnet_guard", HERE / "pop_mainnet_guard.py")
gate_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate_module)


def baseline():
    return json.loads((HERE / "privi_pop_iot_development.template.json").read_text())


class TestPoPMainnetGate(unittest.TestCase):
    def test_developer_feature_configuration_does_not_authorize_mainnet(self):
        self.assertEqual(gate_module.gate(baseline(), financial_mainnet=False)["status"],
                         "DEVELOPMENT_ONLY")
        result = gate_module.gate(baseline())
        self.assertEqual(result["status"], "NO_GO")
        self.assertFalse(result["production_mainnet_activated"])
        self.assertFalse(result["financial_prvi_issued"])
        self.assertTrue(any("PoP BFT consensus" in x for x in result["blockers"]))

    def test_foreign_chain_settlement_is_refused(self):
        for field, bad in (("chain_family", "base"), ("iot_settlement", "bnb"),
                           ("target_protocol", "proof-of-stake"),
                           ("external_bridges", True), ("external_pairings", True),
                           ("real_prvi_rewards", True)):
            with self.subTest(field=field):
                payload = baseline()
                payload[field] = bad
                self.assertEqual(gate_module.gate(payload, financial_mainnet=False)["status"],
                                 "NO_GO")

    def test_pos_and_posa_explicitly_rejected(self):
        for kind in ("pos", "posa", "proof-of-stake", "proof-of-staked-authority"):
            payload = baseline()
            payload["consensus_kind"] = kind
            self.assertTrue(any("PoS or PoSA" in x
                                for x in gate_module.gate(payload)["blockers"]))

    def test_unknown_or_missing_consensus_state_fails_closed(self):
        for kind in (None, "", "pop", "custom", "proof-of-participation"):
            with self.subTest(kind=kind):
                payload = baseline()
                if kind is None:
                    del payload["consensus_kind"]
                else:
                    payload["consensus_kind"] = kind
                result = gate_module.gate(payload, financial_mainnet=False)
                self.assertEqual(result["status"], "NO_GO")
                self.assertTrue(any("consensus implementation state" in x
                                    for x in result["blockers"]))

    def test_missing_hardened_iot_controls_fail_closed(self):
        for control in gate_module.REQUIRED_IOT_CONTROLS:
            with self.subTest(control=control):
                payload = baseline()
                del payload["iot_controls"][control]
                result = gate_module.gate(payload, financial_mainnet=False)
                self.assertEqual(result["status"], "NO_GO")
                self.assertTrue(any(control in x for x in result["blockers"]))

    def test_owner_attestations_do_not_unblock_unimplemented_pop(self):
        payload = baseline()
        payload["mainnet_approved"] = True
        payload["consensus_certified"] = True
        payload["validators"] = ["approved"] * 4
        self.assertEqual(gate_module.gate(payload)["status"], "NO_GO")
        self.assertFalse(gate_module.POP_CONSENSUS_IMPLEMENTED)


if __name__ == "__main__":
    unittest.main()
