#!/usr/bin/env python3
"""Privi regional health latency probe; standard-library only.

Run from actual regional machines. Does not measure MCP calls or quantum speed.
Copyright (c) 2026 Privi World Co. All rights reserved.
"""
from __future__ import annotations

import argparse
import concurrent.futures
from datetime import datetime, timezone
import json
import math
import statistics
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def probe(url: str, timeout: float) -> dict:
    started = time.perf_counter()
    try:
        with urlopen(Request(url, headers={"User-Agent": "privi-latency-probe/1.0",
                                            "Accept": "application/json"}), timeout=timeout) as response:
            status = response.status
            response.read(1024)  # Cap the amount of data consumed.
        success = 200 <= status < 300
        error = None if success else f"HTTP {status}"
    except HTTPError as exc:
        success, error = False, f"HTTP {exc.code}"
    except (URLError, TimeoutError, OSError) as exc:
        success, error = False, type(exc).__name__
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    return {"ok": success, "ms": elapsed_ms, "error": error}


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(len(ordered) * fraction) - 1)], 2)


def summarize(url: str, samples: list[dict]) -> dict:
    ok = [x["ms"] for x in samples if x["ok"]]
    errors: dict[str, int] = {}
    for x in samples:
        if x["error"]:
            errors[x["error"]] = errors.get(x["error"], 0) + 1
    return {
        "url": url, "requests": len(samples), "successes": len(ok),
        "failure_rate": round(1 - len(ok) / len(samples), 3),
        "p50_ms": percentile(ok, .50), "p95_ms": percentile(ok, .95),
        "p99_ms": percentile(ok, .99),
        "mean_ms": round(statistics.mean(ok), 2) if ok else None,
        "errors": errors,
        "measurement": "HTTPS health request, no reusable connection guarantee",
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--region", required=True, help="Caller-supplied origin label")
    p.add_argument("--url", action="append", required=True, help="Public HTTPS /health endpoint; repeatable")
    p.add_argument("--requests", type=int, default=20, help="Requests per URL (1-100)")
    p.add_argument("--workers", type=int, default=4, help="Concurrent requests (1-16)")
    p.add_argument("--timeout", type=float, default=8, help="Per-request timeout, seconds")
    p.add_argument("--output", default="", help="Optional local JSON report file")
    args = p.parse_args()
    if not (1 <= args.requests <= 100 and 1 <= args.workers <= 16 and 1 <= args.timeout <= 30):
        p.error("requests: 1-100; workers: 1-16; timeout: >0 to 30")
    for url in args.url:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            p.error("Only credential-free public HTTPS URLs are accepted")
        if not parsed.path.endswith("/health"):
            p.error("Only /health endpoints are supported; no authenticated calls")
    report = {"service": "privi-health-probe", "time_utc": datetime.now(timezone.utc).isoformat(),
              "region_label_unverified": args.region, "results": []}
    for url in args.url:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            samples = list(pool.map(lambda _: probe(url, args.timeout), range(args.requests)))
        report["results"].append(summarize(url, samples))
    text = json.dumps(report, indent=2)
    print(text)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as file:
            file.write(text + "\n")
    return 0 if all(x["successes"] > 0 for x in report["results"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
