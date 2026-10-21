"""Privi Live: real-time streams, human approvals and a kill switch.

Everything here is delivered over three transports that share one event log:
  * Server-sent events   GET /live/events
  * WebSocket            /live/ws   (first frame {"type":"auth","key":...}; keys never go in URLs)
  * Plain polling        GET /live/trust/recent

Channels
  org:<org_id>   private to that organization (needs its API key): ledger entries, approvals, kill switch
  trust          public trust-change feed: passports issued / revoked / re-scored, KYA wallet bindings,
                 mandate activations and revocations, anchored transparency-log heads
  mandate:<id>   status of one spending mandate (activated / revoked)

Free and anonymous subscribers get the public channels delayed by LIVE_FREE_DELAY_S (default 300 s);
Pro and enterprise organizations get them in real time. An organization's own channel is always real time.

Human approvals: an agent asks for approval, a human signs an approve/deny message with their wallet
(EIP-191, the same proof Mandates use). The organization's API key can only *cancel* a request, never
approve it, so an agent cannot approve itself.

Kill switch: an organization can stop an agent (or all agents) from spending under mandates and from
using its gateways at once. Recording to the audit log is deliberately never blocked.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Callable

import anyio
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.websockets import WebSocket, WebSocketDisconnect

from .kya import checksum, norm_address, personal_hash, recover_address
from .mandate import MandateError, fmt, norm_payee, to_micro
from .store import check_id

FREE_DELAY_S = float(os.getenv("LIVE_FREE_DELAY_S", "300"))
MAX_CONN = {"anon": int(os.getenv("LIVE_MAX_ANON", "100")), "free": int(os.getenv("LIVE_MAX_FREE", "5")),
            "paid": int(os.getenv("LIVE_MAX_PAID", "100"))}
MAX_FRAME = 64 * 1024
HEARTBEAT_S = 15.0
EVENT_KEEP_S = 7 * 24 * 3600
TRUST_MIN_DELTA = int(os.getenv("LIVE_TRUST_MIN_DELTA", "10"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS live_events (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    channel TEXT NOT NULL,
    type    TEXT NOT NULL,
    ts      REAL NOT NULL,
    data    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_live_events_ch ON live_events (channel, id);
CREATE TABLE IF NOT EXISTS live_controls (
    org_id TEXT NOT NULL, stream_id TEXT NOT NULL, killed_at TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '',
    by_who TEXT NOT NULL DEFAULT '', PRIMARY KEY (org_id, stream_id)
);
CREATE TABLE IF NOT EXISTS live_policies (
    org_id TEXT NOT NULL, stream_id TEXT NOT NULL, approve_over INTEGER NOT NULL, set_at TEXT NOT NULL,
    PRIMARY KEY (org_id, stream_id)
);
CREATE TABLE IF NOT EXISTS approvals (
    approval_id TEXT PRIMARY KEY,
    org_id      TEXT NOT NULL,
    org_name    TEXT NOT NULL,
    stream_id   TEXT NOT NULL,
    mandate_id  TEXT,
    action      TEXT NOT NULL,
    amount      INTEGER NOT NULL DEFAULT 0,
    payee       TEXT NOT NULL DEFAULT '',
    reference   TEXT NOT NULL DEFAULT '',
    reason      TEXT NOT NULL DEFAULT '',
    approver    TEXT NOT NULL,
    status      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL,
    decided_at  TEXT,
    decided_by  TEXT,
    signature   TEXT,
    use_until   TEXT,
    used_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_approvals_org ON approvals (org_id, created_at);
CREATE TABLE IF NOT EXISTS trust_state (
    passport_id TEXT PRIMARY KEY, state TEXT NOT NULL, score INTEGER NOT NULL, grade TEXT NOT NULL, at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS live_usage (
    org_id TEXT NOT NULL, month TEXT NOT NULL, kind TEXT NOT NULL, n INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (org_id, month, kind)
);
"""


class LiveError(Exception):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.isoformat(timespec="seconds")


def _month() -> str:
    return _now().strftime("%Y-%m")


def jresp(data: Any, status: int = 200, cors: bool = False) -> JSONResponse:
    h = {"Cache-Control": "no-store"}
    if cors:
        h["Access-Control-Allow-Origin"] = "*"
    return JSONResponse(data, status_code=status, headers=h)


def bearer(headers) -> str:
    auth = (headers or {}).get("authorization", "")
    return auth[7:].strip() if auth.lower().startswith("bearer ") else ""


# ---------------------------------------------------------------- event bus

class Bus:
    """Append-only event log in SQLite plus a thread-safe wake-up for async subscribers."""

    def __init__(self, db: sqlite3.Connection, lock: threading.Lock):
        self._db, self._lock = db, lock
        self._waiters: set[tuple[asyncio.AbstractEventLoop, asyncio.Event]] = set()
        self._wl = threading.Lock()
        self._n = 0
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.commit()

    def publish(self, channel: str, type_: str, data: dict) -> int:
        body = json.dumps(data, separators=(",", ":"), default=str)
        with self._lock:
            cur = self._db.execute("INSERT INTO live_events (channel, type, ts, data) VALUES (?,?,?,?)",
                                   (channel, type_, time.time(), body))
            eid = cur.lastrowid
            self._n += 1
            if self._n % 500 == 0:
                self._db.execute("DELETE FROM live_events WHERE ts < ?", (time.time() - EVENT_KEEP_S,))
            self._db.commit()
        self._wake()
        return eid

    def _wake(self) -> None:
        with self._wl:
            items = list(self._waiters)
        for loop, ev in items:
            try:
                loop.call_soon_threadsafe(ev.set)
            except RuntimeError:   # loop already closed
                pass

    def new_waiter(self) -> asyncio.Event:
        ev = asyncio.Event()
        with self._wl:
            self._waiters.add((asyncio.get_running_loop(), ev))
        return ev

    def drop_waiter(self, ev: asyncio.Event) -> None:
        with self._wl:
            self._waiters = {w for w in self._waiters if w[1] is not ev}

    @staticmethod
    def _row(r) -> dict:
        return {"id": r["id"], "channel": r["channel"], "type": r["type"],
                "at": _iso(datetime.fromtimestamp(r["ts"], timezone.utc)), "data": json.loads(r["data"])}

    def since(self, channel: str, after_id: int, delay_s: float = 0.0, limit: int = 200) -> list[dict]:
        sql, args = "SELECT * FROM live_events WHERE channel=? AND id>?", [channel, after_id]
        if delay_s:
            sql += " AND ts<=?"
            args.append(time.time() - delay_s)
        with self._lock:
            rows = self._db.execute(sql + " ORDER BY id LIMIT ?", (*args, limit)).fetchall()
        return [self._row(r) for r in rows]

    def max_id(self) -> int:
        with self._lock:
            return self._db.execute("SELECT COALESCE(MAX(id),0) FROM live_events").fetchone()[0]

    def tail_cursor(self, channel: str, n: int) -> int:
        """Cursor that makes the next read return the last n events of a channel."""
        with self._lock:
            r = self._db.execute("SELECT id FROM live_events WHERE channel=? ORDER BY id DESC LIMIT 1 OFFSET ?",
                                 (channel, max(0, n - 1))).fetchone()
        return (r["id"] - 1) if r else 0

    def recent(self, channel: str, limit: int, delay_s: float = 0.0) -> list[dict]:
        sql, args = "SELECT * FROM live_events WHERE channel=?", [channel]
        if delay_s:
            sql += " AND ts<=?"
            args.append(time.time() - delay_s)
        with self._lock:
            rows = self._db.execute(sql + " ORDER BY id DESC LIMIT ?", (*args, limit)).fetchall()
        return [self._row(r) for r in reversed(rows)]


def make_filter(f: dict | None) -> Callable[[dict], bool]:
    f = f or {}
    addr = None
    if f.get("address"):
        try:
            addr = norm_address(str(f["address"]))
        except ValueError:
            addr = str(f["address"]).lower()
    pid = (f.get("passport_id") or "").strip() or None
    types = [t.strip() for t in (f.get("types") or []) if t and t.strip()]

    def ok(ev: dict) -> bool:
        d = ev["data"]
        if types and not any(ev["type"] == t or ev["type"].startswith(t.rstrip("*")) for t in types):
            return False
        if pid and d.get("passport_id") != pid:
            return False
        if addr:
            mine = {str(a).lower() for a in (d.get("addresses") or [])} | ({str(d["address"]).lower()} if d.get("address") else set())
            if addr not in mine:
                return False
        return True
    return ok


# ---------------------------------------------------------------- the service

class LiveService:
    def __init__(self, ledger, plans, passports, kya, mandates, fortress, public_url: str):
        self.ledger, self.plans, self.passports, self.kya, self.mandates = ledger, plans, passports, kya, mandates
        self.fortress, self.public_url = fortress, public_url.rstrip("/")
        self.db, self.lock = ledger._db, ledger._lock
        self.bus = Bus(self.db, self.lock)
        self._conns: dict[str, int] = {}
        self._cl = threading.Lock()
        self._org_subs: dict[str, int] = {}

    # ---- identity and plan --------------------------------------------

    def plan_of(self, org_id: str) -> str:
        return self.plans.status(org_id)["plan"]

    def is_paid(self, org: dict | None) -> bool:
        return bool(org) and self.plan_of(org["org_id"]) in ("pro", "enterprise")

    def public_delay(self, org: dict | None) -> float:
        return 0.0 if self.is_paid(org) else FREE_DELAY_S

    # ---- usage metering (gateway calls, room messages) ------------------

    def usage(self, org_id: str, kind: str) -> int:
        with self.lock:
            r = self.db.execute("SELECT n FROM live_usage WHERE org_id=? AND month=? AND kind=?",
                                (org_id, _month(), kind)).fetchone()
        return r["n"] if r else 0

    def bump(self, org_id: str, kind: str, n: int = 1) -> int:
        with self.lock:
            self.db.execute("INSERT INTO live_usage (org_id, month, kind, n) VALUES (?,?,?,?) "
                            "ON CONFLICT(org_id, month, kind) DO UPDATE SET n = n + ?", (org_id, _month(), kind, n, n))
            r = self.db.execute("SELECT n FROM live_usage WHERE org_id=? AND month=? AND kind=?",
                                (org_id, _month(), kind)).fetchone()
            self.db.commit()
        return r["n"]

    def quota(self, org_id: str, kind: str, free_limit: int) -> tuple[bool, dict]:
        paid = self.plan_of(org_id) in ("pro", "enterprise")
        used = self.usage(org_id, kind)
        return (paid or used < free_limit), {"kind": kind, "used_this_month": used,
                                              "free_monthly_limit": None if paid else free_limit,
                                              "plan": "paid" if paid else "free"}

    # ---- event helpers --------------------------------------------------

    def emit(self, channel: str, type_: str, data: dict) -> int:
        return self.bus.publish(channel, type_, data)

    def emit_trust(self, type_: str, data: dict, org_id: str | None = None, extra_channels: tuple[str, ...] = ()) -> None:
        self.bus.publish("trust", type_, data)
        for ch in extra_channels:
            self.bus.publish(ch, type_, data)
        if org_id:
            self.bus.publish(f"org:{org_id}", type_, data)

    def on_record(self, org_id: str, entry: dict) -> None:
        """Ledger hook: live tail of an organization's audit entries (only while someone is listening)."""
        if self._org_subs.get(org_id, 0) <= 0:
            return
        self.bus.publish(f"org:{org_id}", "entry.recorded", {
            "stream_id": entry["stream_id"], "seq": entry["seq"], "actor": entry["actor"],
            "action_type": entry["action_type"], "summary": entry["summary"][:300], "outcome": entry["outcome"],
            "entry_hash": entry["entry_hash"], "recorded_at": str(entry["recorded_at"])})

    def _log(self, org_id: str, stream: str, action_type: str, summary: str, resource: str = "",
             outcome: str = "success", details: dict | None = None) -> None:
        try:
            self.ledger.record(org_id, stream, "Privi Live", action_type, summary, resource, outcome, details or {})
        except ValueError:
            pass

    # ---- kill switch ----------------------------------------------------

    def kill(self, org_id: str, stream_id: str, reason: str = "", by: str = "organization") -> dict:
        sid = "*" if stream_id in ("*", "") else check_id(stream_id, "stream_id")
        now = _iso(_now())
        with self.lock:
            self.db.execute("INSERT INTO live_controls (org_id, stream_id, killed_at, reason, by_who) VALUES (?,?,?,?,?) "
                            "ON CONFLICT(org_id, stream_id) DO UPDATE SET killed_at=excluded.killed_at, "
                            "reason=excluded.reason, by_who=excluded.by_who", (org_id, sid, now, reason[:300], by[:80]))
            self.db.commit()
        d = {"stream_id": sid, "killed_at": now, "reason": reason[:300], "by": by}
        self.emit(f"org:{org_id}", "agent.killed", d)
        self._log(org_id, "privi-live", "decision",
                  f"KILL SWITCH: {'all agents' if sid == '*' else 'agent ' + sid} stopped. {reason[:200]}".strip(),
                  sid, "blocked", {"by": by})
        return {"killed": True, **d}

    def resume(self, org_id: str, stream_id: str, by: str = "organization") -> dict:
        sid = "*" if stream_id in ("*", "") else check_id(stream_id, "stream_id")
        with self.lock:
            n = self.db.execute("DELETE FROM live_controls WHERE org_id=? AND stream_id=?", (org_id, sid)).rowcount
            self.db.commit()
        if n:
            self.emit(f"org:{org_id}", "agent.resumed", {"stream_id": sid, "by": by})
            self._log(org_id, "privi-live", "decision", f"Kill switch released for {'all agents' if sid == '*' else sid}",
                      sid, "success", {"by": by})
        return {"resumed": bool(n), "stream_id": sid}

    def is_killed(self, org_id: str, stream_id: str) -> dict | None:
        with self.lock:
            r = self.db.execute("SELECT * FROM live_controls WHERE org_id=? AND stream_id IN (?, '*') "
                                "ORDER BY stream_id = '*' LIMIT 1", (org_id, stream_id)).fetchone()
        return dict(r) if r else None

    def killed_list(self, org_id: str) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.db.execute(
                "SELECT stream_id, killed_at, reason, by_who FROM live_controls WHERE org_id=? ORDER BY killed_at DESC",
                (org_id,)).fetchall()]

    # ---- approval policy -------------------------------------------------

    def policy_set(self, org_id: str, stream_id: str, approve_over_usdc: str | None) -> dict:
        sid = "*" if stream_id in ("*", "") else check_id(stream_id, "stream_id")
        with self.lock:
            if approve_over_usdc is None or str(approve_over_usdc).strip() == "":
                self.db.execute("DELETE FROM live_policies WHERE org_id=? AND stream_id=?", (org_id, sid))
                self.db.commit()
                return {"stream_id": sid, "approve_over_usdc": None, "note": "policy removed"}
            micro = to_micro(approve_over_usdc)
            self.db.execute("INSERT INTO live_policies (org_id, stream_id, approve_over, set_at) VALUES (?,?,?,?) "
                            "ON CONFLICT(org_id, stream_id) DO UPDATE SET approve_over=excluded.approve_over, "
                            "set_at=excluded.set_at", (org_id, sid, micro, _iso(_now())))
            self.db.commit()
        return {"stream_id": sid, "approve_over_usdc": fmt(micro),
                "note": "payments over this amount now need a live human approval (the mandate's principal signs)"}

    def policy_get(self, org_id: str, stream_id: str) -> int | None:
        with self.lock:
            r = self.db.execute("SELECT approve_over FROM live_policies WHERE org_id=? AND stream_id IN (?, '*') "
                                "ORDER BY stream_id = '*' LIMIT 1", (org_id, stream_id)).fetchone()
        return r["approve_over"] if r else None

    def policies(self, org_id: str) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT stream_id, approve_over FROM live_policies WHERE org_id=?", (org_id,)).fetchall()
        return [{"stream_id": r["stream_id"], "approve_over_usdc": fmt(r["approve_over"])} for r in rows]

    # ---- human approvals -------------------------------------------------

    def _approval_row(self, aid: str) -> dict | None:
        with self.lock:
            r = self.db.execute("SELECT * FROM approvals WHERE approval_id=?", ((aid or "").strip(),)).fetchone()
        return dict(r) if r else None

    @staticmethod
    def approval_message(a: dict, decision: str) -> str:
        what = a["action"]
        money = f"\nAmount: {fmt(a['amount'])} USDC to {a['payee']}" if a["amount"] else ""
        ref = f"\nReference: {a['reference']}" if a["reference"] else ""
        mdt = f"\nUnder mandate: {a['mandate_id']}" if a["mandate_id"] else ""
        why = f"\nWhy: {a['reason']}" if a["reason"] else ""
        return (f"Privi Approval {a['approval_id']}\n{decision.upper()} this request from {a['org_name']}'s agent "
                f"'{a['stream_id']}': {what}{money}{ref}{mdt}{why}\nRequest expires {a['expires_at']} UTC.")

    def approval_request(self, org: dict, stream_id: str, action: str, *, amount: str | None = None,
                         payee: str = "", reference: str = "", reason: str = "", approver_wallet: str | None = None,
                         mandate_id: str | None = None, ttl_s: int = 900) -> dict:
        sid = check_id(stream_id, "stream_id")
        action = " ".join((action or "").split())[:300]
        if not action:
            raise LiveError("action is required: say what you want approved")
        micro = to_micro(amount) if amount not in (None, "") else 0
        pay = norm_payee(payee) if payee else ""
        if mandate_id:
            m = self.mandates._row(mandate_id)
            if not m or m["org_id"] != org["org_id"]:
                raise LiveError("no such mandate for this organization")
            approver = m["principal"]            # the human who signed the mandate decides
        elif approver_wallet:
            approver = norm_address(approver_wallet)
        else:
            raise LiveError("name who decides: approver_wallet (a 0x address) or mandate_id (its principal decides)")
        if not 60 <= ttl_s <= 86400:
            raise LiveError("ttl_s must be between 60 and 86400 seconds")
        aid = "apr_" + secrets.token_hex(8)
        now = _now()
        row = {"approval_id": aid, "org_id": org["org_id"], "org_name": org["name"], "stream_id": sid,
               "mandate_id": mandate_id, "action": action, "amount": micro, "payee": pay,
               "reference": reference[:200], "reason": " ".join((reason or "").split())[:300], "approver": approver,
               "status": "pending", "created_at": _iso(now), "expires_at": _iso(now + timedelta(seconds=ttl_s))}
        with self.lock:
            self.db.execute(f"INSERT INTO approvals ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})",
                            tuple(row.values()))
            self.db.commit()
        pub = self.approval_public(aid)
        self.emit(f"org:{org['org_id']}", "approval.requested", {k: pub[k] for k in (
            "approval_id", "stream_id", "action", "amount_usdc", "payee", "mandate_id", "approver", "expires_at", "approve_url")})
        self._log(org["org_id"], sid, "approval", f"Approval {aid} requested from {checksum(approver)}: {action}", aid,
                  "pending", {"amount_usdc": fmt(micro), "payee": pay, "mandate_id": mandate_id})
        return pub

    def _expire(self, a: dict) -> dict:
        if a["status"] == "pending" and a["expires_at"] < _iso(_now()):
            with self.lock:
                self.db.execute("UPDATE approvals SET status='expired' WHERE approval_id=? AND status='pending'",
                                (a["approval_id"],))
                self.db.commit()
            a = {**a, "status": "expired"}
            self.emit(f"org:{a['org_id']}", "approval.expired", {"approval_id": a["approval_id"]})
        return a

    def approval_public(self, aid: str) -> dict:
        a = self._approval_row(aid)
        if not a:
            raise LiveError("no such approval")
        a = self._expire(a)
        return {"approval_id": a["approval_id"], "status": a["status"], "org_id": a["org_id"], "stream_id": a["stream_id"],
                "action": a["action"], "amount_usdc": fmt(a["amount"]), "payee": a["payee"] or None,
                "reference": a["reference"] or None, "reason": a["reason"] or None, "mandate_id": a["mandate_id"],
                "approver": checksum(a["approver"]), "created_at": a["created_at"], "expires_at": a["expires_at"],
                "decided_at": a["decided_at"], "decided_by": checksum(a["decided_by"]) if a["decided_by"] else None,
                "signature": a["signature"], "use_until": a["use_until"], "used_at": a["used_at"],
                "messages": {"approve": self.approval_message(a, "approve"), "deny": self.approval_message(a, "deny")},
                "approve_url": f"{self.public_url}/approve/{a['approval_id']}"}

    def approval_decide(self, aid: str, decision: str, signature: str) -> dict:
        if decision not in ("approve", "deny"):
            raise LiveError("decision must be 'approve' or 'deny'")
        a = self._approval_row(aid)
        if not a:
            raise LiveError("no such approval")
        a = self._expire(a)
        if a["status"] != "pending":
            raise LiveError(f"this request is already {a['status']}")
        try:
            signer = recover_address(personal_hash(self.approval_message(a, decision)),
                                     bytes.fromhex(signature.strip().removeprefix("0x")))
        except ValueError as e:
            raise LiveError(f"bad signature: {e}")
        if signer != a["approver"]:
            raise LiveError(f"signed by {checksum(signer)}, but only {checksum(a['approver'])} can decide this")
        status = "approved" if decision == "approve" else "denied"
        now = _now()
        use_until = _iso(now + timedelta(minutes=10)) if status == "approved" else None
        with self.lock:
            n = self.db.execute("UPDATE approvals SET status=?, decided_at=?, decided_by=?, signature=?, use_until=? "
                                "WHERE approval_id=? AND status='pending'",
                                (status, _iso(now), signer, signature.strip(), use_until, aid)).rowcount
            self.db.commit()
        if not n:
            raise LiveError("this request was just decided by someone else")
        pub = self.approval_public(aid)
        self.emit(f"org:{a['org_id']}", f"approval.{status}", {
            "approval_id": aid, "stream_id": a["stream_id"], "decided_by": pub["decided_by"], "use_until": use_until})
        self._log(a["org_id"], a["stream_id"], "approval",
                  f"Human {checksum(signer)} {status} request {aid}: {a['action']}", aid,
                  "success" if status == "approved" else "blocked", {"signature": signature.strip()[:140]})
        return pub

    def approval_cancel(self, org_id: str, aid: str) -> dict:
        a = self._approval_row(aid)
        if not a or a["org_id"] != org_id:
            raise LiveError("no such approval for this organization")
        if a["status"] not in ("pending", "approved"):
            return self.approval_public(aid)
        with self.lock:
            self.db.execute("UPDATE approvals SET status='cancelled' WHERE approval_id=? AND status IN ('pending','approved')",
                            (aid,))
            self.db.commit()
        self.emit(f"org:{org_id}", "approval.cancelled", {"approval_id": aid})
        return self.approval_public(aid)

    def approvals_for(self, org_id: str, status: str | None = None) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT approval_id FROM approvals WHERE org_id=? ORDER BY created_at DESC LIMIT 100",
                                   (org_id,)).fetchall()
        out = [self.approval_public(r["approval_id"]) for r in rows]
        return [a for a in out if not status or a["status"] == status]

    def approval_consume(self, aid: str, org_id: str, mandate_id: str | None, amount_micro: int, payee: str) -> None:
        """Atomically spend an approved request exactly once; it must match the payment it was granted for."""
        a = self._approval_row(aid)
        if not a or a["org_id"] != org_id:
            raise LiveError("no such approval for this organization")
        if a["status"] != "approved":
            raise LiveError(f"approval {aid} is {a['status']}, not approved")
        if a["use_until"] and a["use_until"] < _iso(_now()):
            raise LiveError(f"approval {aid} was not used in time (valid until {a['use_until']}); ask again")
        if (a["mandate_id"] or None) != (mandate_id or None) or a["amount"] != amount_micro or (a["payee"] or "") != (payee or ""):
            raise LiveError("this approval was granted for a different payment (mandate, amount and payee must match)")
        with self.lock:
            n = self.db.execute("UPDATE approvals SET used_at=? WHERE approval_id=? AND used_at IS NULL",
                                (_iso(_now()), aid)).rowcount
            self.db.commit()
        if not n:
            raise LiveError(f"approval {aid} was already used")

    def approval_release(self, aid: str) -> None:
        with self.lock:
            self.db.execute("UPDATE approvals SET used_at=NULL WHERE approval_id=?", (aid,))
            self.db.commit()

    def spend_gate(self, org: dict, mandate_id: str, amount: str, payee: str, approval_id: str | None):
        """Run before mandates.spend. Returns (blocked_response | None, consumed_approval_id | None)."""
        m = self.mandates._row(mandate_id)
        if not m or m["org_id"] != org["org_id"]:
            return None, None            # let mandates.spend report it
        k = self.is_killed(org["org_id"], m["stream_id"])
        if k:
            return {"allow": False, "killed": True, "error": f"kill switch is on for '{k['stream_id']}'"
                    + (f": {k['reason']}" if k["reason"] else "") + ". Spending is stopped until the organization resumes it."}, None
        thr = self.policy_get(org["org_id"], m["stream_id"])
        micro, pay = to_micro(amount), norm_payee(payee)
        if thr is None or micro <= thr:
            return None, None
        if approval_id:
            try:
                self.approval_consume(approval_id.strip(), org["org_id"], mandate_id, micro, pay)
            except LiveError as e:
                return {"allow": False, "approval_required": True, "error": str(e)}, None
            return None, approval_id.strip()
        pub = self.approval_request(org, m["stream_id"], f"Pay {fmt(micro)} USDC to {pay}", amount=amount, payee=payee,
                                    mandate_id=mandate_id, reason=f"over the {fmt(thr)} USDC live-approval threshold")
        return {"allow": False, "approval_required": True, "approval_id": pub["approval_id"],
                "approve_url": pub["approve_url"], "expires_at": pub["expires_at"],
                "error": f"{fmt(micro)} USDC is over this agent's {fmt(thr)} USDC live-approval threshold. A human must "
                         f"approve: send them {pub['approve_url']} then call mandate_spend again with approval_id={pub['approval_id']} "
                         f"(or approval_wait to block until they decide)."}, None

    # ---- connections ------------------------------------------------------

    def _slot(self, org: dict | None) -> tuple[str, int]:
        if not org:
            return "anon", MAX_CONN["anon"]
        return org["org_id"], MAX_CONN["paid"] if self.is_paid(org) else MAX_CONN["free"]

    def acquire(self, org: dict | None) -> str | None:
        key, cap = self._slot(org)
        with self._cl:
            if self._conns.get(key, 0) >= cap:
                return None
            self._conns[key] = self._conns.get(key, 0) + 1
        return key

    def release(self, key: str | None) -> None:
        if key:
            with self._cl:
                self._conns[key] = max(0, self._conns.get(key, 1) - 1)

    def resolve_channels(self, requested: list[str], org: dict | None) -> tuple[list[tuple[str, float]], str | None]:
        specs: list[tuple[str, float]] = []
        delay = self.public_delay(org)
        for c in requested:
            c = c.strip()
            if c in ("org", "org:*") or (org and c == f"org:{org['org_id']}"):
                if not org:
                    return [], "the 'org' channel needs your organization API key"
                specs.append((f"org:{org['org_id']}", 0.0))
            elif c.startswith("org:"):
                return [], "you can only subscribe to your own organization's channel"
            elif c == "trust":
                specs.append(("trust", delay))
            elif c.startswith("mandate:") and 8 < len(c) < 40 and c[8:].replace("_", "").isalnum():
                specs.append((c, delay))
            elif c == "scan" or (c.startswith("scan:mcp_") and len(c) == 21 and c[9:].isalnum()):
                specs.append((c, delay))
            else:
                return [], f"unknown channel '{c[:40]}' (use: org, trust, scan, scan:<server_id>, mandate:<id>)"
        if not specs:
            return [], "no channels requested"
        return list(dict.fromkeys(specs)), None

    def cursors_for(self, specs, since: int | None, replay: int) -> dict[str, int]:
        cur = {}
        base = self.bus.max_id()
        for ch, _ in specs:
            if since is not None:
                cur[ch] = max(0, since)
            elif replay > 0:
                cur[ch] = self.bus.tail_cursor(ch, min(replay, 200))
            else:
                cur[ch] = base
        return cur

    async def pump(self, specs: list[tuple[str, float]], cursors: dict[str, int],
                   filt: Callable[[dict], bool]) -> AsyncIterator[dict | None]:
        """Yield matching events as they happen; yield None every HEARTBEAT_S when idle."""
        ev = self.bus.new_waiter()
        delayed = any(d for _, d in specs)
        idle_since = time.monotonic()
        try:
            while True:
                ev.clear()
                got = False
                for ch, delay in specs:
                    rows = await anyio.to_thread.run_sync(self.bus.since, ch, cursors[ch], delay)
                    for r in rows:
                        cursors[ch] = r["id"]
                        got = True
                        if filt(r):
                            idle_since = time.monotonic()
                            yield r
                if got:
                    continue
                wait = min(HEARTBEAT_S, 2.0) if delayed else HEARTBEAT_S
                try:
                    await asyncio.wait_for(ev.wait(), wait)
                except asyncio.TimeoutError:
                    pass
                if time.monotonic() - idle_since >= HEARTBEAT_S:
                    idle_since = time.monotonic()
                    yield None
        finally:
            self.bus.drop_waiter(ev)

    def _watch_org(self, specs, delta: int) -> None:
        for ch, _ in specs:
            if ch.startswith("org:"):
                oid = ch[4:]
                self._org_subs[oid] = max(0, self._org_subs.get(oid, 0) + delta)

    # ---- HTTP: server-sent events -----------------------------------------

    def _org_from(self, request: Request) -> tuple[dict | None, Response | None]:
        key = bearer(request.headers)
        if not key:
            return None, None
        org = self.ledger.org_for_key(key)
        if not org:
            return None, jresp({"error": "invalid API key"}, 401)
        return org, None

    async def sse(self, request: Request) -> Response:
        org, err = self._org_from(request)
        if err:
            return err
        q = request.query_params
        default = "org,trust" if org else "trust"
        specs, e = self.resolve_channels([c for c in q.get("channels", default).split(",") if c], org)
        if e:
            return jresp({"error": e}, 401 if "API key" in e else 400)
        try:
            lei = request.headers.get("last-event-id")
            since = int(lei) if lei and lei.isdigit() else (int(q["since"]) if q.get("since", "").isdigit() else None)
            replay = int(q.get("replay", "0") or 0)
        except ValueError:
            return jresp({"error": "since and replay must be integers"}, 400)
        filt = make_filter({"address": q.get("address"), "passport_id": q.get("passport_id"),
                            "types": [t for t in q.get("types", "").split(",") if t]})
        slot = self.acquire(org)
        if not slot:
            return jresp({"error": "too many open streams for this account"}, 429)
        cursors = self.cursors_for(specs, since, replay)

        async def gen():
            self._watch_org(specs, +1)
            try:
                yield "retry: 3000\n: connected\n\n"
                async for ev in self.pump(specs, cursors, filt):
                    if ev is None:
                        yield ": keep-alive\n\n"
                    else:
                        yield f"id: {ev['id']}\nevent: {ev['type']}\ndata: {json.dumps(ev, separators=(',', ':'))}\n\n"
            finally:
                self._watch_org(specs, -1)
                self.release(slot)
        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no", "Access-Control-Allow-Origin": "*",
                                          "X-Privi-Delay-Seconds": str(int(max(d for _, d in specs)))})

    async def trust_recent(self, request: Request) -> Response:
        org, err = self._org_from(request)
        if err:
            return err
        q = request.query_params
        try:
            limit = max(1, min(int(q.get("limit", "50")), 200))
        except ValueError:
            limit = 50
        filt = make_filter({"address": q.get("address"), "passport_id": q.get("passport_id")})
        delay = self.public_delay(org)
        evs = [e for e in self.bus.recent("trust", 200, delay) if filt(e)][-limit:]
        return jresp({"channel": "trust", "delay_seconds": int(delay), "events": evs,
                      "realtime": "Pro/enterprise API keys get this feed in real time: GET /live/events or WS /live/ws"},
                     cors=True)

    # ---- HTTP: kill switch, state, approvals ---------------------------------

    async def http_kill(self, request: Request) -> Response:
        org, err = self._org_from(request)
        if err or not org:
            return err or jresp({"error": "an organization API key is required"}, 401)
        try:
            b = await request.json()
            return jresp(self.kill(org["org_id"], str(b.get("stream_id", "*")), str(b.get("reason", "")), "organization (api)"))
        except (ValueError, AttributeError) as e:
            return jresp({"error": str(e) or "send JSON like {\"stream_id\": \"*\", \"reason\": \"...\"}"}, 400)

    async def http_resume(self, request: Request) -> Response:
        org, err = self._org_from(request)
        if err or not org:
            return err or jresp({"error": "an organization API key is required"}, 401)
        try:
            b = await request.json()
            return jresp(self.resume(org["org_id"], str(b.get("stream_id", "*")), "organization (api)"))
        except (ValueError, AttributeError) as e:
            return jresp({"error": str(e)}, 400)

    async def http_state(self, request: Request) -> Response:
        org, err = self._org_from(request)
        if err or not org:
            return err or jresp({"error": "an organization API key is required"}, 401)
        return jresp({"org_id": org["org_id"], "name": org["name"], "plan": self.plan_of(org["org_id"]),
                      "killed": self.killed_list(org["org_id"]), "policies": self.policies(org["org_id"]),
                      "pending_approvals": self.approvals_for(org["org_id"], "pending")})

    async def http_approval(self, request: Request) -> Response:
        try:
            return jresp(self.approval_public(request.path_params["approval_id"]), cors=True)
        except LiveError as e:
            return jresp({"error": str(e)}, 404)

    async def http_approval_decide(self, request: Request) -> Response:
        try:
            b = await request.json()
            return jresp(self.approval_decide(request.path_params["approval_id"], str(b.get("decision", "")),
                                              str(b.get("signature", ""))))
        except (LiveError, ValueError, AttributeError) as e:
            return jresp({"error": str(e)}, 400)

    async def page_approve(self, _: Request) -> Response:
        return Response((Path(__file__).parent / "approve.html").read_text(encoding="utf-8"),
                        media_type="text/html; charset=utf-8")

    async def page_live(self, _: Request) -> Response:
        return Response((Path(__file__).parent / "live.html").read_text(encoding="utf-8"),
                        media_type="text/html; charset=utf-8")

    # ---- WebSocket ------------------------------------------------------------

    async def ws_live(self, ws: WebSocket) -> None:
        await ws.accept()
        org: dict | None = None
        slot: str | None = None
        send_lock = anyio.Lock()
        watching: list[tuple[str, float]] = []

        async def send(obj: dict) -> None:
            async with send_lock:
                await ws.send_text(json.dumps(obj, separators=(",", ":")))

        async def run_pump(specs, cursors, filt):
            async for ev in self.pump(specs, cursors, filt):
                await send({"type": "event", "event": ev["type"], "id": ev["id"], "channel": ev["channel"],
                            "at": ev["at"], "data": ev["data"]} if ev else {"type": "heartbeat", "at": _iso(_now())})

        sub_scope: anyio.CancelScope | None = None
        try:
            async with anyio.create_task_group() as tg:
                async def start_sub(specs, cursors, filt):
                    nonlocal sub_scope
                    if sub_scope:
                        sub_scope.cancel()
                    scope = anyio.CancelScope()
                    sub_scope = scope

                    async def runner():
                        with scope:
                            try:
                                await run_pump(specs, cursors, filt)
                            except (WebSocketDisconnect, RuntimeError):
                                tg.cancel_scope.cancel()
                    tg.start_soon(runner)

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
                            await send({"type": "error", "error": "send JSON frames like {\"type\":\"subscribe\",\"channels\":[\"trust\"]}"})
                            continue
                        if t == "ping":
                            await send({"type": "pong", "at": _iso(_now())})
                        elif t == "auth":
                            o = self.ledger.org_for_key(str(m.get("key", "")))
                            if not o:
                                await anyio.sleep(0.5)
                                await send({"type": "auth", "ok": False, "error": "invalid API key"})
                                continue
                            org = o
                            await send({"type": "auth", "ok": True, "org_id": o["org_id"], "plan": self.plan_of(o["org_id"])})
                        elif t == "subscribe":
                            specs, e = self.resolve_channels([str(c) for c in (m.get("channels") or ["trust"])], org)
                            if e:
                                await send({"type": "error", "error": e})
                                continue
                            new_slot = slot or self.acquire(org)
                            if not new_slot:
                                await send({"type": "error", "error": "too many open streams for this account"})
                                continue
                            slot = new_slot
                            if watching:
                                self._watch_org(watching, -1)
                            self._watch_org(specs, +1)
                            watching = specs
                            try:
                                since = int(m["since"]) if m.get("since") is not None else None
                                replay = int(m.get("replay") or 0)
                            except (ValueError, TypeError):
                                await send({"type": "error", "error": "since and replay must be integers"})
                                continue
                            cursors = self.cursors_for(specs, since, replay)
                            await send({"type": "subscribed", "channels": [c for c, _ in specs],
                                        "delay_seconds": int(max(d for _, d in specs)), "from_id": min(cursors.values())})
                            await start_sub(specs, cursors, make_filter(m.get("filter")))
                        elif t == "unsubscribe":
                            if sub_scope:
                                sub_scope.cancel()
                            await send({"type": "unsubscribed"})
                        elif t in ("kill", "resume"):
                            if not org:
                                await send({"type": "error", "error": "authenticate first"})
                                continue
                            try:
                                if t == "kill":
                                    res = self.kill(org["org_id"], str(m.get("stream_id", "*")), str(m.get("reason", "")), "organization (ws)")
                                else:
                                    res = self.resume(org["org_id"], str(m.get("stream_id", "*")), "organization (ws)")
                                await send({"type": t, "ok": True, **res})
                            except ValueError as e:
                                await send({"type": "error", "error": str(e)})
                        else:
                            await send({"type": "error", "error": f"unknown frame type '{str(t)[:30]}'"})
                except (WebSocketDisconnect, RuntimeError):
                    pass
                finally:
                    tg.cancel_scope.cancel()
        finally:
            if watching:
                self._watch_org(watching, -1)
            self.release(slot)

    # ---- route table --------------------------------------------------------------

    def http_routes(self) -> list[tuple[str, list[str], Callable]]:
        return [
            ("/live", ["GET"], self.page_live),
            ("/live/events", ["GET"], self.sse),
            ("/live/trust/recent", ["GET"], self.trust_recent),
            ("/live/kill", ["POST"], self.http_kill),
            ("/live/resume", ["POST"], self.http_resume),
            ("/live/state", ["GET"], self.http_state),
            ("/approve/{approval_id}", ["GET"], self.page_approve),
            ("/approvals/{approval_id}", ["GET"], self.http_approval),
            ("/approvals/{approval_id}/decide", ["POST"], self.http_approval_decide),
        ]

    def ws_routes(self) -> list[tuple[str, Callable]]:
        return [("/live/ws", self.ws_live)]


# ---------------------------------------------------------------- trust-change watcher

class TrustWatcher:
    """Periodically re-scores live passports and publishes what changed to the public trust feed."""

    def __init__(self, live: LiveService):
        self.live = live

    def run_once(self) -> int:
        lv = self.live
        with lv.lock:
            ids = [r["passport_id"] for r in lv.db.execute(
                "SELECT passport_id FROM passports WHERE revoked_at IS NULL ORDER BY created_at DESC LIMIT 500").fetchall()]
        changed = 0
        for pid in ids:
            rec = lv.passports.get(pid)
            if not rec:
                continue
            with lv.lock:
                prev = lv.db.execute("SELECT * FROM trust_state WHERE passport_id=?", (pid,)).fetchone()
            if prev and prev["state"] == "expired":
                continue
            try:
                v = lv.passports.check(rec)
            except Exception:
                continue
            live = v.get("live") or {}
            score, grade = live.get("score", v["issued_score"]), live.get("grade", v["issued_grade"])
            state = ("valid" if v["valid"] else "broken" if v.get("history_still_intact") is False
                     else "expired" if v["expired"] else "invalid")
            with lv.lock:
                lv.db.execute("INSERT INTO trust_state (passport_id, state, score, grade, at) VALUES (?,?,?,?,?) "
                              "ON CONFLICT(passport_id) DO UPDATE SET state=excluded.state, score=excluded.score, "
                              "grade=excluded.grade, at=excluded.at", (pid, state, score, grade, _iso(_now())))
                lv.db.commit()
            if not prev:
                continue                       # first observation: remember, don't announce
            base = {"passport_id": pid, "org_id": rec["org_id"], "stream_id": rec["stream_id"],
                    "addresses": self._addresses(rec["org_id"], rec["stream_id"])}
            if state != prev["state"]:
                lv.emit_trust("passport.state_changed", {**base, "from": prev["state"], "to": state,
                                                          "score": score, "grade": grade}, rec["org_id"])
                changed += 1
            elif abs(score - prev["score"]) >= TRUST_MIN_DELTA or grade != prev["grade"]:
                lv.emit_trust("passport.score_changed", {**base, "score_from": prev["score"], "score_to": score,
                                                          "grade_from": prev["grade"], "grade_to": grade}, rec["org_id"])
                changed += 1
        return changed

    def _addresses(self, org_id: str, stream_id: str) -> list[str]:
        try:
            return [b["address"] for b in self.live.kya.list_for(org_id)
                    if not b["revoked_at"] and b["stream_id"] in ("*", stream_id)]
        except Exception:
            return []


def mount_ws(app, routes: list[tuple[str, Callable]]) -> None:
    """Add WebSocket routes to the Starlette app returned by MCPServer.streamable_http_app()."""
    from starlette.routing import WebSocketRoute
    for path, handler in routes:
        app.router.routes.append(WebSocketRoute(path, handler))
