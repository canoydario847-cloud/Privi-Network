"""Privi Wallet web app: sign up, create or watch wallets on Base, send PRIVI / USDC / ETH, see Quantum Ledger status."""

from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
import urllib.request
from collections import defaultdict, deque
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route

from . import __version__
from .chain import ASSETS, Chain, ChainError, is_address, new_account
from .config import PRIVI_TOKEN, USDC_TOKEN, Settings
from .store import Store
from .vault import KeyVault, check_password, hash_password, new_token, token_hash

COOKIE = "privi_wallet_session"
CSRF_HEADER = "x-privi-wallet"
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,24}$")
STATIC = Path(__file__).parent / "static"
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "Content-Security-Policy": ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' "
                                "https://fonts.googleapis.com; font-src https://fonts.gstatic.com; img-src 'self' data:; "
                                "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"),
}


def err(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": message}, status, headers=SECURITY_HEADERS)


def ok(body: Any, status: int = 200) -> JSONResponse:
    return JSONResponse(body, status, headers=SECURITY_HEADERS)


class RateLimit:
    def __init__(self, per_minute: int):
        self.per_minute, self._hits, self._lock = per_minute, defaultdict(deque), threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= self.per_minute:
                return False
            q.append(now)
            return True


def create_app(settings: Settings | None = None, chain: Chain | None = None,
               new_key=new_account, ledger_fetch=None) -> Starlette:
    s = settings or Settings()
    store = Store(s.db_path)
    chain = chain or Chain(s.rpc_url, s.chain_id)
    vault = KeyVault(s.master_key) if s.custody_ready() else None
    auth_limit, money_limit = RateLimit(10), RateLimit(6)
    user_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
    ql_cache: dict[str, Any] = {"at": 0.0, "body": None}

    def client_ip(request: Request) -> str:
        fwd = request.headers.get("x-forwarded-for", "")
        return fwd.split(",")[0].strip() or (request.client.host if request.client else "?")

    def current_user(request: Request) -> int | None:
        tok = request.cookies.get(COOKIE)
        return store.session_user(token_hash(tok)) if tok else None

    async def body_json(request: Request) -> dict[str, Any] | None:
        # Every write must come from our own page: a custom header can't be sent cross-site without CORS.
        if request.headers.get(CSRF_HEADER) != "1":
            return None
        try:
            data = await request.json()
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    def start_session(user_id: int, body: dict) -> JSONResponse:
        tok = new_token()
        store.add_session(token_hash(tok), user_id)
        resp = ok(body)
        resp.set_cookie(COOKIE, tok, max_age=7 * 24 * 3600, httponly=True, secure=s.secure_cookies,
                        samesite="strict", path="/")
        return resp

    # ---------------------------------------------------------------- pages
    async def index(_: Request) -> Response:
        return HTMLResponse((STATIC / "index.html").read_text(encoding="utf-8"), headers=SECURITY_HEADERS)

    async def health(_: Request) -> JSONResponse:
        return ok({"ok": True, "version": __version__, "custody": s.custody_ready()})

    async def config(_: Request) -> JSONResponse:
        return ok({
            "custody": s.custody_ready(), "chain_id": s.chain_id, "explorer": s.explorer,
            "assets": {a: {"token": m["token"], "decimals": m["decimals"]} for a, m in ASSETS.items()},
            "privi_token": PRIVI_TOKEN, "usdc_token": USDC_TOKEN, "ledger_url": s.ledger_url,
            "limits_24h": {a: str(s.limit(a)) for a in ASSETS}, "max_wallets": s.max_wallets,
        })

    # ---------------------------------------------------------------- accounts
    async def signup(request: Request) -> JSONResponse:
        if not auth_limit.allow("auth:" + client_ip(request)):
            return err("Too many attempts. Wait a minute and try again.", 429)
        data = await body_json(request)
        if data is None:
            return err("bad request")
        email = str(data.get("email", "")).strip().lower()
        password = str(data.get("password", ""))
        if not EMAIL_RE.match(email):
            return err("Enter a valid email address.")
        if len(password) < 10 or len(password) > 200:
            return err("Use a password of at least 10 characters.")
        uid = store.create_user(email, await run_in_threadpool(hash_password, password))
        if uid is None:
            return err("An account with that email already exists. Sign in instead.", 409)
        store.log(uid, "account_created", {"email": email})
        return start_session(uid, {"ok": True, "email": email})

    async def login(request: Request) -> JSONResponse:
        if not auth_limit.allow("auth:" + client_ip(request)):
            return err("Too many attempts. Wait a minute and try again.", 429)
        data = await body_json(request)
        if data is None:
            return err("bad request")
        email = str(data.get("email", "")).strip().lower()
        row = store.user_by_email(email)
        good = row is not None and await run_in_threadpool(check_password, str(data.get("password", "")), row["password"])
        if not good:
            return err("Email or password is wrong.", 401)
        store.log(row["id"], "signed_in", {"ip": client_ip(request)})
        return start_session(row["id"], {"ok": True, "email": email})

    async def logout(request: Request) -> JSONResponse:
        tok = request.cookies.get(COOKIE)
        if tok:
            store.drop_session(token_hash(tok))
        resp = ok({"ok": True})
        resp.delete_cookie(COOKIE, path="/")
        return resp

    def wallet_view(w) -> dict[str, Any]:
        view = {"address": w["address"], "kind": w["kind"], "label": w["label"], "created_at": w["created_at"],
                "explorer": f"{s.explorer}/address/{w['address']}"}
        try:
            view["balances"] = chain.balances(w["address"])
        except (ChainError, ValueError) as e:
            view["balances"], view["balance_error"] = None, str(e)[:200]
        return view

    async def me(request: Request) -> JSONResponse:
        uid = current_user(request)
        if uid is None:
            return err("not signed in", 401)
        user = store.user(uid)
        wallets = [await run_in_threadpool(wallet_view, w) for w in store.wallets(uid)]
        return ok({"email": user["email"], "wallets": wallets, "custody": s.custody_ready()})

    # ---------------------------------------------------------------- wallets
    async def create_wallet(request: Request) -> JSONResponse:
        uid = current_user(request)
        if uid is None:
            return err("not signed in", 401)
        data = await body_json(request)
        if data is None:
            return err("bad request")
        if vault is None:
            return err("Privi-held wallets are not switched on yet. You can add a wallet you already own to watch it.", 403)
        if len(store.wallets(uid)) >= s.max_wallets:
            return err(f"You can have up to {s.max_wallets} wallets.")
        label = str(data.get("label") or "My Privi wallet").strip()[:40]
        address, key = await run_in_threadpool(new_key)
        store.add_wallet(uid, address, "privi", label, vault.seal(key, uid, address))
        del key
        store.log(uid, "wallet_created", {"address": address.lower(), "label": label})
        return ok({"address": address.lower(), "label": label}, 201)

    async def watch_wallet(request: Request) -> JSONResponse:
        uid = current_user(request)
        if uid is None:
            return err("not signed in", 401)
        data = await body_json(request)
        if data is None:
            return err("bad request")
        address = str(data.get("address", "")).strip()
        if not is_address(address):
            return err("That is not a valid 0x wallet address.")
        if len(store.wallets(uid)) >= s.max_wallets + 5:
            return err("Too many wallets on this account.")
        label = str(data.get("label") or "My wallet").strip()[:40]
        if not store.add_wallet(uid, address, "watch", label, None):
            return err("That wallet is already on a Privi account.", 409)
        store.log(uid, "wallet_watched", {"address": address.lower(), "label": label})
        return ok({"address": address.lower(), "label": label}, 201)

    async def require_owner_key(request: Request, data: dict, uid: int) -> tuple[Any, str | None]:
        """The custodial wallet row and its key, after re-checking the account password."""
        w = store.wallet(uid, request.path_params["address"])
        if w is None:
            return err("wallet not found", 404), None
        if w["kind"] != "privi" or not w["sealed_key"]:
            return err("This is a watch-only wallet. Send from the app that holds its key."), None
        if vault is None:
            return err("Privi-held wallets are switched off right now.", 503), None
        row = store.user(uid)
        if not await run_in_threadpool(check_password, str(data.get("password", "")), row["password"]):
            store.log(uid, "password_check_failed", {"address": w["address"]})
            return err("Password is wrong.", 401), None
        return w, vault.open(w["sealed_key"], uid, w["address"])

    async def send(request: Request) -> JSONResponse:
        uid = current_user(request)
        if uid is None:
            return err("not signed in", 401)
        if not money_limit.allow(f"send:{uid}"):
            return err("Too many sends. Wait a minute.", 429)
        data = await body_json(request)
        if data is None:
            return err("bad request")
        asset = str(data.get("asset", "")).upper()
        if asset not in ASSETS:
            return err("Choose PRIVI, USDC or ETH.")
        to = str(data.get("to", "")).strip()
        if not is_address(to):
            return err("That is not a valid 0x address.")
        try:
            amount = Decimal(str(data.get("amount", "")).strip())
        except InvalidOperation:
            return err("Enter an amount.")
        if not amount.is_finite() or amount <= 0:
            return err("Enter an amount above zero.")
        w, key = await require_owner_key(request, data, uid)
        if key is None:
            return w
        if to.lower() == w["address"]:
            return err("That is this wallet's own address.")
        async with user_locks[uid]:   # one send at a time per account, so the 24-hour limit can't be raced
            used = store.sent_last_24h(uid, asset)
            if used + amount > s.limit(asset):
                left = max(s.limit(asset) - used, Decimal(0))
                return err(f"Over the 24-hour limit for {asset}. You can still send {left} {asset} today.")
            try:
                tx = await run_in_threadpool(chain.build_send, w["address"], asset, to, amount)
            except ValueError as e:
                return err(str(e))
            except ChainError as e:
                return err(f"Base network error, nothing was sent: {str(e)[:160]}", 502)
            send_id = store.record_send(uid, w["address"], asset, amount, to)
            try:
                tx_hash = await run_in_threadpool(chain.send, key, tx)
            except ChainError as e:
                store.set_send_tx(send_id, None)
                return err(f"The network did not accept the transfer, nothing was sent: {str(e)[:160]}", 502)
            finally:
                del key
            store.set_send_tx(send_id, tx_hash)
        store.log(uid, "sent", {"from": w["address"], "to": to.lower(), "asset": asset, "amount": str(amount),
                                "tx_hash": tx_hash})
        return ok({"tx_hash": tx_hash, "explorer": f"{s.explorer}/tx/{tx_hash}"})

    async def export_key(request: Request) -> JSONResponse:
        uid = current_user(request)
        if uid is None:
            return err("not signed in", 401)
        if not money_limit.allow(f"export:{uid}"):
            return err("Too many attempts. Wait a minute.", 429)
        data = await body_json(request)
        if data is None:
            return err("bad request")
        w, key = await require_owner_key(request, data, uid)
        if key is None:
            return w
        store.log(uid, "key_exported", {"address": w["address"]})
        return ok({"address": w["address"], "private_key": key})

    # ---------------------------------------------------------------- activity and Quantum Ledger
    async def activity(request: Request) -> JSONResponse:
        uid = current_user(request)
        if uid is None:
            return err("not signed in", 401)
        return ok({"entries": store.activity(uid), "check": store.verify_activity(uid)})

    def fetch_ledger() -> Any:
        if ledger_fetch:
            return ledger_fetch()
        req = urllib.request.Request(s.ledger_url.rstrip("/") + "/quantum-ledger",
                                     headers={"User-Agent": f"privi-wallet/{__version__}"})
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read())

    def ledger_summary(st: dict[str, Any]) -> dict[str, Any]:
        head = st.get("head") or {}
        block = head.get("block") or {}
        return {"blocks": (st["height"] + 1) if isinstance(st.get("height"), int) else 0,
                "latest_height": block.get("height"), "latest_time": block.get("time"),
                "latest_hash": head.get("block_hash"), "entries": block.get("tree_size"),
                "pending_entries": st.get("pending_entries"), "settled": bool(head.get("settlement"))}

    async def quantum_ledger(_: Request) -> JSONResponse:
        if time.monotonic() - ql_cache["at"] > 30 or ql_cache["body"] is None:
            try:
                ql_cache["body"] = ledger_summary(await run_in_threadpool(fetch_ledger))
                ql_cache["at"] = time.monotonic()
            except Exception as e:  # the ledger may be asleep on Render's free tier
                return ok({"available": False, "error": str(e)[:160], "explorer": s.ledger_url + "/quantum-scan"})
        return ok({"available": True, "status": ql_cache["body"], "explorer": s.ledger_url + "/quantum-scan"})

    routes = [
        Route("/", index), Route("/health", health), Route("/api/config", config),
        Route("/api/signup", signup, methods=["POST"]), Route("/api/login", login, methods=["POST"]),
        Route("/api/logout", logout, methods=["POST"]), Route("/api/me", me),
        Route("/api/wallets", create_wallet, methods=["POST"]),
        Route("/api/wallets/watch", watch_wallet, methods=["POST"]),
        Route("/api/wallets/{address}/send", send, methods=["POST"]),
        Route("/api/wallets/{address}/export", export_key, methods=["POST"]),
        Route("/api/activity", activity), Route("/api/quantum-ledger", quantum_ledger),
    ]
    app = Starlette(routes=routes)
    app.state.store = store
    return app


def main() -> None:
    import uvicorn
    s = Settings()
    if s.custody and not s.custody_ready():
        raise SystemExit("WALLET_CUSTODY=1 needs WALLET_MASTER_KEY (32+ characters).")
    uvicorn.run(create_app(s), host="0.0.0.0", port=int(os.getenv("PORT", "8000")), proxy_headers=True,
                forwarded_allow_ips="*")
