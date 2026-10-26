# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Quantum - https://priviflow.us - dariocanoy@priviflow.us
"""Printable HTML for a signed post-quantum readiness package (GET /reports/<id>)."""
from __future__ import annotations

import html
from typing import Any

e = html.escape

CSS = """
:root{--paper:#F7F8FA;--surface:#FFFFFF;--ink:#0E1B33;--steel:#5A6B85;--seal:#2F5BEA;--verified:#0F8A5F;--warn:#9A5B00;--bad:#B4252F;--rule:#DCE1EA;--code:#EEF1F6}
@media (prefers-color-scheme:dark){:root{--paper:#0D1626;--surface:#122036;--ink:#E7ECF4;--steel:#93A3BB;--seal:#7FA2FF;--verified:#3CCB94;--warn:#F0B35A;--bad:#FF8088;--rule:#22314A;--code:#16263F}}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 "IBM Plex Sans",system-ui,sans-serif;padding:24px 16px 56px}
.wrap{max-width:980px;margin:0 auto;display:flex;flex-direction:column;gap:18px}
h1{font:600 clamp(26px,5vw,36px)/1.1 "IBM Plex Sans Condensed",system-ui,sans-serif;margin:0}h2{font:600 19px "IBM Plex Sans Condensed",system-ui,sans-serif;margin:0 0 10px}
.eyebrow{font:500 12px ui-monospace,monospace;letter-spacing:.1em;text-transform:uppercase;color:var(--seal)}
.card{background:var(--surface);border:1px solid var(--rule);border-radius:12px;padding:18px;min-width:0}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}.stat b{display:block;font:500 24px ui-monospace,monospace}.stat span{color:var(--steel);font-size:13px}
.table{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px}th,td{text-align:left;padding:8px 10px;border-top:1px solid var(--rule);vertical-align:top}
th{font-weight:600;color:var(--steel);font-size:12px;text-transform:uppercase;letter-spacing:.05em;border-top:0}
.mono{font-family:ui-monospace,monospace;font-size:13px;overflow-wrap:anywhere}.nw{white-space:nowrap}
.p1{color:var(--bad);font-weight:600}.p2{color:var(--warn);font-weight:600}.ok{color:var(--verified);font-weight:600}
.pill{display:inline-block;padding:2px 8px;border-radius:999px;font-size:12px;border:1px solid var(--rule)}
a{color:var(--seal)}.note{color:var(--steel);font-size:13px}
@media print{body{background:#fff;padding:0}.card{border-color:#ccc}}
"""


def _prio(p: str) -> str:
    cls = {"P1": "p1", "P2": "p2", "P4 done": "ok"}.get(p, "")
    return f'<span class="{cls}">{e(p)}</span>'


def render(att: dict[str, Any], verify: dict[str, Any], public_url: str) -> str:
    b = att["body"]
    pkg = b.get("package_body", {})
    s = pkg.get("summary", {})
    org = pkg.get("organization", {})
    aid = att["id"]
    anc = att.get("anchor") or {}
    sig_ok = verify.get("valid")
    explorer = "https://privi-devnet.onrender.com/tx/" if anc.get("chain_id") == 772626 else (
        "https://basescan.org/tx/" if anc.get("chain_id") == 8453 else "")
    anchor_html = (f'<span class="ok">Anchored</span> on {e(str(anc.get("network") or "chain"))}, block {e(str(anc.get("block_number")))} · '
                   f'<a class="mono" href="{e(explorer + anc["tx_hash"])}">{e(anc["tx_hash"][:18])}…</a>'
                   if anc.get("tx_hash") else '<span class="p2">Queued</span> for the next anchor batch (every few minutes)')
    rows = "".join(
        f"<tr><td>{_prio(a['priority'])}</td><td>{e(a['system'])}<div class='note mono'>{e(a['asset'])}</div></td>"
        f"<td class='mono'>{e(a['algorithm'])}</td><td>{e(a['usage'])}{' · ' + e(a['protocol']) if a.get('protocol') else ''}</td>"
        f"<td class='mono nw'>{e(a['deadline'] or '—')}</td><td>{e(a['action'])}</td></tr>"
        for a in pkg.get("assets", []))
    elements = ""
    if pkg.get("plan_elements"):
        elements = "<section class='card'><h2>OMB M-26-15 plan elements</h2><div class='table'><table><tr><th>#</th><th>Element</th><th>Status</th><th>Evidence in this package</th><th>Agency must supply</th></tr>" + "".join(
            f"<tr><td>{x['element']}</td><td>{e(x['name'])}</td><td><span class='pill {'ok' if x['status']=='evidence' else 'p2' if x['status']=='partial' else 'p1'}'>{e(x['status'])}</span></td>"
            f"<td>{e(x['evidence_in_package'] or '—')}</td><td>{e(x['agency_must_supply'] or '—')}</td></tr>" for x in pkg["plan_elements"]) + "</table></div></section>"
    contractor = ""
    if pkg.get("contractor_readiness"):
        contractor = "<section class='card'><h2>Federal contractor readiness (EO 14409)</h2><div class='table'><table><tr><th>Item</th><th>Source</th><th>Status</th></tr>" + "".join(
            f"<tr><td>{e(x['item'])}</td><td>{e(x['source'])}</td><td>{e(x['status'])}</td></tr>" for x in pkg["contractor_readiness"]) + "</table></div></section>"
    miles = "".join(f"<tr><td class='mono nw'>{e(m['date'])}</td><td>{e(m['source'])}</td><td>{e(m['item'])}</td></tr>" for m in pkg.get("milestones", []))
    caveats = "".join(f"<li>{e(c)}</li>" for c in pkg.get("caveats", []))
    sources = " · ".join(f"<a href='{e(x['url'])}'>{e(x['name'])}</a>" for x in pkg.get("sources", []))
    by = s.get("by_priority", {})
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PQC readiness: {e(org.get('name', ''))}</title><style>{CSS}</style></head><body><div class="wrap">
<header><div class="eyebrow">Privi Quantum · Post-quantum readiness package · {e(pkg.get('profile', ''))}</div>
<h1>{e(org.get('name', 'Organization'))}</h1>
<p class="note">Generated {e(pkg.get('generated_at', ''))} · Package <span class="mono">{e(aid)}</span>{(' · PQC Migration Lead: ' + e(org['pqc_lead'])) if org.get('pqc_lead') else ''}</p></header>
<section class="card"><div class="stats">
<div class="stat"><b>{s.get('assets', 0)}</b><span>Cryptographic assets</span></div>
<div class="stat"><b class="p1">{by.get('P1', 0)}</b><span>P1: HVA, high-impact, long-lived data</span></div>
<div class="stat"><b class="p2">{by.get('P2', 0)}</b><span>P2: other quantum-vulnerable</span></div>
<div class="stat"><b>{s.get('pqc_ready_percent') if s.get('pqc_ready_percent') is not None else '—'}%</b><span>Already PQC or hybrid</span></div>
<div class="stat"><b class="mono" style="font-size:18px">{e(s.get('next_deadline') or '—')}</b><span>Next deadline</span></div></div></section>
<section class="card"><h2>Integrity</h2>
<p>Signatures: {'<span class="ok">valid</span>' if sig_ok else '<span class="p1">INVALID</span>'} (Ed25519 + ML-DSA-87, NIST FIPS 204) · key <span class="mono">{e(att.get('key_id', ''))}</span> · <a href="{e(public_url)}/keys">public keys</a></p>
<p>On chain: {anchor_html}</p>
<p>CBOM (CycloneDX 1.6): <a href="{e(public_url)}/reports/{e(aid)}.cbom.json">download</a> · SHA-256 <span class="mono">{e(pkg.get('cbom_sha256', ''))}</span> · Full signed package: <a href="{e(public_url)}/reports/{e(aid)}.json">JSON</a></p></section>
<section class="card"><h2>Prioritized migration list</h2><div class="table"><table>
<tr><th>Priority</th><th>System / asset</th><th>Algorithm</th><th>Usage</th><th>Due</th><th>Action</th></tr>{rows}</table></div></section>
{elements}{contractor}
<section class="card"><h2>Federal milestones</h2><div class="table"><table><tr><th>Date</th><th>Source</th><th>What</th></tr>{miles}</table></div></section>
<section class="card"><h2>Notes</h2><ul>{caveats}</ul><p class="note">Sources: {sources}</p>
<p class="note">Privi World Co · Port Huron, Michigan · <a href="mailto:dariocanoy@priviflow.us">dariocanoy@priviflow.us</a> · Copyright (c) 2026 Privi World Co.</p></section>
</div></body></html>"""
