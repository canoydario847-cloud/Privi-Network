# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Quantum - https://priviflow.us - dariocanoy@priviflow.us
"""The Privi Quantum Leaderboard: every quantum backend ranked only by runs Privi measured and sealed.

Nothing here comes from a vendor's claims. Each row is computed from this server's own job log (success,
turnaround, price) and its signed Quantum Advantage Receipts (did the backend find the proven optimum, and did
quantum beat classical). Rows link to receipt hashes anyone can check in Privi Explorer, never to customer data.
"""
from __future__ import annotations

import html
import json
import statistics
from datetime import datetime, timezone
from typing import Any

MIN_RUNS_TO_RANK = 3


def _median(xs: list[float]) -> float | None:
    return round(statistics.median(xs), 3) if xs else None


def compute(router, attestor) -> dict[str, Any]:
    rows: dict[str, dict] = {}

    def row(bid: str) -> dict:
        if bid not in rows:
            b = router.backends.get(bid)
            rows[bid] = {"backend": bid, "provider": b.provider if b else bid.split(":")[0],
                         "name": b.name if b else bid, "kind": b.kind if b else "unknown",
                         "connected": bool(b and b.configured()[0]), "jobs": 0, "completed": 0, "failed": 0,
                         "turnarounds": [], "costs": [], "shots": 0, "circuit_runs": 0,
                         "receipts": 0, "optimum_found": 0, "verdicts": {"quantum_won": 0, "classical_won": 0, "tie": 0},
                         "recent_receipt_hashes": []}
        return rows[bid]

    for bid in router.backends:
        row(bid)
    for j in router._db.execute("SELECT backend_id, problem, status, turnaround_s, est_cost_usd, shots FROM hw_jobs"):
        r = row(j["backend_id"])
        r["jobs"] += 1
        r["shots"] += j["shots"] or 0
        if j["status"] == "done":
            r["completed"] += 1
            if j["turnaround_s"] is not None:
                r["turnarounds"].append(float(j["turnaround_s"]))
            if j["est_cost_usd"] is not None:
                r["costs"].append(float(j["est_cost_usd"]))
            if j["problem"] == "circuit":
                r["circuit_runs"] += 1
        elif j["status"] in ("failed", "canceled"):
            r["failed"] += 1
    tally = {"quantum_won": 0, "classical_won": 0, "tie": 0}
    for a in attestor._db.execute("SELECT body, body_sha256 FROM attestations WHERE kind='advantage_receipt' ORDER BY rowid DESC"):
        b = json.loads(a["body"])
        q = b.get("quantum") or {}
        r = row(q.get("backend") or "local")
        r["receipts"] += 1
        r["optimum_found"] += bool(q.get("found_optimum"))
        v = b.get("verdict")
        if v in r["verdicts"]:
            r["verdicts"][v] += 1
            tally[v] += 1
        if len(r["recent_receipt_hashes"]) < 3:
            r["recent_receipt_hashes"].append(a["body_sha256"])
    out = []
    for r in rows.values():
        done_or_failed = r["completed"] + r["failed"]
        r["success_rate"] = round(r["completed"] / done_or_failed, 4) if done_or_failed else None
        r["optimum_rate"] = round(r["optimum_found"] / r["receipts"], 4) if r["receipts"] else None
        r["median_turnaround_s"] = _median(r.pop("turnarounds"))
        costs = r.pop("costs")
        r["median_cost_usd"] = _median(costs)
        r["measured_runs"] = max(r["completed"], r["receipts"])
        r["ranked"] = r["measured_runs"] >= MIN_RUNS_TO_RANK
        out.append(r)

    def key(r):
        return (not r["ranked"], -(r["optimum_rate"] or 0), -(r["success_rate"] if r["success_rate"] is not None else 1),
                r["median_turnaround_s"] if r["median_turnaround_s"] is not None else 1e12, -r["measured_runs"])
    out.sort(key=key)
    rank = 0
    for r in out:
        r["rank"] = (rank := rank + 1) if r["ranked"] else None
    return {"title": "Privi Quantum Leaderboard", "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "method": ("Ranked by share of sealed runs that found the proven optimum, then job success rate, then median "
                       f"turnaround. A backend needs {MIN_RUNS_TO_RANK} measured runs to be ranked. Only runs routed through "
                       "Privi Quantum count; every receipt is signed (Ed25519 + ML-DSA-87) and anchored on Base."),
            "quantum_vs_classical": tally, "backends": out,
            "simulators_note": "Simulators are noise-free, so they lead on quality; compare QPUs with QPUs.",
            "honest_note": ("At today's problem sizes classical methods usually match or beat quantum; this board records "
                            "that as it happens and will show the first measured quantum win the same way.")}


def render(board: dict, explorer_url: str) -> str:
    h = lambda x: html.escape(str(x), quote=True)  # noqa: E731
    pct = lambda x: "—" if x is None else f"{x * 100:.0f}%"  # noqa: E731
    secs = lambda x: "—" if x is None else (f"{x:.1f} s" if x < 120 else f"{x / 60:.1f} min" if x < 7200 else f"{x / 3600:.1f} h")  # noqa: E731
    money = lambda x: "—" if x is None else ("free" if x == 0 else f"${x:,.2f}")  # noqa: E731
    rows = []
    for r in board["backends"]:
        v = r["verdicts"]
        kind = "QPU" if r["kind"] == "qpu" else "simulator"
        status = "" if r["connected"] else ' <span class="muted">(not connected)</span>'
        hashes = " ".join(f'<a class="mono" href="{h(explorer_url)}?q={h(x)}">{h(x[:10])}…</a>' for x in r["recent_receipt_hashes"])
        rows.append(f"""<tr class="{'' if r['ranked'] else 'unranked'}"><td class="num">{r['rank'] or '—'}</td>
<td><b>{h(r['provider'])}</b> <span class="tag">{kind}</span><br><span class="muted">{h(r['name'])} · {h(r['backend'])}</span>{status}</td>
<td class="num">{r['measured_runs']}</td><td class="num">{pct(r['optimum_rate'])}</td><td class="num">{pct(r['success_rate'])}</td>
<td class="num">{secs(r['median_turnaround_s'])}</td><td class="num">{money(r['median_cost_usd'])}</td>
<td class="num">{v['quantum_won']} / {v['classical_won']} / {v['tie']}</td><td>{hashes or '<span class="muted">none yet</span>'}</td></tr>""")
    t = board["quantum_vs_classical"]
    total = sum(t.values())
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Privi Quantum Leaderboard</title>
<meta name="description" content="Quantum computers ranked only by runs Privi measured and sealed: quality, reliability, speed and price.">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400&family=IBM+Plex+Sans+Condensed:wght@600&family=IBM+Plex+Sans:wght@400;600&display=swap" rel="stylesheet">
<style>
:root{{--paper:#F7F8FA;--surface:#FFFFFF;--ink:#0E1B33;--steel:#5A6B85;--seal:#2F5BEA;--q:#7A3FD1;--ok:#0F8A5F;--warn:#A15C00;--rule:#DCE1EA}}
@media (prefers-color-scheme:dark){{:root{{--paper:#0D1626;--surface:#122036;--ink:#E7ECF4;--steel:#93A3BB;--seal:#7FA2FF;--q:#B892FF;--ok:#3CCB94;--warn:#F0B35A;--rule:#22314A}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:16px/1.55 "IBM Plex Sans",system-ui,sans-serif}}
.wrap{{max-width:1180px;margin:0 auto;padding:0 16px}}a{{color:var(--seal)}}
header{{background:var(--surface);border-bottom:1px solid var(--rule)}}header .wrap{{display:flex;justify-content:space-between;align-items:center;min-height:58px;gap:12px;flex-wrap:wrap}}
.mark{{font:600 20px "IBM Plex Sans Condensed",sans-serif;color:var(--ink);text-decoration:none}}
h1{{font:600 clamp(30px,4.5vw,46px)/1.05 "IBM Plex Sans Condensed",sans-serif;margin:36px 0 8px}}
.lede{{color:var(--steel);max-width:52em;margin:0 0 22px}}
.score{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:0 0 22px}}
.score div{{background:var(--surface);border:1px solid var(--rule);border-radius:12px;padding:12px 14px}}
.score b{{display:block;font:600 28px/1.2 "IBM Plex Sans Condensed",sans-serif;font-variant-numeric:tabular-nums}}
.score span{{color:var(--steel);font-size:13px}}
.tablewrap{{overflow-x:auto;background:var(--surface);border:1px solid var(--rule);border-radius:12px}}
table{{border-collapse:collapse;width:100%;min-width:860px;font-size:14px}}
th,td{{text-align:left;padding:11px 12px;border-bottom:1px solid var(--rule);vertical-align:top}}th{{color:var(--steel);font-weight:600;font-size:13px}}
td.num,th.num{{text-align:right;font-variant-numeric:tabular-nums}}tr:last-child td{{border-bottom:0}}tr.unranked td{{color:var(--steel)}}
.tag{{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.03em;padding:2px 6px;border-radius:4px;box-shadow:inset 0 0 0 1.2px var(--q);color:var(--q)}}
.muted{{color:var(--steel)}}.mono{{font:13px "IBM Plex Mono",monospace}}
.notes{{color:var(--steel);font-size:14px;max-width:60em;margin:18px 0 40px}}
@media (max-width:700px){{.score{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}
</style></head><body>
<header><div class="wrap"><a class="mark" href="/leaderboard">Privi Quantum Leaderboard</a><nav><a href="{h(explorer_url)}">Privi Explorer</a> · <a href="/leaderboard.json">JSON</a></nav></div></header>
<main class="wrap">
<h1>Which quantum computer actually delivers?</h1>
<p class="lede">Every row comes from a job Privi routed and measured itself: whether the answer was the proven optimum, whether the job
finished, how long it took and what it cost. Every result is signed and anchored on Base, so you can check it, not take it on trust.</p>
<div class="score"><div><b>{total}</b><span>sealed advantage receipts</span></div><div><b>{t['quantum_won']}</b><span>quantum won</span></div>
<div><b>{t['classical_won']}</b><span>classical won</span></div><div><b>{t['tie']}</b><span>ties</span></div></div>
<div class="tablewrap"><table><thead><tr><th class="num">Rank</th><th>Backend</th><th class="num">Measured runs</th><th class="num">Found optimum</th>
<th class="num">Jobs finished</th><th class="num">Median turnaround</th><th class="num">Median cost</th><th class="num">Quantum / classical / tie</th>
<th>Latest receipts</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<p class="notes">{h(board['method'])} {h(board['simulators_note'])} {h(board['honest_note'])} Updated {h(board['generated_at'].replace('T', ' ').replace('+00:00', ' UTC'))}.
Run your own circuit or problem on any backend with Privi Quantum (<code>quantum_run_circuit</code>, <code>quantum_run_hardware</code>) and it joins the board.
© 2026 Privi World Co.</p>
</main></body></html>"""
