"""Privi Rooms: live, hash-chained conversations between two organizations' agents, optionally paid per message.

One organization opens a room (optionally naming the only counterparty or issuing a join code). Both sides
connect over WebSocket (/rooms/<id>/ws, first frame {"type":"auth","key":...}). Every message is numbered,
chained to the one before it and delivered live to the other side.

Paid rooms: the owner sets price_per_message_usdc and a payee. Each message from the *guest* is charged against a
human-signed Privi Mandate (budget, per-payment cap, payee list, live approval policy and kill switch all apply),
so a runaway agent cannot overspend and every charge is in both parties' logs. Privi enforces and records the
charge; moving the money is between the two parties (for example by settling the mandate's spends over x402).

Closing a room seals the transcript: its hash is signed (Ed25519 + ML-DSA-87), anchored on the Privi chain and
written into both organizations' tamper-evident logs. Anyone holding the transcript can verify it with room_verify.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

import anyio
from starlette.requests import Request
from starlette.websockets import WebSocket, WebSocketDisconnect

from .live import LiveService, MAX_FRAME, _iso, _now, jresp
from .mandate import MandateError, fmt, norm_payee, to_micro
from .store import GENESIS, check_id

FREE_MONTHLY = int(os.getenv("ROOM_FREE_MONTHLY", "200"))
MAX_BODY_CHARS = 8000
MAX_ROOMS_OPEN = {"free": 3, "pro": 100, "enterprise": 1000}

SCHEMA = """
CREATE TABLE IF NOT EXISTS rooms (
    room_id      TEXT PRIMARY KEY,
    owner_org    TEXT NOT NULL,
    guest_org    TEXT,
    allowed_org  TEXT,
    join_hash    TEXT,
    title        TEXT NOT NULL,
    price        INTEGER NOT NULL DEFAULT 0,
    payee        TEXT NOT NULL DEFAULT '',
    max_messages INTEGER NOT NULL,
    status       TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    expires_at   TEXT NOT NULL,
    closed_at    TEXT,
    closed_by    TEXT,
    msg_count    INTEGER NOT NULL DEFAULT 0,
    head_hash    TEXT NOT NULL,
    seal         TEXT
);
CREATE TABLE IF NOT EXISTS room_messages (
    room_id    TEXT NOT NULL,
    seq        INTEGER NOT NULL,
    org_id     TEXT NOT NULL,
    kind       TEXT NOT NULL,
    body       TEXT NOT NULL,
    body_hash  TEXT NOT NULL,
    prev_hash  TEXT NOT NULL,
    entry_hash TEXT NOT NULL,
    at         TEXT NOT NULL,
    charged    INTEGER NOT NULL DEFAULT 0,
    spend_id   TEXT,
    PRIMARY KEY (room_id, seq)
);
"""


class RoomError(Exception):
    pass


def msg_hash(room_id: str, seq: int, org_id: str, kind: str, at: str, body_hash: str, prev: str) -> str:
    return hashlib.sha256(f"{room_id}\n{seq}\n{org_id}\n{kind}\n{at}\n{body_hash}\n{prev}".encode()).hexdigest()


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def recompute_chain(room_id: str, messages: list[dict]) -> dict:
    """Verify a transcript: sequence, per-message hashes and the chain. Pure function; used by room_verify."""
    prev = GENESIS
    for i, m in enumerate(messages, 1):
        try:
            body_hash = hashlib.sha256(m["body"].encode()).hexdigest()
            h = msg_hash(room_id, m["seq"], m["org_id"], m["kind"], m["at"], body_hash, prev)
        except (KeyError, AttributeError, TypeError):
            return {"valid": False, "broken_at": i, "reason": "malformed message"}
        if m["seq"] != i or m.get("prev_hash") != prev or m.get("entry_hash") != h or m.get("body_hash") != body_hash:
            return {"valid": False, "broken_at": i, "reason": "message does not match its hash or position"}
        prev = h
    return {"valid": True, "head_hash": prev, "message_count": len(messages)}


class Rooms:
    def __init__(self, live: LiveService, anchor_hash: Callable[[str, str], Awaitable[dict]] | None = None):
        self.live, self.ledger, self.plans, self.mandates = live, live.ledger, live.plans, live.mandates
        self.db, self.lock = live.db, live.lock
        self.anchor_hash = anchor_hash
        self._conns: dict[str, dict[int, tuple[str, Callable]]] = {}
        self._n = 0
        with self.lock:
            self.db.executescript(SCHEMA)
            self.db.commit()

    # ---------------- lifecycle ----------------

    def _row(self, room_id: str) -> dict | None:
        with self.lock:
            r = self.db.execute("SELECT * FROM rooms WHERE room_id=?", ((room_id or "").strip(),)).fetchone()
        return dict(r) if r else None

    def open(self, org: dict, title: str, counterparty_org_id: str | None = None, price_per_message_usdc: str | None = None,
             payee: str | None = None, max_messages: int = 500, hours: int = 24) -> dict:
        title = " ".join((title or "").split())[:120]
        if not title:
            raise RoomError("title is required")
        if not 2 <= max_messages <= 10000:
            raise RoomError("max_messages must be 2-10000")
        if not 1 <= hours <= 168:
            raise RoomError("hours must be 1-168")
        price = to_micro(price_per_message_usdc) if price_per_message_usdc not in (None, "") else 0
        pay = ""
        if price:
            if not payee:
                raise RoomError("payee (a 0x address or domain) is required when price_per_message_usdc is set")
            pay = norm_payee(payee)
        if counterparty_org_id and not self.ledger.org_exists(counterparty_org_id):
            raise RoomError("counterparty_org_id is not a Privi organization")
        plan = self.live.plan_of(org["org_id"])
        with self.lock:
            n = self.db.execute("SELECT COUNT(*) FROM rooms WHERE owner_org=? AND status='open'", (org["org_id"],)).fetchone()[0]
        if n >= MAX_ROOMS_OPEN[plan]:
            raise RoomError(f"the {plan} plan allows {MAX_ROOMS_OPEN[plan]} open rooms; close one or call ledger_upgrade_pro")
        rid = "rm_" + secrets.token_hex(6)
        code = None if counterparty_org_id else secrets.token_urlsafe(9)
        now = _now()
        with self.lock:
            self.db.execute(
                "INSERT INTO rooms (room_id, owner_org, allowed_org, join_hash, title, price, payee, max_messages, status, "
                "created_at, expires_at, head_hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (rid, org["org_id"], counterparty_org_id, hashlib.sha256(code.encode()).hexdigest() if code else None, title,
                 price, pay, max_messages, "open", _iso(now), _iso(now + timedelta(hours=hours)), GENESIS))
            self.db.commit()
        out = self.public(rid)
        if code:
            out["join_code"] = code
            out["note"] = "Give the join_code to the other organization's agent privately; it is shown only once."
        self.live.emit(f"org:{org['org_id']}", "room.opened", {"room_id": rid, "title": title})
        self.live._log(org["org_id"], f"room-{rid}", "other", f"Room {rid} opened: {title}", rid)
        return out

    def public(self, room_id: str) -> dict:
        r = self._row(room_id)
        if not r:
            raise RoomError("no such room")
        base = self.live.public_url
        ws = base.replace("https://", "wss://").replace("http://", "ws://")
        status = "expired" if r["status"] == "open" and r["expires_at"] < _iso(_now()) else r["status"]
        seal = json.loads(r["seal"]) if r["seal"] else None
        return {"room_id": r["room_id"], "title": r["title"], "status": status, "owner_org": r["owner_org"],
                "guest_org": r["guest_org"], "invited_org": r["allowed_org"],
                "price_per_message_usdc": fmt(r["price"]) if r["price"] else None, "payee": r["payee"] or None,
                "message_count": r["msg_count"], "max_messages": r["max_messages"], "head_hash": r["head_hash"],
                "created_at": r["created_at"], "expires_at": r["expires_at"], "closed_at": r["closed_at"],
                "ws_url": f"{ws}/rooms/{r['room_id']}/ws", "seal": seal,
                "protocol": 'connect, send {"type":"auth","key":"<org api key>","join_code":"<if invited by code>",'
                            '"mandate_id":"<if the room is paid and you are the guest>"}, then {"type":"msg","body":"..."}'}

    def list_for(self, org_id: str) -> list[dict]:
        with self.lock:
            ids = [r["room_id"] for r in self.db.execute(
                "SELECT room_id FROM rooms WHERE owner_org=? OR guest_org=? ORDER BY created_at DESC LIMIT 100",
                (org_id, org_id)).fetchall()]
        return [{k: self.public(i)[k] for k in ("room_id", "title", "status", "owner_org", "guest_org", "message_count",
                                                "price_per_message_usdc", "expires_at")} for i in ids]

    def authorize(self, room_id: str, org: dict, join_code: str | None) -> tuple[dict, str]:
        """Returns (room, role). Joining as guest is atomic and happens only here."""
        r = self._row(room_id)
        if not r:
            raise RoomError("no such room")
        if org["org_id"] == r["owner_org"]:
            return r, "owner"
        if r["guest_org"] == org["org_id"]:
            return r, "guest"
        if r["guest_org"]:
            raise RoomError("this room already has two parties")
        ok = (r["allowed_org"] == org["org_id"]) or bool(
            r["join_hash"] and join_code and hashlib.sha256(join_code.encode()).hexdigest() == r["join_hash"])
        if not ok:
            raise RoomError("you are not invited to this room (send join_code, or ask the owner to name your organization)")
        with self.lock:
            n = self.db.execute("UPDATE rooms SET guest_org=? WHERE room_id=? AND guest_org IS NULL",
                                (org["org_id"], room_id)).rowcount
            self.db.commit()
        if not n:
            raise RoomError("this room already has two parties")
        self.live.emit(f"org:{r['owner_org']}", "room.joined", {"room_id": room_id, "guest_org": org["org_id"]})
        self.live._log(org["org_id"], f"room-{room_id}", "other", f"Joined room {room_id}: {r['title']}", room_id)
        return {**r, "guest_org": org["org_id"]}, "guest"

    # ---------------- messages ----------------

    def post(self, room_id: str, org: dict, body: str, kind: str = "text", mandate_id: str | None = None) -> dict:
        r = self._row(room_id)
        if not r:
            raise RoomError("no such room")
        if org["org_id"] not in (r["owner_org"], r["guest_org"]):
            raise RoomError("you are not in this room")
        if r["status"] != "open" or r["expires_at"] < _iso(_now()):
            raise RoomError("this room is closed")
        if kind not in ("text", "json", "offer", "accept", "decline", "payment", "data"):
            raise RoomError("kind must be one of: text, json, offer, accept, decline, payment, data")
        body = body if isinstance(body, str) else json.dumps(body, separators=(",", ":"))
        if not body.strip() or len(body) > MAX_BODY_CHARS:
            raise RoomError(f"body must be 1-{MAX_BODY_CHARS} characters")
        if r["msg_count"] >= r["max_messages"]:
            raise RoomError("this room reached its message limit; close it and open a new one")
        k = self.live.is_killed(org["org_id"], f"room-{room_id}")
        if k:
            raise RoomError("kill switch is on for your organization" + (f": {k['reason']}" if k["reason"] else ""))
        ok, q = self.live.quota(org["org_id"], "room", FREE_MONTHLY)
        if not ok:
            raise RoomError(f"free plan limit reached ({FREE_MONTHLY} room messages this month); call ledger_upgrade_pro")
        charged, spend_id = 0, None
        if r["price"] and org["org_id"] != r["owner_org"]:
            if not mandate_id:
                raise RoomError(f"this room charges {fmt(r['price'])} USDC per message from you; send mandate_id "
                                "(a signed Privi Mandate that allows this payee)")
            blocked, _ = self.live.spend_gate(org, mandate_id, fmt(r["price"]), r["payee"], None)
            if blocked:
                raise RoomError(blocked["error"])
            try:
                sp = self.mandates.spend(mandate_id.strip(), org["org_id"], fmt(r["price"]), r["payee"], f"{room_id} message")
            except (MandateError, ValueError) as e:
                raise RoomError(f"payment refused: {e}")
            charged, spend_id = r["price"], sp["spend_id"]
        at = _iso(_now())
        body_hash = hashlib.sha256(body.encode()).hexdigest()
        with self.lock:
            cur = self.db.execute("SELECT msg_count, head_hash, status FROM rooms WHERE room_id=?", (room_id,)).fetchone()
            if cur["status"] != "open":
                raise RoomError("this room is closed")
            seq = cur["msg_count"] + 1
            h = msg_hash(room_id, seq, org["org_id"], kind, at, body_hash, cur["head_hash"])
            self.db.execute("INSERT INTO room_messages (room_id, seq, org_id, kind, body, body_hash, prev_hash, entry_hash, at, "
                            "charged, spend_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            (room_id, seq, org["org_id"], kind, body, body_hash, cur["head_hash"], h, at, charged, spend_id))
            self.db.execute("UPDATE rooms SET msg_count=?, head_hash=? WHERE room_id=?", (seq, h, room_id))
            self.db.commit()
        self.live.bump(org["org_id"], "room")
        return {"room_id": room_id, "seq": seq, "org_id": org["org_id"], "kind": kind, "body": body, "body_hash": body_hash,
                "prev_hash": cur["head_hash"], "entry_hash": h, "at": at, "charged_usdc": fmt(charged) if charged else None,
                "spend_id": spend_id}

    def messages(self, room_id: str, since: int = 0) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT * FROM room_messages WHERE room_id=? AND seq>? ORDER BY seq LIMIT 1000",
                                   (room_id, since)).fetchall()
        return [{**{k: r[k] for k in ("room_id", "seq", "org_id", "kind", "body", "body_hash", "prev_hash", "entry_hash", "at")},
                 "charged_usdc": fmt(r["charged"]) if r["charged"] else None, "spend_id": r["spend_id"]} for r in rows]

    def transcript(self, room_id: str, org: dict) -> dict:
        r = self._row(room_id)
        if not r or org["org_id"] not in (r["owner_org"], r["guest_org"]):
            raise RoomError("no such room for this organization")
        msgs = self.messages(room_id)
        return {"room": self.public(room_id), "messages": msgs, "verification": recompute_chain(room_id, msgs)}

    # ---------------- sealing ----------------

    async def close(self, room_id: str, org: dict | None, reason: str = "closed by a participant") -> dict:
        r = self._row(room_id)
        if not r:
            raise RoomError("no such room")
        if org is not None and org["org_id"] not in (r["owner_org"], r["guest_org"]):
            raise RoomError("you are not in this room")
        if r["status"] == "closed":
            return self.public(room_id)
        msgs = await anyio.to_thread.run_sync(self.messages, room_id)
        chain = recompute_chain(room_id, msgs)
        seal_body = {"type": "PriviRoomSeal", "version": "1", "room_id": room_id, "title": r["title"],
                     "owner_org": r["owner_org"], "guest_org": r["guest_org"],
                     "price_per_message_usdc": fmt(r["price"]) if r["price"] else None, "payee": r["payee"] or None,
                     "message_count": len(msgs), "head_hash": chain.get("head_hash", GENESIS),
                     "first_message_at": msgs[0]["at"] if msgs else None, "closed_at": _iso(_now()),
                     "issuer_url": self.live.public_url, "key_id": self.live.passports.key_id}
        h = hashlib.sha256(canonical(seal_body).encode()).hexdigest()
        seal = {"body": seal_body, "seal_hash": h, "signature": self.live.passports.sign(h),
                "ml_dsa_87_signature": self.live.fortress.pq_sign(h)}
        self.live.fortress.cosign(h, "room")
        seal["anchor"] = (await self.anchor_hash(h, f"privi room {room_id}")) if self.anchor_hash else {"anchored": False}
        with self.lock:
            n = self.db.execute("UPDATE rooms SET status='closed', closed_at=?, closed_by=?, seal=? WHERE room_id=? AND status='open'",
                                (seal_body["closed_at"], (org or {}).get("org_id", "system"), json.dumps(seal), room_id)).rowcount
            self.db.commit()
        if not n:
            return self.public(room_id)
        for oid in filter(None, (r["owner_org"], r["guest_org"])):
            self.live._log(oid, f"room-{room_id}", "other",
                           f"Room {room_id} sealed: {len(msgs)} messages, transcript hash {h[:16]}…", room_id, "success",
                           {"seal_hash": h, "head_hash": seal_body["head_hash"], "anchored": seal["anchor"].get("anchored"),
                            "reason": reason[:120]})
            self.live.emit(f"org:{oid}", "room.closed", {"room_id": room_id, "seal_hash": h, "message_count": len(msgs)})
        await self._broadcast(room_id, {"type": "closed", "room_id": room_id, "seal_hash": h, "message_count": len(msgs),
                                        "anchored": seal["anchor"].get("anchored")})
        return self.public(room_id)

    def verify(self, room_id: str, messages: list[dict] | None) -> dict:
        r = self._row(room_id)
        if not r:
            raise RoomError("no such room")
        out: dict[str, Any] = {"room_id": room_id, "status": r["status"], "sealed": bool(r["seal"])}
        if not r["seal"]:
            out["note"] = "the room is not sealed yet; seals appear when a participant closes it"
            return out
        seal = json.loads(r["seal"])
        out["seal_hash_ok"] = hashlib.sha256(canonical(seal["body"]).encode()).hexdigest() == seal["seal_hash"]
        out["signature_valid"] = self.live.passports.signature_ok(seal["seal_hash"], seal["signature"])
        out["anchor"] = seal.get("anchor")
        out["seal"] = seal["body"]
        if messages is not None:
            chain = recompute_chain(room_id, messages)
            out["transcript"] = {**chain, "matches_seal": chain.get("valid") and chain.get("head_hash") == seal["body"]["head_hash"]
                                 and chain.get("message_count") == seal["body"]["message_count"]}
        else:
            out["transcript"] = "pass the transcript's messages to check them against this seal"
        return out

    # ---------------- WebSocket ----------------

    async def _broadcast(self, room_id: str, frame: dict, skip: int | None = None) -> None:
        for tok, (_, send) in list(self._conns.get(room_id, {}).items()):
            if tok == skip:
                continue
            try:
                await send(frame)
            except Exception:
                pass

    async def ws_room(self, ws: WebSocket) -> None:
        room_id = ws.path_params["room_id"]
        if not self._row(room_id):
            await ws.close(code=4404)
            return
        await ws.accept()
        send_lock = anyio.Lock()
        org: dict | None = None
        role = None
        token = id(ws)
        mandate_id: str | None = None

        async def send(obj: dict) -> None:
            async with send_lock:
                await ws.send_text(json.dumps(obj, separators=(",", ":")))

        try:
            while True:
                raw = await ws.receive_text()
                if len(raw) > MAX_FRAME:
                    await send({"type": "error", "error": "frame too large"})
                    continue
                try:
                    m = json.loads(raw)
                    t = m["type"]
                except (ValueError, KeyError, TypeError):
                    await send({"type": "error", "error": 'send JSON frames: {"type":"auth",...} then {"type":"msg","body":"..."}'})
                    continue
                if t == "ping":
                    await send({"type": "pong"})
                    continue
                if t == "auth":
                    o = self.ledger.org_for_key(str(m.get("key", "")))
                    if not o:
                        await anyio.sleep(0.5)
                        await send({"type": "auth", "ok": False, "error": "invalid API key"})
                        continue
                    try:
                        _, role = await anyio.to_thread.run_sync(self.authorize, room_id, o, m.get("join_code"))
                    except RoomError as e:
                        await send({"type": "auth", "ok": False, "error": str(e)})
                        continue
                    org, mandate_id = o, (str(m["mandate_id"]) if m.get("mandate_id") else None)
                    self._conns.setdefault(room_id, {})[token] = (o["org_id"], send)
                    pub = self.public(room_id)
                    await send({"type": "joined", "ok": True, "role": role, "room": {k: pub[k] for k in (
                        "room_id", "title", "status", "owner_org", "guest_org", "price_per_message_usdc", "payee",
                        "message_count", "expires_at")}})
                    await self._broadcast(room_id, {"type": "presence", "org_id": o["org_id"], "role": role, "online": True})
                    continue
                if not org:
                    await send({"type": "error", "error": "authenticate first"})
                    continue
                if t == "msg":
                    try:
                        rec = await anyio.to_thread.run_sync(self.post, room_id, org, m.get("body", ""), str(m.get("kind", "text")),
                                                             str(m["mandate_id"]) if m.get("mandate_id") else mandate_id)
                    except RoomError as e:
                        await send({"type": "error", "error": str(e), "ref": m.get("ref")})
                        continue
                    await send({"type": "msg", **rec, "ref": m.get("ref")})              # the sender's copy carries its ref
                    await self._broadcast(room_id, {"type": "msg", **rec}, skip=token)
                elif t == "history":
                    msgs = await anyio.to_thread.run_sync(self.messages, room_id, int(m.get("since") or 0))
                    await send({"type": "history", "messages": msgs})
                elif t == "close":
                    pub = await self.close(room_id, org)
                    await send({"type": "close", "ok": True, "status": pub["status"]})
                else:
                    await send({"type": "error", "error": f"unknown frame type '{str(t)[:30]}'"})
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            self._conns.get(room_id, {}).pop(token, None)
            if org:
                await self._broadcast(room_id, {"type": "presence", "org_id": org["org_id"], "role": role, "online": False})

    async def http_room(self, request: Request):
        try:
            return jresp(self.public(request.path_params["room_id"]), cors=True)
        except RoomError as e:
            return jresp({"error": str(e)}, 404)

    def http_routes(self):
        return [("/rooms/{room_id}", ["GET"], self.http_room)]

    def ws_routes(self):
        return [("/rooms/{room_id}/ws", self.ws_room)]
