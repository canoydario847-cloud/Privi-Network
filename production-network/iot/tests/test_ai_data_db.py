import importlib.util
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pop_position as pop
SPEC = importlib.util.spec_from_file_location("privi_iot_ai", ROOT / "ai_data_db.py")
ai = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ai)


def sample():
    return {
        "version": 3, "companyId": "PRIVI_TEST_CO", "popZone": "GRID/READINGS",
        "positionSequence": 1,
        "deviceId": "iot.test-001", "sequence": 1,
        "observedAt": 1760912345, "eventType": "environment.temperature",
        "payload": {"temperatureC": 22, "humidityPct": 51},
        "signatureBase64": "test-signature-only",
    }


def confirmed(packet):
    return {
        **ai.event_hashes(packet),
        "transactionHash": "0x" + "c" * 64,
        "blockNumber": 25,
        "blockTimestamp": 1760912345,
        "chainId": 262144,
        "confirmations": 2,
        "sequence": packet["sequence"],
    }


class LocalAiTest(unittest.TestCase):
    def test_local_labels_and_positive_non_minted_value(self):
        out = ai.predict(sample())
        self.assertIn(out["suggested_label"], ai.CATEGORIES)
        self.assertEqual(out["engine"], "local-naive-bayes-v1")
        quote = ai.quality_and_quote(sample())
        self.assertGreater(quote["proposed_micro_prvi"], 0)
        self.assertEqual(quote["pop_protocol"], "Point of Position")
        self.assertFalse(quote["pop_verified"])
        self.assertEqual(quote["valuation_status"], "PROPOSAL_ONLY_NOT_MINTED")

    def test_features_do_not_expose_values(self):
        packet = sample()
        packet["payload"]["email"] = "private@example.org"
        text = " ".join(ai.features(packet))
        self.assertNotIn("private@", text)

    def test_record_confirmation_and_refuse_duplicate(self):
        packet = sample()
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "iot.db"
            out = ai.record(db, packet, confirmed(packet))
            self.assertEqual(out["stored_raw_sensor_data"], False)
            self.assertEqual(out["pop_stamp"], "PoP:PRIVI_TEST_CO:GRID/READINGS:000001")
            self.assertTrue(out["pop_verified"])
            self.assertEqual(out["pop_sealed_reports"], 1)
            with sqlite3.connect(db) as conn:
                n, quote = conn.execute("SELECT COUNT(*), SUM(proposed_micro_prvi) FROM iot_events").fetchone()
            self.assertEqual(n, 1)
            self.assertGreater(quote, 0)
            with self.assertRaisesRegex(ValueError, "company-zone sequence"):
                ai.record(db, packet, confirmed(packet))

    def test_refuse_unconfirmed_wrong_hash_and_external_chain(self):
        packet = sample()
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "iot.db"
            c = confirmed(packet)
            with self.assertRaisesRegex(ValueError, "hash"):
                ai.record(db, packet, {**c, "eventHash": "0x" + "0"*64})
            with self.assertRaisesRegex(ValueError, "Unconfirmed"):
                ai.record(db, packet, {**c, "confirmations": 0})
            with self.assertRaisesRegex(ValueError, "Native Privi"):
                ai.record(db, packet, {**c, "chainId": 56})

    def test_pop_leverage_formula_and_duration(self):
        self.assertEqual(pop.leverage_bps(0, 0), 10000)
        self.assertEqual(pop.leverage_bps(50, 365), 25000)
        self.assertEqual(pop.leverage_bps(500, 3650), 25000)
        self.assertEqual(pop.leverage_bps(25, 0), 14500)
        self.assertEqual(pop.leverage_bps(0, 365), 16000)
        self.assertEqual(pop.stamp("PRIVI_TEST_CO","GRID/READINGS",12),
                         "PoP:PRIVI_TEST_CO:GRID/READINGS:000012")
        self.assertGreater(pop.proposal("GRID/READINGS", 50, 365)["proposed_micro_prvi"],
                           pop.proposal("GRID/READINGS", 1, 0)["proposed_micro_prvi"])
        with self.assertRaises(ValueError):
            pop.stamp("PRIVI_TEST_CO", "ETHEREUM", 1)

    def test_pop_history_growth_is_computed_from_sealed_receipts(self):
        packet = sample()
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "iot.db"
            first = ai.record(db, packet, confirmed(packet))
            other = {**packet, "sequence": 2, "positionSequence": 2}
            c = {**confirmed(other), "blockTimestamp": 1760912345 + 86400,
                 "blockNumber": 26, "transactionHash": "0x" + "d" * 64}
            second = ai.record(db, other, c)
            self.assertEqual(second["pop_sealed_reports"], 2)
            self.assertEqual(second["pop_duration_days"], 1)
            self.assertGreater(second["pop_leverage_basis_points"], first["pop_leverage_basis_points"])
            self.assertEqual(second["pop_stamp"],"PoP:PRIVI_TEST_CO:GRID/READINGS:000002")

    def test_parallel_devices_share_one_ordered_pop_position_space(self):
        packet = sample()
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "iot.db"
            ai.record(db, packet, confirmed(packet))
            parallel = {**packet, "deviceId": "iot.test-002", "sequence": 1,
                        "positionSequence": 1}
            c = {**confirmed(parallel), "transactionHash": "0x" + "e"*64,
                 "blockNumber": 27}
            with self.assertRaisesRegex(ValueError, "company-zone sequence"):
                ai.record(db, parallel, c)
            parallel["positionSequence"] = 2
            c = {**confirmed(parallel), "transactionHash": "0x" + "f"*64,
                 "blockNumber": 28}
            result = ai.record(db, parallel, c)
            self.assertEqual(result["pop_stamp"], "PoP:PRIVI_TEST_CO:GRID/READINGS:000002")

    def test_rejects_ambiguous_floats_and_oversize_payload(self):
        packet = sample()
        packet["payload"]["ratio"] = 23.4
        with self.assertRaises(ValueError):
            ai.event_hashes(packet)
        packet["payload"] = {"huge": "a"*20000}
        with self.assertRaises(ValueError):
            ai.event_hashes(packet)

    def test_feature_confidence_requires_human_review_when_uncertain(self):
        packet = sample()
        packet["payload"] = {"foo": 1}
        packet["eventType"] = "unknown"
        result = ai.predict(packet)
        self.assertIsInstance(result["review_required"], bool)


if __name__ == "__main__":
    unittest.main()
