#!/usr/bin/env python3
"""Read-only HTTP health audit of Privi Render services.

Only GET requests are issued. No Render credentials, deploys, or configuration
changes. Free-plan services and static sites are opt-in to avoid unnecessary
wakeups and alert noise. This is not a replacement for Render events/metrics.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PAID_APIS = {
    "privi-ledger": "https://privi-ledger.onrender.com/health",
    "privi-verify": "https://privi-verify.onrender.com/health",
    "privi-call": "https://privi-call.onrender.com/health",
    "privi-quantum": "https://privi-quantum.onrender.com/health",
    "privi-anchor": "https://privi-anchor.onrender.com/health",
}
FREE_SERVICES = {
    "privi-discovery": "https://privi-discovery.onrender.com/health",
    "jose-backend": "https://jose-backend-vbuu.onrender.com/health",
    # Staging currently has no configured HTTP health route in Render.
    "privi-life-ai-staging": "https://privi-life-ai-staging.onrender.com/",
}
STATIC_SITES = {
    "privi-guard": "https://privi-guard-814f.onrender.com/",
    "privi-hub": "https://privi-hub.onrender.com/",
    "privi-live": "https://privi-live.onrender.com/",
    "privi-developers": "https://privi-developers.onrender.com/",
    "privi-chainflow": "https://privi-chainflow.onrender.com/",
    "privi-gov": "https://privi-gov.onrender.com/",
    "privi-mandates": "https://privi-mandates.onrender.com/",
    "privi-kya": "https://privi-kya.onrender.com/",
    "privi-passport": "https://privi-passport.onrender.com/",
    "privi-fortress": "https://privi-fortress.onrender.com/",
    "privi-world": "https://privi-world.onrender.com/",
    "jose-site": "https://jose-site.onrender.com/",
}


def check(name: str, url: str, timeout: float) -> dict:
    """Issue one GET and report the observable HTTP outcome."""
    req = Request(url, headers={"User-Agent": "PriviReadOnlyHealthAudit/1.0", "Accept": "*/*"})
    try:
        with urlopen(req, timeout=timeout) as response:
            status = response.status
            response.read(128)  # Don't capture body contents or secrets.
        return {"name": name, "url": url, "status": status, "ok": 200 <= status < 400}
    except HTTPError as exc:
        exc.close()
        return {"name": name, "url": url, "status": exc.code, "ok": False}
    except (URLError, TimeoutError, OSError) as exc:
        return {"name": name, "url": url, "status": None, "ok": False,
                "error": type(exc).__name__}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--include-free", action="store_true", help="Also GET free-tier endpoints (may cause cold starts)")
    parser.add_argument("--all-sites", action="store_true", help="Also GET all twelve static sites")
    parser.add_argument("--timeout", type=float, default=12.0, help="Per-request timeout in seconds (default 12)")
    args = parser.parse_args(argv)
    if args.timeout <= 0 or args.timeout > 120:
        parser.error("--timeout must be between 0 and 120 seconds")
    urls = dict(PAID_APIS)
    if args.include_free:
        urls.update(FREE_SERVICES)
    if args.all_sites:
        urls.update(STATIC_SITES)
    results = [check(name, url, args.timeout) for name, url in urls.items()]
    report = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "results": results,
        "failures": sum(not x["ok"] for x in results),
        "note": "HTTP success does not confirm service metrics, deployments, or database availability.",
    }
    print(json.dumps(report, indent=2))
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    sys.exit(main())
