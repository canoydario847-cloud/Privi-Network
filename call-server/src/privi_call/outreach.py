# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Call - https://priviflow.us - dariocanoy@priviflow.us
"""Privi Call outreach checks: three records anyone placing calls has to keep, and one go / no-go check.

- Do-Not-Call list   your own list of people who asked not to be called (47 CFR 64.1200(d) requires callers to keep one)
- Calling hours      is it between 8 a.m. and 9 p.m. where the called person is (47 CFR 64.1200(c)(1))
- Consent records    who agreed to what (marketing calls, an AI voice, call recording, texts), hash-chained
- call_precheck      all three in one answer before an agent or a person dials

Each list belongs to a prepaid call key (pck_...). Phone numbers are stored only as salted SHA-256 hashes plus
the last four digits. This is record keeping, not legal advice; it does not check the National Do Not Call Registry.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from mcp_types import CallToolResult, TextContent, ToolAnnotations
from pydantic import Field

SCHEMA = """
CREATE TABLE IF NOT EXISTS out_dnc (
    owner TEXT NOT NULL, phone_hash TEXT NOT NULL, last4 TEXT NOT NULL, reason TEXT NOT NULL, added_at REAL NOT NULL,
    PRIMARY KEY (owner, phone_hash));
CREATE TABLE IF NOT EXISTS out_consent (
    id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT NOT NULL, phone_hash TEXT NOT NULL, last4 TEXT NOT NULL,
    consent_type TEXT NOT NULL, action TEXT NOT NULL, method TEXT NOT NULL, evidence_sha256 TEXT NOT NULL,
    at REAL NOT NULL, prev_hash TEXT NOT NULL, record_hash TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_out_consent ON out_consent (owner, phone_hash, consent_type, id);
"""
CONSENT_TYPES = ("marketing_calls", "ai_voice", "call_recording", "text_messages")
METHODS = ("web_form", "written", "verbal_recorded", "keypress", "text_reply", "other")
PURPOSES = ("marketing", "informational")
FEDERAL_START, FEDERAL_END = 8, 21        # 8:00 a.m. to 9:00 p.m. at the called party's location
GENESIS = "0" * 64
READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)


class OutreachError(ValueError):
    pass


def normalize_phone(phone: str) -> str:
    raw = str(phone or "").strip()
    digits = re.sub(r"\D", "", raw)
    if raw.startswith("+") and 8 <= len(digits) <= 15:
        return "+" + digits
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    raise OutreachError("phone must be a 10-digit US number or an international number starting with +")


def calling_hours(tz: str, when: str | None = None, start_hour: int = FEDERAL_START, end_hour: int = FEDERAL_END) -> dict[str, Any]:
    try:
        zone = ZoneInfo(str(tz or "").strip())
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise OutreachError("timezone must be an IANA name for where the called person is, e.g. America/Detroit") from None
    if not (isinstance(start_hour, int) and isinstance(end_hour, int) and 0 <= start_hour < end_hour <= 24):
        raise OutreachError("start_hour and end_hour must be whole hours with 0 <= start < end <= 24")
    if start_hour < FEDERAL_START or end_hour > FEDERAL_END:
        raise OutreachError(f"the window cannot be wider than the federal one ({FEDERAL_START}:00-{FEDERAL_END}:00); narrow it for stricter state rules")
    if when:
        try:
            t = datetime.fromisoformat(str(when).replace("Z", "+00:00"))
        except ValueError:
            raise OutreachError("when must be an ISO 8601 date-time") from None
        t = t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    else:
        t = datetime.now(timezone.utc)
    local = t.astimezone(zone)
    allowed = start_hour <= local.hour < end_hour
    nxt = local
    if not allowed:
        day = local.date() if local.hour < start_hour else local.date() + timedelta(days=1)
        nxt = datetime(day.year, day.month, day.day, start_hour, tzinfo=zone)
    return {"allowed": allowed, "timezone": zone.key, "local_time": local.isoformat(timespec="minutes"),
            "window": f"{start_hour:02d}:00-{end_hour:02d}:00 local time",
            "next_allowed_at": None if allowed else nxt.isoformat(timespec="minutes"),
            "next_allowed_utc": None if allowed else nxt.astimezone(timezone.utc).isoformat(timespec="minutes"),
            "rule": "47 CFR 64.1200(c)(1): no telephone solicitation before 8 a.m. or after 9 p.m. local time at the "
                    "called party's location. Some states set shorter hours; pass start_hour / end_hour to narrow."}


class Outreach:
    def __init__(self, store):
        self.store, self._db, self._lock = store, store._db, store._lock
        with self._lock:
            self._db.executescript(SCHEMA)

    def _owner(self, call_key: str) -> str:
        key = str(call_key or "")
        if not key.startswith("pck_") or self.store.balance(key) is None:
            raise OutreachError("a valid prepaid call key (pck_...) is required; buy one with call_credits_buy")
        return hashlib.sha256(key.encode()).hexdigest()

    @staticmethod
    def _ph(owner: str, phone: str) -> tuple[str, str]:
        e164 = normalize_phone(phone)
        return hashlib.sha256(f"{owner}:{e164}".encode()).hexdigest(), e164[-4:]

    # ---- do-not-call ----

    def dnc_add(self, call_key: str, phone: str, reason: str = "") -> dict:
        owner = self._owner(call_key)
        ph, last4 = self._ph(owner, phone)
        with self._lock:
            self._db.execute("INSERT OR IGNORE INTO out_dnc VALUES (?,?,?,?,?)", (owner, ph, last4, str(reason or "")[:200], time.time()))
        return {"on_do_not_call_list": True, "phone": f"***-{last4}", "list_size": self.dnc_size(owner)}

    def dnc_remove(self, call_key: str, phone: str) -> dict:
        owner = self._owner(call_key)
        ph, last4 = self._ph(owner, phone)
        with self._lock:
            n = self._db.execute("DELETE FROM out_dnc WHERE owner=? AND phone_hash=?", (owner, ph)).rowcount
        return {"removed": n == 1, "phone": f"***-{last4}", "list_size": self.dnc_size(owner)}

    def dnc_size(self, owner: str) -> int:
        return self._db.execute("SELECT COUNT(*) AS n FROM out_dnc WHERE owner=?", (owner,)).fetchone()["n"]

    def dnc_check(self, call_key: str, phone: str) -> dict:
        owner = self._owner(call_key)
        ph, last4 = self._ph(owner, phone)
        r = self._db.execute("SELECT reason, added_at FROM out_dnc WHERE owner=? AND phone_hash=?", (owner, ph)).fetchone()
        return {"phone": f"***-{last4}", "on_do_not_call_list": bool(r), "reason": r["reason"] if r else None,
                "added_at": datetime.fromtimestamp(r["added_at"], timezone.utc).isoformat(timespec="seconds") if r else None,
                "note": "Your own list only; the National Do Not Call Registry is checked separately."}

    # ---- consent ----

    def _consent_write(self, owner: str, ph: str, last4: str, ctype: str, action: str, method: str, evidence: str) -> dict:
        with self._lock:
            last = self._db.execute("SELECT record_hash FROM out_consent WHERE owner=? ORDER BY id DESC LIMIT 1", (owner,)).fetchone()
            rec = {"phone_hash": ph, "consent_type": ctype, "action": action, "method": method,
                   "evidence_sha256": evidence, "at": round(time.time(), 3), "prev_hash": last["record_hash"] if last else GENESIS}
            rec["record_hash"] = hashlib.sha256(json.dumps(rec, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            self._db.execute("INSERT INTO out_consent (owner, phone_hash, last4, consent_type, action, method, evidence_sha256,"
                             " at, prev_hash, record_hash) VALUES (?,?,?,?,?,?,?,?,?,?)",
                             (owner, ph, last4, ctype, action, method, evidence, rec["at"], rec["prev_hash"], rec["record_hash"]))
        return rec

    def consent_record(self, call_key: str, phone: str, consent_type: str, method: str, evidence_sha256: str = "") -> dict:
        owner = self._owner(call_key)
        if consent_type not in CONSENT_TYPES:
            raise OutreachError("consent_type must be one of: " + ", ".join(CONSENT_TYPES))
        if method not in METHODS:
            raise OutreachError("method must be one of: " + ", ".join(METHODS))
        ev = str(evidence_sha256 or "").strip().lower()
        if ev and not re.fullmatch(r"[0-9a-f]{64}", ev):
            raise OutreachError("evidence_sha256 must be a SHA-256 fingerprint (64 hex characters)")
        ph, last4 = self._ph(owner, phone)
        rec = self._consent_write(owner, ph, last4, consent_type, "granted", method, ev)
        return {"recorded": True, "phone": f"***-{last4}", "consent_type": consent_type, "record_hash": rec["record_hash"]}

    def consent_revoke(self, call_key: str, phone: str, consent_type: str = "", add_to_do_not_call: bool = True) -> dict:
        owner = self._owner(call_key)
        types = [consent_type] if consent_type else list(CONSENT_TYPES)
        if consent_type and consent_type not in CONSENT_TYPES:
            raise OutreachError("consent_type must be one of: " + ", ".join(CONSENT_TYPES))
        ph, last4 = self._ph(owner, phone)
        current = self._current(owner, ph)
        revoked = [t for t in types if current.get(t, {}).get("granted")]
        for t in revoked:
            self._consent_write(owner, ph, last4, t, "revoked", "other", "")
        if add_to_do_not_call and not consent_type:
            with self._lock:
                self._db.execute("INSERT OR IGNORE INTO out_dnc VALUES (?,?,?,?,?)", (owner, ph, last4, "revoked consent", time.time()))
        return {"phone": f"***-{last4}", "revoked": revoked, "on_do_not_call_list": bool(add_to_do_not_call and not consent_type)}

    def _current(self, owner: str, ph: str) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for r in self._db.execute("SELECT consent_type, action, method, evidence_sha256, at, record_hash FROM out_consent "
                                  "WHERE owner=? AND phone_hash=? ORDER BY id", (owner, ph)):
            out[r["consent_type"]] = {"granted": r["action"] == "granted", "method": r["method"],
                                      "evidence_sha256": r["evidence_sha256"] or None, "record_hash": r["record_hash"],
                                      "at": datetime.fromtimestamp(r["at"], timezone.utc).isoformat(timespec="seconds")}
        return out

    def consent_check(self, call_key: str, phone: str) -> dict:
        owner = self._owner(call_key)
        ph, last4 = self._ph(owner, phone)
        cur = self._current(owner, ph)
        return {"phone": f"***-{last4}", "consents": {t: cur.get(t, {"granted": False}) for t in CONSENT_TYPES}}

    def consent_verify_chain(self, call_key: str) -> dict:
        owner, prev, n = self._owner(call_key), GENESIS, 0
        for r in self._db.execute("SELECT * FROM out_consent WHERE owner=? ORDER BY id", (owner,)):
            rec = {"phone_hash": r["phone_hash"], "consent_type": r["consent_type"], "action": r["action"], "method": r["method"],
                   "evidence_sha256": r["evidence_sha256"], "at": r["at"], "prev_hash": r["prev_hash"]}
            h = hashlib.sha256(json.dumps(rec, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            n += 1
            if r["prev_hash"] != prev or h != r["record_hash"]:
                return {"intact": False, "records": n, "broken_at": n}
            prev = h
        return {"intact": True, "records": n, "head_hash": prev if n else None}

    # ---- go / no-go ----

    def precheck(self, call_key: str, phone: str, tz: str, purpose: str = "marketing", ai_voice: bool = False,
                 recording: bool = False, when: str | None = None, start_hour: int = FEDERAL_START,
                 end_hour: int = FEDERAL_END) -> dict:
        owner = self._owner(call_key)
        if purpose not in PURPOSES:
            raise OutreachError("purpose must be marketing or informational")
        ph, last4 = self._ph(owner, phone)
        hours = calling_hours(tz, when, start_hour, end_hour)
        cur = self._current(owner, ph)
        has = lambda t: bool(cur.get(t, {}).get("granted"))  # noqa: E731
        blockers, warnings = [], []
        if self._db.execute("SELECT 1 FROM out_dnc WHERE owner=? AND phone_hash=?", (owner, ph)).fetchone():
            blockers.append("this number is on your do-not-call list")
        if purpose == "marketing" and not hours["allowed"]:
            blockers.append(f"outside calling hours where the person is ({hours['local_time']}); next allowed {hours['next_allowed_at']}")
        if ai_voice and not has("ai_voice"):
            blockers.append("no recorded consent to an AI or prerecorded voice (the FCC treats AI-generated voices as "
                            "artificial voices under the TCPA, which need the called person's prior consent)")
        if purpose == "marketing" and not has("marketing_calls"):
            warnings.append("no recorded consent to marketing calls; needed for autodialed or prerecorded marketing calls")
        if recording and not has("call_recording"):
            warnings.append("no recorded consent to call recording; some states require every party's consent")
        if purpose == "informational" and not hours["allowed"]:
            warnings.append(f"it is {hours['local_time']} where the person is")
        return {"go": not blockers, "phone": f"***-{last4}", "blockers": blockers, "warnings": warnings,
                "calling_hours": hours, "consents": {t: has(t) for t in CONSENT_TYPES},
                "note": "Checks your own records only. It does not check the National Do Not Call Registry or state "
                        "rules, and it is not legal advice."}


def _result(data: dict[str, Any], is_error: bool = False) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(data))], structured_content=data, is_error=is_error)


Key = Annotated[str, Field(description="Your prepaid call key (pck_...); your lists belong to it")]
Phone = Annotated[str, Field(description="Phone number: 10-digit US or international starting with +")]
Tz = Annotated[str, Field(description="IANA timezone where the called person is, e.g. America/Detroit")]


def register(mcp, out: Outreach) -> None:

    def run(fn, *a, **kw) -> CallToolResult:
        try:
            return _result(fn(*a, **kw))
        except OutreachError as e:
            return _result({"error": str(e)}, is_error=True)

    @mcp.tool(title="Do-not-call list: add, remove or check", annotations=WRITE)
    def call_do_not_call(call_key: Key, phone: Phone,
                         action: Annotated[str, Field(description="check | add | remove")] = "check",
                         reason: Annotated[str, Field(description="Why it was added, e.g. 'asked on call 2026-11-13'")] = "") -> CallToolResult:
        """Keep your own do-not-call list: add a person who asked not to be called, remove one, or check a number
        before dialing. Numbers are stored only as salted hashes."""
        if action not in ("check", "add", "remove"):
            return _result({"error": "action must be check, add or remove"}, is_error=True)
        return run({"check": out.dnc_check, "remove": out.dnc_remove}.get(action) or out.dnc_add, call_key, phone,
                   *([reason] if action == "add" else []))

    @mcp.tool(title="Calling hours check", annotations=READ)
    def call_hours_check(timezone: Tz,
                         when: Annotated[str | None, Field(description="Moment to check (ISO 8601). Default: now")] = None,
                         start_hour: Annotated[int, Field(description="Narrow the window for stricter state rules", ge=8, le=20)] = FEDERAL_START,
                         end_hour: Annotated[int, Field(description="Narrow the window for stricter state rules", ge=9, le=21)] = FEDERAL_END) -> CallToolResult:
        """Is it within calling hours (8 a.m. to 9 p.m.) where the called person is, and if not, when the window
        opens next."""
        return run(calling_hours, timezone, when, start_hour, end_hour)

    @mcp.tool(title="Consent: record", annotations=WRITE)
    def call_consent_record(call_key: Key, phone: Phone,
                            consent_type: Annotated[str, Field(description="|".join(CONSENT_TYPES))],
                            method: Annotated[str, Field(description="How consent was given: " + "|".join(METHODS))],
                            evidence_sha256: Annotated[str, Field(description="SHA-256 of the form, recording or message that shows it")] = "") -> CallToolResult:
        """Record that a person agreed to marketing calls, an AI voice, call recording or texts. Records are
        hash-chained so they cannot be back-filled unnoticed."""
        return run(out.consent_record, call_key, phone, consent_type, method, evidence_sha256)

    @mcp.tool(title="Consent: revoke", annotations=WRITE)
    def call_consent_revoke(call_key: Key, phone: Phone,
                            consent_type: Annotated[str, Field(description="One type, or empty to revoke everything and add the number to your do-not-call list")] = "") -> CallToolResult:
        """Record that a person withdrew consent. With no type, every consent is revoked and the number goes on
        your do-not-call list."""
        return run(out.consent_revoke, call_key, phone, consent_type)

    @mcp.tool(title="Consent: check", annotations=READ)
    def call_consent_check(call_key: Key, phone: Annotated[str, Field(description="Phone number; empty to verify your whole consent log instead")] = "") -> CallToolResult:
        """What a person has agreed to, with when and how. With no phone, checks that your consent log is intact."""
        return run(out.consent_check, call_key, phone) if phone else run(out.consent_verify_chain, call_key)

    @mcp.tool(title="Pre-call check: go or no-go", annotations=READ)
    def call_precheck(call_key: Key, phone: Phone, timezone: Tz,
                      purpose: Annotated[str, Field(description="marketing | informational")] = "marketing",
                      ai_voice: Annotated[bool, Field(description="The call uses an AI or prerecorded voice")] = False,
                      recording: Annotated[bool, Field(description="The call will be recorded")] = False,
                      when: Annotated[str | None, Field(description="Planned call time (ISO 8601). Default: now")] = None) -> CallToolResult:
        """One answer before dialing: is the number on your do-not-call list, is it within calling hours where the
        person is, and do you hold the consent this call needs. Returns go / no-go with the reasons."""
        return run(out.precheck, call_key, phone, timezone, purpose, ai_voice, recording, when)
