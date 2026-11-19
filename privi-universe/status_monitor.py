"""Read-only status observation for Privi Universe sandbox demos.

Fixed allowlist, verified HTTPS, no redirects or user-provided URLs, bounded
response size, and a short cache. A health response is *not* uptime, security,
billing or mainnet readiness certification.
"""
from __future__ import annotations

import json
import ssl
import threading
import time
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler

TARGETS = {
    "one": ("https://privi-one-demo.onrender.com/health", "PRELAUNCH_SIMULATION"),
    "outcome": ("https://privi-outcomegrid-demo.onrender.com/health", "SYNTHETIC_PRELAUNCH"),
}
CACHE_SECONDS = 90


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("Redirect disallowed for health checks")


def https_fetch(url):
    """Only invoked for the two hardcoded, allowlisted URLs."""
    if url not in {x[0] for x in TARGETS.values()}:
        raise ValueError("Unapproved health URL")
    opener = build_opener(HTTPSHandler(context=ssl.create_default_context()), NoRedirect())
    req = Request(url, method="GET", headers={"User-Agent": "PriviUniverseReadOnlyStatus/1",
                                              "Accept": "application/json"})
    with opener.open(req, timeout=4) as response:
        if response.status != 200:
            raise RuntimeError("Unexpected HTTP status")
        data = response.read(4097)
        if len(data) > 4096:
            raise RuntimeError("Health JSON too large")
        return json.loads(data)


class StatusMonitor:
    def __init__(self, fetch=None, now=None):
        self.fetch = fetch if fetch is not None else https_fetch
        self.now = now if now is not None else time.time
        self.lock = threading.Lock()
        self._snapshot = None
        self._expires = 0.0

    def snapshot(self):
        with self.lock:
            ts = self.now()
            if self._snapshot is not None and ts < self._expires:
                return self._snapshot
            services = {}
            for key, (url, expected_mode) in TARGETS.items():
                state = "unreachable_or_unverified"
                try:
                    payload = self.fetch(url)
                    if (isinstance(payload, dict) and payload.get("ok") is True
                            and payload.get("mode") == expected_mode):
                        state = "health_responding"
                    else:
                        state = "unexpected_health_response"
                except Exception:
                    # Do not leak underlying infrastructure or exception detail.
                    pass
                services[key] = {"state": state, "scope": "SANDBOX_HEALTH_ONLY"}
            self._snapshot = {
                "mode": "READ_ONLY_SNAPSHOT_NOT_UPTIME_MONITORING",
                "checked_at_unix": int(ts),
                "refresh_interval_seconds": CACHE_SECONDS,
                "services": services,
                "references": {
                    "callproof": "not_monitored_source_reference",
                    "guard": "not_monitored_source_reference",
                    "ledger": "not_monitored_source_reference",
                },
                "authentication": "NOT_CONFIGURED",
                "payments": "NOT_CHECKED",
                "mainnet": "NOT_CHECKED",
            }
            self._expires = ts + CACHE_SECONDS
            return self._snapshot
