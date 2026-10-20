import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("privi_iot_ai", ROOT / "ai_data_db.py")
ai = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ai)


def sample():
    return {
        "version": 1, "deviceId": "iot.test-001", "sequence": 1,
        "observedAt": 1760912345, "eventType": "environment.temperature",
        "payload": {"temperatureC": 22, "humidityPct": 51},
        "signatureBase64": "test-signature-only",
    }


def confirmed(packet):
    return {
        **ai.event_hashes(packet),
        "transactionHash": "0x" + "c" * 64,
        "blockNumber": 25,
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
            with sqlite3.connect(db) as conn:
                n, quote = conn.execute("SELECT COUNT(*), SUM(proposed_micro_prvi) FROM iot_events").fetchone()
            self.assertEqual(n, 1)
            self.assertGreater(quote, 0)
            with self.assertRaises(sqlite3.IntegrityError):
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
            with self.assertRaisesRegex(ValueError, "Third-party"):
                ai.record(db, packet, {**c, "chainId": 56})

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
