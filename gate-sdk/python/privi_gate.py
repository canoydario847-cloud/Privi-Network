# Copyright (c) 2026 Privi World Co. All rights reserved.
"""Privi Gate: let only AI agents with a valid Privi Passport call your API or MCP server.

Drop-in ASGI middleware (FastMCP streamable HTTP, Starlette, FastAPI, any ASGI app) plus a plain
check_passport() for anything else. Zero dependencies. Agents present their passport in the
X-Privi-Passport header (or "Authorization: PriviPassport pp_..."). Privi Gate verifies it against
Privi Ledger (signature, content unaltered, not expired or revoked, history still intact, live score),
caches the answer for a few minutes, and answers agents without one with HTTP 401 and instructions
for getting a passport.

    from privi_gate import PriviGate
    app = PriviGate(app, min_score=550)                 # enforce
    app = PriviGate(app, mode="monitor")                # log only, let everyone through
"""
from __future__ import annotations

import asyncio
import json
import re
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

__version__ = "0.1.0"
LEDGER_URL = "https://privi-ledger.onrender.com"
HEADER = "x-privi-passport"
GRADES = ["A", "B", "C", "D", "E"]
_ID = re.compile(r"^pp_[A-Za-z0-9_-]{4,64}$")


@dataclass
class Decision:
    allow: bool
    passport_id: str | None
    reasons: list[str] = field(default_factory=list)
    score: int | None = None
    grade: str | None = None
    subject: dict | None = None
    checked_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {"allow": self.allow, "passport_id": self.passport_id, "reasons": self.reasons,
                "score": self.score, "grade": self.grade, "subject": self.subject}


def how_to_get_one(ledger_url: str = LEDGER_URL) -> dict:
    return {
        "what": "This service only accepts AI agents carrying a valid Privi Passport (a signed, on-chain-anchored "
                "trust credential built from the agent's tamper-evident audit log).",
        "steps": [
            f"Create a free Privi Ledger organization: MCP tool ledger_signup at {ledger_url}/mcp",
            "Record your agent's actions with ledger_record (this history is what the passport scores)",
            "Issue a passport: MCP tool passport_issue (free on Pro; $1 USDC via x402 on the free plan)",
            "Send it on every request: header 'X-Privi-Passport: pp_...'",
        ],
        "verify_yourself": f"{ledger_url}/passports/<passport_id>",
        "docs": "https://github.com/canoydario847-cloud/Privi-Network/tree/main/gate-sdk",
    }


def _decide(doc: dict, passport_id: str, min_score: int, min_grade: str | None) -> Decision:
    v = doc.get("verification") or {}
    reasons: list[str] = []
    if not v.get("valid"):
        if v.get("hash_matches_issued") is False:
            reasons.append("passport content does not match what was issued")
        if v.get("signature_valid") is False:
            reasons.append("signature is not from Privi Ledger")
        if v.get("expired"):
            reasons.append("passport expired")
        if v.get("revoked"):
            reasons.append("passport revoked by its organization")
        if v.get("history_still_intact") is False:
            reasons.append("the agent's history no longer verifies (tampering detected since issue)")
        if not reasons:
            reasons.append("passport did not verify")
    live = v.get("live") or {}
    score = live.get("score", v.get("issued_score"))
    grade = live.get("grade", v.get("issued_grade"))
    if score is None or score < min_score:
        reasons.append(f"current score {score} is below the required {min_score}")
    if min_grade and grade in GRADES and GRADES.index(grade) > GRADES.index(min_grade.upper()):
        reasons.append(f"current grade {grade} is below the required {min_grade.upper()}")
    return Decision(not reasons, passport_id, reasons, score, grade, v.get("subject"))


def _http_get(url: str, timeout: float) -> tuple[int, dict]:
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": f"privi-gate/{__version__}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}


class PassportChecker:
    """Verifies passports against Privi Ledger with a small in-memory cache."""

    def __init__(self, min_score: int = 550, min_grade: str | None = None, ledger_url: str = LEDGER_URL,
                 cache_seconds: int = 300, timeout: float = 8.0, on_unreachable: str = "deny",
                 fetch: Callable[[str, float], tuple[int, dict]] = _http_get):
        if on_unreachable not in ("deny", "allow"):
            raise ValueError("on_unreachable must be 'deny' or 'allow'")
        self.min_score, self.min_grade = min_score, min_grade
        self.ledger_url, self.cache_seconds, self.timeout = ledger_url.rstrip("/"), cache_seconds, timeout
        self.on_unreachable, self._fetch = on_unreachable, fetch
        self._cache: dict[str, Decision] = {}
        self._lock = threading.Lock()

    def check(self, passport_id: str | None) -> Decision:
        if not passport_id:
            return Decision(False, None, ["no Privi Passport presented (send header X-Privi-Passport)"])
        passport_id = passport_id.strip()
        if not _ID.match(passport_id):
            return Decision(False, passport_id, ["malformed passport id"])
        with self._lock:
            hit = self._cache.get(passport_id)
        if hit and time.time() - hit.checked_at < self.cache_seconds:
            return hit
        try:
            status, doc = self._fetch(f"{self.ledger_url}/passports/{passport_id}", self.timeout)
        except Exception as e:  # network failure
            allow = self.on_unreachable == "allow"
            return Decision(allow, passport_id, [] if allow else [f"Privi Ledger unreachable: {type(e).__name__}"])
        if status == 404:
            d = Decision(False, passport_id, ["no such passport"])
        elif status != 200:
            allow = self.on_unreachable == "allow"
            return Decision(allow, passport_id, [] if allow else [f"Privi Ledger answered HTTP {status}"])
        else:
            d = _decide(doc, passport_id, self.min_score, self.min_grade)
        with self._lock:
            self._cache[passport_id] = d
        return d


def passport_from_headers(headers: dict[str, str]) -> str | None:
    h = {k.lower(): v for k, v in headers.items()}
    if h.get(HEADER):
        return h[HEADER].strip()
    auth = h.get("authorization", "")
    if auth.lower().startswith("privipassport "):
        return auth.split(None, 1)[1].strip()
    return None


def check_passport(passport_id: str | None, **kw) -> Decision:
    """One-off check without middleware (cache not shared between calls)."""
    return PassportChecker(**kw).check(passport_id)


class PriviGate:
    """ASGI middleware. mode='enforce' blocks agents without a valid passport; mode='monitor' only labels them."""

    def __init__(self, app, min_score: int = 550, min_grade: str | None = None, mode: str = "enforce",
                 exempt: tuple[str, ...] = ("/health", "/healthz", "/.well-known/", "/robots.txt"),
                 on_decision: Callable[[Decision, dict], None] | None = None, checker: PassportChecker | None = None,
                 **checker_kw):
        if mode not in ("enforce", "monitor"):
            raise ValueError("mode must be 'enforce' or 'monitor'")
        self.app, self.mode, self.exempt, self.on_decision = app, mode, tuple(exempt), on_decision
        self.checker = checker or PassportChecker(min_score=min_score, min_grade=min_grade, **checker_kw)

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket") or scope.get("path", "").startswith(self.exempt) \
                or scope.get("method") == "OPTIONS":
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope.get("headers", [])}
        pid = passport_from_headers(headers)

        d = await asyncio.get_running_loop().run_in_executor(None, self.checker.check, pid)
        if self.on_decision:
            try:
                self.on_decision(d, scope)
            except Exception:
                pass
        scope.setdefault("state", {})["privi_passport"] = d.to_dict()
        if d.allow or self.mode == "monitor":
            return await self.app(scope, receive, send)
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 4401})
            return
        body = json.dumps({"error": "privi_passport_required", "decision": d.to_dict(),
                           "how_to_get_one": how_to_get_one(self.checker.ledger_url)}).encode()
        await send({"type": "http.response.start", "status": 401, "headers": [
            (b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
            (b"www-authenticate", f'PriviPassport realm="privi", get="{self.checker.ledger_url}/mcp"'.encode()),
            (b"access-control-allow-origin", b"*")]})
        await send({"type": "http.response.body", "body": body})
