"""Privi Guard client: check what your agent reads (prompt injection) and what it sends (leaked secrets).

    from privi_guard import Guard
    guard = Guard()                                   # reads PRIVI_API_KEY from the environment
    v = guard.inbound(page_text, source=url)          # before acting on untrusted content
    if v.blocked: ...
    v = guard.outbound(message)                       # before sending / posting / calling a tool
    safe = v.redacted_text or message

    @guard.tool_result                                # check every result a tool returns
    def fetch(url): ...

Zero dependencies. Free: 1,000 checks a month with a free organization key:

    key = Guard.signup("Acme agents")["api_key"]      # store it; it is shown once
"""

from __future__ import annotations

import functools
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

__version__ = "0.1.0"
__all__ = ["Guard", "Verdict", "GuardBlocked", "GuardError"]

DEFAULT_URL = "https://privi-ledger.onrender.com"
UNIT_CHARS = 100_000
MAX_CHARS = 400_000


class GuardError(RuntimeError):
    """Privi could not be reached or refused the request (and fail_open is False)."""


class GuardBlocked(RuntimeError):
    """Raised by the decorators when content is blocked."""

    def __init__(self, verdict: "Verdict"):
        codes = ", ".join(f.get("code", "?") for f in verdict.findings) or "policy"
        super().__init__(f"Privi Guard blocked {verdict.direction} content ({codes})")
        self.verdict = verdict


@dataclass
class Verdict:
    verdict: str
    risk: int = 0
    direction: str = "inbound"
    findings: list[dict] = field(default_factory=list)
    redacted_text: str | None = None
    receipt: dict | None = None
    checked: bool = True
    error: str | None = None
    raw: dict = field(default_factory=dict)

    @property
    def blocked(self) -> bool:
        return self.verdict == "block"

    @property
    def warned(self) -> bool:
        return self.verdict == "warn"

    @property
    def ok(self) -> bool:
        return self.verdict == "allow"

    @property
    def receipt_id(self) -> str | None:
        return (self.receipt or {}).get("check_id")

    def explain(self) -> str:
        if not self.checked:
            return f"Not checked by Privi Guard: {self.error}"
        if not self.findings:
            return "Privi Guard: no attack or leak patterns found."
        return "Privi Guard " + self.verdict + ": " + "; ".join(f"{f.get('code')}: {f.get('detail')}" for f in self.findings)

    @classmethod
    def from_json(cls, d: dict) -> "Verdict":
        return cls(verdict=d.get("verdict", "allow"), risk=d.get("risk", 0), direction=d.get("direction", "inbound"),
                   findings=d.get("findings") or [], redacted_text=d.get("redacted_text"), receipt=d.get("receipt"), raw=d)


def _to_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", "replace")
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(value)


class Guard:
    """Client for Privi Guard.

    api_key    organization key (PRIVI_API_KEY). Without one, every check needs an x402 payment, which this
               zero-dependency client does not sign; use a key.
    fail_open  when Privi is unreachable, return an unchecked "allow" (True, the default) or raise GuardError.
    block_on   verdicts that make the decorators raise GuardBlocked (default: block only).
    """

    def __init__(self, api_key: str | None = None, base_url: str | None = None, timeout: float = 10.0,
                 fail_open: bool = True, block_on: tuple[str, ...] = ("block",)):
        self.api_key = api_key if api_key is not None else os.getenv("PRIVI_API_KEY", "")
        self.base_url = (base_url or os.getenv("PRIVI_GUARD_URL") or DEFAULT_URL).rstrip("/")
        self.timeout, self.fail_open, self.block_on = timeout, fail_open, tuple(block_on)

    # ---- transport -------------------------------------------------------------

    def _post(self, path: str, body: dict) -> dict:
        headers = {"Content-Type": "application/json", "User-Agent": f"privi-guard-python/{__version__}"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(self.base_url + path, data=json.dumps(body).encode(), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            try:
                detail = json.loads(e.read()).get("error", "")
            except Exception:
                detail = ""
            raise GuardError(f"HTTP {e.code}: {detail or e.reason}") from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            raise GuardError(f"cannot reach Privi Guard: {e}") from None

    def _unchecked(self, direction: str, err: Exception) -> Verdict:
        if not self.fail_open:
            raise err if isinstance(err, GuardError) else GuardError(str(err))
        return Verdict(verdict="allow", direction=direction, checked=False, error=str(err))

    # ---- checks ------------------------------------------------------------------

    def check(self, content: Any, direction: str = "inbound", source: str | None = None) -> Verdict:
        text = _to_text(content)
        if len(text) > MAX_CHARS:
            text = text[:MAX_CHARS]
        body = {"text": text, "direction": direction}
        if source:
            body["source"] = source[:300]
        try:
            return Verdict.from_json(self._post("/guard/v1/check", body))
        except GuardError as e:
            return self._unchecked(direction, e)

    def inbound(self, content: Any, source: str | None = None) -> Verdict:
        """Untrusted content the agent is about to read or act on."""
        return self.check(content, "inbound", source)

    def outbound(self, content: Any, source: str | None = None) -> Verdict:
        """Content the agent is about to send, post, write or pass to a tool."""
        return self.check(content, "outbound", source)

    def check_many(self, items: list[dict]) -> list[Verdict]:
        """items: [{"text": ..., "direction": "inbound"|"outbound", "source": optional}] (up to 50; needs a key)."""
        clean = [{"text": _to_text(i.get("text"))[:MAX_CHARS], "direction": i.get("direction", "inbound"),
                  **({"source": i["source"][:300]} if i.get("source") else {})} for i in items]
        try:
            out = self._post("/guard/v1/check_many", {"items": clean})
            return [Verdict.from_json(r) for r in out["results"]]
        except GuardError as e:
            return [self._unchecked(c["direction"], e) for c in clean]

    # ---- decorators ------------------------------------------------------------------

    def _enforce(self, v: Verdict) -> None:
        if v.verdict in self.block_on:
            raise GuardBlocked(v)

    def tool_result(self, fn: Callable | None = None, *, source: str | None = None):
        """Decorator: check what a tool returns before the agent sees it. Raises GuardBlocked on block."""
        def deco(f):
            @functools.wraps(f)
            def wrapper(*a, **kw):
                out = f(*a, **kw)
                self._enforce(self.inbound(out, source or f.__name__))
                return out
            return wrapper
        return deco(fn) if fn else deco

    def before_send(self, fn: Callable | None = None, *, arg: int | str = 0, redact: bool = True):
        """Decorator: check an outgoing argument (position or name) before the function sends it. With
        redact=True, secrets are replaced by [REDACTED:...] instead of raising."""
        def deco(f):
            @functools.wraps(f)
            def wrapper(*a, **kw):
                a = list(a)
                val = kw.get(arg) if isinstance(arg, str) else (a[arg] if len(a) > arg else None)
                if val is not None:
                    v = self.outbound(val, f.__name__)
                    if v.blocked and redact and v.redacted_text is not None and isinstance(val, str):
                        if isinstance(arg, str):
                            kw[arg] = v.redacted_text
                        else:
                            a[arg] = v.redacted_text
                    else:
                        self._enforce(v)
                return f(*a, **kw)
            return wrapper
        return deco(fn) if fn else deco

    @staticmethod
    def signup(organization_name: str, base_url: str | None = None) -> dict:
        """Create a free Privi organization and return its api_key (shown once; store it)."""
        g = Guard(api_key="", base_url=base_url, fail_open=False)
        return g._post("/guard/v1/signup", {"organization_name": organization_name})

    def receipt(self, check_id: str) -> dict:
        try:
            with urllib.request.urlopen(f"{self.base_url}/guard/v1/receipts/{check_id}", timeout=self.timeout) as r:
                return json.loads(r.read())
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise GuardError(str(e)) from None
