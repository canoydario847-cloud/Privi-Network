# Copyright (c) 2026 Privi World Co. All rights reserved.
"""Apify Actor: post-quantum TLS check, priced per host checked (pay-per-event 'host-checked').

Each host gets two raw TLS ClientHellos (no handshake completed, no data sent): one offering only
hybrid ML-KEM groups, one classical. Only public addresses on TLS ports are probed.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

from apify import Actor

from . import pqctls

MAX_HOSTS = 500
EVENT = "host-checked"          # define this event and its price in Apify Console -> Monetization


async def main() -> None:
    async with Actor:
        inp = await Actor.get_input() or {}
        hosts = [h for h in dict.fromkeys(str(h).strip() for h in inp.get("hosts") or []) if h][:MAX_HOSTS]
        timeout = float(inp.get("timeoutSeconds") or 6)
        if not hosts:
            await Actor.fail(status_message="Give at least one hostname in 'hosts'.")
            return
        loop = asyncio.get_running_loop()
        counts = {"pq_hybrid": 0, "tls13_classical": 0, "tls12": 0, "no_tls13": 0, "other": 0}
        with ThreadPoolExecutor(max_workers=8) as pool:
            for start in range(0, len(hosts), 8):
                batch = hosts[start:start + 8]
                results = await asyncio.gather(*[loop.run_in_executor(pool, pqctls.check_endpoint, h, timeout) for h in batch])
                for r in results:
                    counts[r["status"] if r["status"] in counts else "other"] += 1
                    checked = r["status"] in ("pq_hybrid", "tls13_classical", "tls12", "no_tls13")
                    if checked:   # bill only real checks, never invalid / blocked / unreachable hosts
                        charge = await Actor.push_data(r, EVENT)
                        if charge and getattr(charge, "event_charge_limit_reached", False):
                            await Actor.set_status_message("Spending limit reached; stopping.")
                            await Actor.set_value("SUMMARY", {"counts": counts, "stopped_at": r.get("host")})
                            return
                    else:
                        await Actor.push_data(r)
        total = sum(v for k, v in counts.items() if k != "other")
        summary = {"counts": counts, "checked": total,
                   "pq_ready_percent": round(100 * counts["pq_hybrid"] / total) if total else None,
                   "note": "Key exchange only; certificate signatures stay classical until CAs issue ML-DSA certificates.",
                   "more": "Signed EO 14409 / OMB M-26-15 readiness packages: https://privi-quantum.onrender.com (pqc_readiness_package)"}
        await Actor.set_value("SUMMARY", summary)
        await Actor.set_status_message(f"{counts['pq_hybrid']} of {total} hosts use post-quantum key exchange.")
