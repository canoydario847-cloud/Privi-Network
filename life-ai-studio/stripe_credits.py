"""LIFE Stripe credit packs. No token sales. Checkout disabled unless explicitly configured."""
import os
from dataclasses import dataclass

import stripe
import store

CREDITS = 100
CENTS = 1000
LIVE_PRICE = "price_1UUf8qBQR6zcBQ9LRx6xHt0V"
TEST_PRICE = "price_1UUeYxBQR6zcBQ9LjHniLyKv"


@dataclass(frozen=True)
class Settings:
    key: str
    webhook_secret: str
    price_id: str
    live: bool


def settings(*, staging: bool, secure_cookie: bool, origin: str):
    """Fail closed, even when Stripe account is switched to live mode."""
    if os.getenv("LIFE_STRIPE_CHECKOUT_ENABLED") != "1":
        return None
    if staging or not secure_cookie or not origin.startswith("https://"):
        return None
    mode = os.getenv("LIFE_STRIPE_MODE", "")
    if mode not in ("test", "live"):
        return None
    if mode == "live" and os.getenv("LIFE_STRIPE_LIVE_APPROVED") != "1":
        return None
    key = os.getenv("LIFE_STRIPE_SECRET_KEY", "")
    webhook = os.getenv("LIFE_STRIPE_WEBHOOK_SECRET", "")
    expected_prefix = "sk_live_" if mode == "live" else "sk_test_"
    if not key.startswith(expected_prefix) or len(key) < 20:
        return None
    if not webhook.startswith("whsec_") or len(webhook) < 16:
        return None
    expected_price = LIVE_PRICE if mode == "live" else TEST_PRICE
    if os.getenv("LIFE_STRIPE_PRICE_ID") != expected_price:
        return None
    return Settings(key, webhook, expected_price, mode == "live")


def create_session(cfg: Settings, user_id: str, origin: str):
    """Stripe-hosted checkout; caller must persist the returned session before redirect."""
    return stripe.checkout.Session.create(
        api_key=cfg.key,
        mode="payment",
        line_items=[{"price": cfg.price_id, "quantity": 1}],
        client_reference_id=user_id,
        metadata={"life_user_id": user_id, "life_pack": "100"},
        success_url=origin + "/?checkout=success",
        cancel_url=origin + "/?checkout=cancel",
    )


def verified_paid_session(cfg: Settings, raw_body: bytes, header: str):
    """Verify Stripe's signature and independently re-fetch payment + line items.

    Returns None for irrelevant events, otherwise a paid Session or raises.
    No credits are issued by this function.
    """
    event = stripe.Webhook.construct_event(raw_body, header, cfg.webhook_secret)
    if bool(event["livemode"]) != cfg.live:
        raise ValueError("Stripe event mode mismatch")
    if event["type"] not in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
        return None
    session_id = event["data"]["object"]["id"]
    if not isinstance(session_id, str) or not session_id.startswith("cs_"):
        raise ValueError("Invalid checkout session")
    session = stripe.checkout.Session.retrieve(session_id, api_key=cfg.key)
    if (bool(session["livemode"]) != cfg.live or session["mode"] != "payment"
            or session["payment_status"] != "paid" or session["amount_total"] != CENTS
            or session["currency"] != "usd" or not session.get("payment_intent")
            or session.get("metadata", {}).get("life_pack") != str(CREDITS)):
        raise ValueError("Checkout payment verification failed")
    lines = stripe.checkout.Session.list_line_items(session_id, api_key=cfg.key, limit=10)
    items = lines["data"]
    if (lines.get("has_more") or len(items) != 1 or items[0]["quantity"] != 1
            or items[0]["price"]["id"] != cfg.price_id):
        raise ValueError("Checkout price verification failed")
    return session


def fulfill_paid_session(session):
    """Credit exactly once per session in the same durable SQLite transaction."""
    session_id = session["id"]
    user_id = session.get("client_reference_id")
    if not isinstance(user_id, str) or not user_id:
        raise ValueError("Missing member")
    if session.get("metadata", {}).get("life_user_id") != user_id:
        raise ValueError("Member mismatch")
    with store.transaction() as db:
        order = db.execute(
            "SELECT user_id,price_id,credits,amount_cents,fulfilled_at "
            "FROM stripe_checkout_sessions WHERE session_id=?", (session_id,)
        ).fetchone()
        if not order or order["user_id"] != user_id or order["credits"] != CREDITS or (
            order["price_id"] != session["expected_price_id"]
            or order["amount_cents"] != CENTS
        ):
            raise ValueError("Unknown or mismatched checkout order")
        if order["fulfilled_at"] is not None:
            return False
        if db.execute("UPDATE users SET credits=credits+? WHERE id=?",
                      (CREDITS, user_id)).rowcount != 1:
            raise ValueError("Unknown member")
        db.execute(
            "INSERT INTO ledger VALUES (?,?,?,?,?,?,?,?)",
            (store.uid("led"), user_id, "credit", "stripe_life_credits",
             CREDITS, 0, "stripe:" + session_id, store.now()))
        db.execute("UPDATE stripe_checkout_sessions SET fulfilled_at=? WHERE session_id=?",
                   (store.now(), session_id))
    return True
