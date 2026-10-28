"""Isolated LIFE Stripe credit tests; never call Stripe or create real payments."""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import store
import stripe_credits


class StripeCreditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original_db = store.DB
        store.DB = str(Path(self.tmp.name) / "life.sqlite3")
        store.init()
        self.user_id = "life_test"
        with store.transaction() as db:
            db.execute(
                "INSERT INTO users(id,email,pwdhash,member_since) VALUES(?,?,?,?)",
                (self.user_id, "test@example.invalid", "not-a-real-hash", store.now()))

    def tearDown(self):
        store.DB = self.original_db
        self.tmp.cleanup()

    def add_order(self, session_id="cs_test_order", price=None):
        with store.transaction() as db:
            db.execute(
                "INSERT INTO stripe_checkout_sessions "
                "(session_id,user_id,price_id,credits,amount_cents,created) "
                "VALUES (?,?,?,?,?,?)",
                (session_id, self.user_id, price or stripe_credits.TEST_PRICE,
                 100, 1000, store.now()))

    def paid_session(self, session_id="cs_test_order"):
        return {"id": session_id, "client_reference_id": self.user_id,
                "metadata": {"life_user_id": self.user_id, "life_pack": "100"},
                "livemode": False, "mode": "payment", "payment_status": "paid",
                "amount_total": 1000, "currency": "usd", "payment_intent": "pi_test"}

    def test_disabled_without_explicit_gate_and_live_approval(self):
        values = {"LIFE_STRIPE_CHECKOUT_ENABLED": "1", "LIFE_STRIPE_MODE": "live",
                  "LIFE_STRIPE_SECRET_KEY": "sk_live_" + "a" * 30,
                  "LIFE_STRIPE_WEBHOOK_SECRET": "whsec_" + "b" * 30,
                  "LIFE_STRIPE_PRICE_ID": stripe_credits.LIVE_PRICE}
        with patch.dict(os.environ, values, clear=True):
            self.assertIsNone(stripe_credits.settings(
                staging=False, secure_cookie=True, origin="https://life.example"))
            os.environ["LIFE_STRIPE_LIVE_APPROVED"] = "1"
            self.assertIsNotNone(stripe_credits.settings(
                staging=False, secure_cookie=True, origin="https://life.example"))
            self.assertIsNone(stripe_credits.settings(
                staging=True, secure_cookie=True, origin="https://life.example"))
            self.assertIsNone(stripe_credits.settings(
                staging=False, secure_cookie=False, origin="https://life.example"))
            self.assertIsNone(stripe_credits.settings(
                staging=False, secure_cookie=True, origin="http://life.example"))
            os.environ["LIFE_STRIPE_PRICE_ID"] = stripe_credits.TEST_PRICE
            self.assertIsNone(stripe_credits.settings(
                staging=False, secure_cookie=True, origin="https://life.example"))
            os.environ["LIFE_STRIPE_CHECKOUT_ENABLED"] = "0"
            self.assertIsNone(stripe_credits.settings(
                staging=False, secure_cookie=True, origin="https://life.example"))

    def test_checkout_order_credits_once_after_verified_payment(self):
        self.add_order()
        session = self.paid_session()
        self.assertTrue(stripe_credits.fulfill_paid_session(session, stripe_credits.TEST_PRICE))
        self.assertFalse(stripe_credits.fulfill_paid_session(session, stripe_credits.TEST_PRICE))
        with store.transaction() as db:
            self.assertEqual(db.execute(
                "SELECT credits FROM users WHERE id=?", (self.user_id,)).fetchone()[0], 100)
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM ledger WHERE user_id=?", (self.user_id,)).fetchone()[0], 1)

    def test_rejects_unknown_order_and_mismatched_member_or_price(self):
        with self.assertRaises(ValueError):
            stripe_credits.fulfill_paid_session(self.paid_session(), stripe_credits.TEST_PRICE)
        self.add_order()
        wrong = self.paid_session()
        wrong["metadata"]["life_user_id"] = "another_user"
        with self.assertRaises(ValueError):
            stripe_credits.fulfill_paid_session(wrong, stripe_credits.TEST_PRICE)
        with self.assertRaises(ValueError):
            stripe_credits.fulfill_paid_session(self.paid_session(), stripe_credits.LIVE_PRICE)
        self.assertEqual(store.get_user(self.user_id)["credits"], 0)

    def test_stripe_retrieval_checks_amount_price_mode_and_paid_status(self):
        cfg = stripe_credits.Settings("sk_test_" + "x" * 25, "whsec_" + "y" * 25,
                                      stripe_credits.TEST_PRICE, False)
        event = {"livemode": False, "type": "checkout.session.completed",
                 "data": {"object": {"id": "cs_test_order"}}}
        lines = {"has_more": False, "data": [
            {"quantity": 1, "price": {"id": stripe_credits.TEST_PRICE}}]}
        with patch.object(stripe_credits.stripe.Webhook, "construct_event", return_value=event), \
             patch.object(stripe_credits.stripe.checkout.Session, "retrieve",
                          return_value=self.paid_session()) as retrieve, \
             patch.object(stripe_credits.stripe.checkout.Session, "list_line_items",
                          return_value=lines) as items:
            self.assertEqual(stripe_credits.verified_paid_session(
                cfg, b"{}", "signed")["id"], "cs_test_order")
            retrieve.return_value = {**self.paid_session(), "amount_total": 999}
            with self.assertRaises(ValueError):
                stripe_credits.verified_paid_session(cfg, b"{}", "signed")
            retrieve.return_value = {**self.paid_session(), "payment_status": "unpaid"}
            with self.assertRaises(ValueError):
                stripe_credits.verified_paid_session(cfg, b"{}", "signed")
            retrieve.return_value = self.paid_session()
            items.return_value = {"has_more": False, "data": [
                {"quantity": 1, "price": {"id": "price_other"}}]}
            with self.assertRaises(ValueError):
                stripe_credits.verified_paid_session(cfg, b"{}", "signed")

    def test_wrong_stripe_event_mode_is_rejected(self):
        cfg = stripe_credits.Settings("sk_test_" + "x" * 25, "whsec_" + "y" * 25,
                                      stripe_credits.TEST_PRICE, False)
        with patch.object(stripe_credits.stripe.Webhook, "construct_event",
                          return_value={"livemode": True, "type": "other"}):
            with self.assertRaises(ValueError):
                stripe_credits.verified_paid_session(cfg, b"{}", "signed")


if __name__ == "__main__":
    unittest.main()
