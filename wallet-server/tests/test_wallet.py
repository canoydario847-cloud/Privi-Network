from decimal import Decimal

import pytest
from starlette.testclient import TestClient

from privi_wallet.app import COOKIE, create_app
from privi_wallet.chain import Chain, to_units
from privi_wallet.config import PRIVI_TOKEN, Settings
from privi_wallet.vault import KeyVault, check_password, hash_password

H = {"X-Privi-Wallet": "1"}
ADDR = "0x1111111111111111111111111111111111111111"
TO = "0x2222222222222222222222222222222222222222"
KEY = "0x" + "ab" * 32


class FakeRpc:
    def __init__(self):
        self.eth = 10**18
        self.privi = 5000 * 10**18
        self.sent = []

    def __call__(self, method, params):
        if method == "eth_getBalance":
            return hex(self.eth)
        if method == "eth_call":
            return hex(self.privi if params[0]["to"] == PRIVI_TOKEN else 0)
        if method == "eth_gasPrice":
            return hex(10**7)
        if method == "eth_estimateGas":
            return hex(60000)
        if method == "eth_getTransactionCount":
            return "0x3"
        if method == "eth_sendRawTransaction":
            self.sent.append(params[0])
            return "0x" + "cd" * 32
        raise AssertionError(method)


def make(tmp_path, custody=True, **kw):
    s = Settings(db_path=str(tmp_path / "w.db"), custody=custody, master_key="m" * 40, secure_cookies=False, **kw)
    rpc = FakeRpc()
    signed = []

    def signer(pk, tx):
        signed.append((pk, tx))
        return "0xf86b"

    chain = Chain("http://x", 8453, rpc=rpc, signer=signer)
    app = create_app(s, chain=chain, new_key=lambda: (ADDR, KEY),
                     ledger_fetch=lambda: {"height": 4, "pending_entries": 2,
                                           "head": {"block_hash": "ff" * 64, "settlement": None,
                                                    "block": {"height": 4, "time": "2026-10-27T18:00:00+00:00",
                                                              "tree_size": 120}}})
    return TestClient(app), rpc, signed, app


def signup(c, email="a@b.co", pw="correct horse"):
    return c.post("/api/signup", json={"email": email, "password": pw}, headers=H)


def test_password_hash_roundtrip():
    h = hash_password("hunter2hunter2")
    assert check_password("hunter2hunter2", h) and not check_password("nope", h)


def test_vault_binds_key_to_owner():
    v = KeyVault("k" * 40)
    sealed = v.seal(KEY, 1, ADDR)
    assert v.open(sealed, 1, ADDR) == KEY
    assert KEY[2:] not in sealed
    with pytest.raises(Exception):
        v.open(sealed, 2, ADDR)       # moved to another account
    with pytest.raises(Exception):
        KeyVault("z" * 40).open(sealed, 1, ADDR)   # wrong master key


def test_to_units_rejects_dust():
    assert to_units(Decimal("1.5"), 6) == 1_500_000
    with pytest.raises(ValueError):
        to_units(Decimal("0.0000001"), 6)


def test_signup_login_and_csrf(tmp_path):
    c, *_ = make(tmp_path)
    assert c.post("/api/signup", json={"email": "a@b.co", "password": "correct horse"}).status_code == 400  # no header
    assert signup(c).status_code == 200 and COOKIE in c.cookies
    assert signup(c).status_code == 409
    assert c.get("/api/me").json()["email"] == "a@b.co"
    c.post("/api/logout", json={}, headers=H)
    assert c.get("/api/me").status_code == 401
    assert c.post("/api/login", json={"email": "a@b.co", "password": "wrong password"}, headers=H).status_code == 401
    assert c.post("/api/login", json={"email": "A@B.co", "password": "correct horse"}, headers=H).status_code == 200


def test_short_password_rejected(tmp_path):
    c, *_ = make(tmp_path)
    assert signup(c, pw="short").status_code == 400


def test_custody_off_blocks_wallet_creation(tmp_path):
    c, *_ = make(tmp_path, custody=False)
    signup(c)
    assert c.post("/api/wallets", json={}, headers=H).status_code == 403
    r = c.post("/api/wallets/watch", json={"address": TO, "label": "Mine"}, headers=H)
    assert r.status_code == 201
    w = c.get("/api/me").json()["wallets"][0]
    assert w["kind"] == "watch" and w["balances"]["PRIVI"] == "5000"


def test_create_send_and_export(tmp_path):
    c, rpc, signed, app = make(tmp_path)
    signup(c)
    assert c.post("/api/wallets", json={"label": "Main"}, headers=H).status_code == 201
    row = app.state.store.wallets(1)[0]
    assert row["sealed_key"] and KEY[2:] not in row["sealed_key"]

    url = f"/api/wallets/{ADDR}/send"
    body = {"asset": "PRIVI", "to": TO, "amount": "12.5", "password": "correct horse"}
    assert c.post(url, json={**body, "password": "bad password"}, headers=H).status_code == 401
    r = c.post(url, json=body, headers=H)
    assert r.status_code == 200, r.text
    pk, tx = signed[-1]
    assert pk == KEY and tx["to"] == PRIVI_TOKEN and tx["chainId"] == 8453 and tx["nonce"] == 3
    assert tx["data"].startswith("0xa9059cbb") and tx["data"].endswith(hex(to_units(Decimal("12.5"), 18))[2:].rjust(64, "0"))
    assert rpc.sent == ["0xf86b"]

    assert c.post(url, json={**body, "amount": "999999"}, headers=H).json()["error"].startswith("Over the 24-hour")
    assert "not enough PRIVI" in c.post(url, json={**body, "amount": "6000"}, headers=H).json()["error"]

    r = c.post(f"/api/wallets/{ADDR}/export", json={"password": "correct horse"}, headers=H)
    assert r.json()["private_key"] == KEY

    act = c.get("/api/activity").json()
    kinds = [e["kind"] for e in act["entries"]]
    assert {"account_created", "wallet_created", "sent", "key_exported", "password_check_failed"} <= set(kinds)
    assert act["check"]["valid"]


def test_needs_gas(tmp_path):
    c, rpc, *_ = make(tmp_path)
    signup(c)
    c.post("/api/wallets", json={}, headers=H)
    rpc.eth = 0
    r = c.post(f"/api/wallets/{ADDR}/send", json={"asset": "PRIVI", "to": TO, "amount": "1", "password": "correct horse"},
               headers=H)
    assert "network fee" in r.json()["error"]


def test_other_account_cannot_touch_wallet(tmp_path):
    c, *_ = make(tmp_path)
    signup(c)
    c.post("/api/wallets", json={}, headers=H)
    c.post("/api/logout", json={}, headers=H)
    signup(c, email="evil@x.co", pw="another password")
    r = c.post(f"/api/wallets/{ADDR}/export", json={"password": "another password"}, headers=H)
    assert r.status_code == 404


def test_activity_tamper_detected(tmp_path):
    c, _, _, app = make(tmp_path)
    signup(c)
    app.state.store._db.execute("UPDATE activity SET detail='{\"email\":\"x@y.co\"}' WHERE id=1")
    assert c.get("/api/activity").json()["check"]["valid"] is False


def test_pages_and_ledger(tmp_path):
    c, *_ = make(tmp_path)
    r = c.get("/")
    assert r.status_code == 200 and "Privi Wallet" in r.text and r.headers["x-frame-options"] == "DENY"
    ql = c.get("/api/quantum-ledger").json()
    assert ql["available"] and ql["status"]["blocks"] == 5 and ql["status"]["entries"] == 120


def test_real_key_generation_and_signing():
    pytest.importorskip("eth_account")
    from eth_account import Account
    from privi_wallet.chain import eth_account_signer, new_account
    address, key = new_account()
    assert Account.from_key(key).address == address
    raw = eth_account_signer(key, {"nonce": 0, "gasPrice": 10**7, "gas": 60000, "to": PRIVI_TOKEN, "value": 0,
                                   "data": "0xa9059cbb" + "00" * 64, "chainId": 8453})
    assert Account.recover_transaction(raw) == address
