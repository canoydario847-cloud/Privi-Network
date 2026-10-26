"""Privi ChainFlow web API on top of Privi Verify.

Browser-facing routes for chainflow.privishine.info:

    POST /api/chainflow/events          record a lot event (manufacturer key, Bearer)
    POST /api/chainflow/key             check a manufacturer key
    GET  /api/chainflow/label/{fp}      free: the event a label fingerprint points to, chain + on-chain status
    GET  /label/{fp}                    the same as a printable public page (the QR code on a box)

Full chains of custody stay paid (privi_verify_lot / privi_chain_of_custody over x402).
"""
from __future__ import annotations

import hmac
import html
import json
from typing import Any, Callable

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response

from .store import EVENT_TYPES, LotStore

CORS = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "authorization, content-type", "Access-Control-Max-Age": "600"}
FIELDS_MAX = {"lot_code": 80, "event_type": 20, "location": 160, "actor": 160, "product": 160, "quantity": 60, "notes": 500}


def _token(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    return auth[7:].strip() if auth.lower().startswith("bearer ") else ""


def _authorized(token: str, keys: set[str]) -> bool:
    return bool(token) and any(hmac.compare_digest(token, k) for k in keys)


def label_info(store: LotStore, fp: str, onchain: Callable[[str, dict], dict]) -> dict[str, Any] | None:
    """Everything a buyer may see for free from one label: that event, whether history up to it is intact,
    and whether an on-chain checkpoint covers it."""
    hit = store.find_fingerprint(fp)
    if not hit:
        return None
    evs = store.events(hit["lot_code"])
    upto = [e for e in evs if e["seq"] <= hit["seq"]]
    check = store.check_chain(upto)
    ev = upto[-1]
    integrity: dict[str, Any] = {"valid": check.valid, "broken_at_seq": check.broken_at_seq, "reason": check.reason}
    cp = onchain(ev["lot_code"], integrity)
    covered = bool(cp.get("anchored") and cp.get("matches_current_record") and cp.get("seq", 0) >= ev["seq"])
    return {
        "found": True, "fingerprint": ev["record_hash"], "lot_code": ev["lot_code"], "seq": ev["seq"],
        "event_type": ev["event_type"], "occurred_at": ev["occurred_at"], "location": ev["location"],
        "actor": ev["actor"], "product": ev["product"], "quantity": ev["quantity"],
        "later_events": len(evs) - len(upto),
        "recalled": any(e["event_type"] == "recalled" for e in evs),
        "integrity": {"history_intact": integrity["valid"], "reason": integrity.get("reason")},
        "onchain": {"covered": covered, "tx_hash": cp.get("tx_hash") if covered else None,
                    "block_number": cp.get("block_number") if covered else None,
                    "note": None if covered else "Not yet covered by an on-chain checkpoint; checkpoints run every few minutes."},
    }


def _label_page(info: dict[str, Any] | None, fp: str, public_url: str, chainflow_url: str) -> str:
    e = html.escape
    if not info:
        body = (f"<h1>Label not found</h1><p>No Privi ChainFlow record has the fingerprint <code>{e(fp[:80])}</code>. "
                "Check the code on the label, or ask the supplier.</p>")
        status = ""
    else:
        ok = info["integrity"]["history_intact"]
        status = ("<p class='badge bad'>Recalled lot</p>" if info["recalled"] else
                  "<p class='badge ok'>Record intact</p>" if ok else
                  f"<p class='badge bad'>Record altered: {e(str(info['integrity']['reason']))}</p>")
        oc = info["onchain"]
        chain = (f"Covered by an on-chain checkpoint (Base, block {e(str(oc['block_number']))}): "
                 f"<a href='https://basescan.org/tx/{e(str(oc['tx_hash']))}'>{e(str(oc['tx_hash'])[:18])}…</a>"
                 if oc["covered"] else e(oc["note"]))
        rows = "".join(f"<tr><th>{k}</th><td>{e(str(v))}</td></tr>" for k, v in (
            ("Lot", info["lot_code"]), ("Product", info["product"] or "—"), ("Event", f"#{info['seq']} {info['event_type']}"),
            ("When (UTC)", info["occurred_at"]), ("Where", info["location"]), ("By", info["actor"]),
            ("Quantity", info["quantity"] or "—"), ("Later events", info["later_events"])) )
        body = (f"<h1>{e(info['product'] or info['lot_code'])}</h1>{status}<table>{rows}</table>"
                f"<p class='note'>{chain}</p>"
                f"<p class='note'>Fingerprint <code>{e(info['fingerprint'])}</code>: SHA-256 of this event and the one before it, "
                "so any later edit to the history changes it.</p>"
                f"<p><a class='btn' href='{e(public_url)}/pay'>Full chain of custody (paid, USDC)</a> "
                f"<a class='btn alt' href='{e(chainflow_url)}'>About ChainFlow</a></p>")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Privi ChainFlow label</title><meta name="robots" content="noindex">
<style>:root{{--paper:#F7F8FA;--surface:#fff;--ink:#0E1B33;--steel:#5A6B85;--seal:#2F5BEA;--on:#fff;--ok:#0F8A5F;--bad:#B4252F;--rule:#DCE1EA}}
@media (prefers-color-scheme:dark){{:root{{--paper:#0D1626;--surface:#122036;--ink:#E7ECF4;--steel:#93A3BB;--seal:#7FA2FF;--on:#0D1626;--ok:#3CCB94;--bad:#FF8088;--rule:#22314A}}}}
body{{margin:0;background:var(--paper);color:var(--ink);font:16px/1.55 system-ui,sans-serif;padding:24px 16px}}
main{{max-width:640px;margin:0 auto;background:var(--surface);border:1px solid var(--rule);border-radius:14px;padding:22px}}
h1{{margin:0 0 10px;font-size:26px;line-height:1.15}}table{{width:100%;border-collapse:collapse;margin:12px 0}}th,td{{text-align:left;padding:7px 4px;border-top:1px solid var(--rule);vertical-align:top}}
th{{color:var(--steel);font-weight:500;width:36%}}code{{word-break:break-all;font-size:13px}}.note{{color:var(--steel);font-size:14px}}a{{color:var(--seal)}}
.badge{{display:inline-block;font-weight:600;padding:5px 10px;border-radius:999px;margin:0}}.ok{{background:color-mix(in srgb,var(--ok) 15%,transparent);color:var(--ok)}}.bad{{background:color-mix(in srgb,var(--bad) 15%,transparent);color:var(--bad)}}
.btn{{display:inline-block;padding:10px 14px;border-radius:8px;background:var(--seal);color:var(--on);text-decoration:none;font-weight:600;margin:4px 6px 0 0}}.btn.alt{{background:transparent;color:var(--seal);border:1.5px solid var(--seal)}}
.brand{{font-weight:600;color:var(--steel);font-size:13px;letter-spacing:.06em;text-transform:uppercase;margin-bottom:8px}}</style></head>
<body><main><div class="brand">Privi ChainFlow · verified label</div>{body}</main></body></html>"""


def add_routes(mcp, store: LotStore, settings, onchain: Callable[[str, dict], dict], public_url: str,
               chainflow_url: str = "https://chainflow.privishine.info") -> None:

    @mcp.custom_route("/api/chainflow/key", methods=["POST", "OPTIONS"], include_in_schema=False)
    async def key_check(request: Request) -> JSONResponse:
        if request.method == "OPTIONS":
            return JSONResponse({}, headers=CORS)
        ok = _authorized(_token(request), settings.write_keys)
        return JSONResponse({"valid": ok}, status_code=200 if ok else 401, headers=CORS)

    @mcp.custom_route("/api/chainflow/events", methods=["POST", "OPTIONS"], include_in_schema=False)
    async def record(request: Request) -> JSONResponse:
        if request.method == "OPTIONS":
            return JSONResponse({}, headers=CORS)
        if not _authorized(_token(request), settings.write_keys):
            return JSONResponse({"error": "a manufacturer key is required (Authorization: Bearer <key>)"}, status_code=401, headers=CORS)
        try:
            b = json.loads((await request.body())[:20_000] or b"{}")
            if not isinstance(b, dict):
                raise ValueError("send a JSON object")
            args = {k: str(b.get(k) or "")[:n] for k, n in FIELDS_MAX.items()}
            ev = store.record_event(args["lot_code"], args["event_type"], args["location"], args["actor"],
                                    args["product"], args["quantity"], args["notes"])
        except (ValueError, json.JSONDecodeError) as ex:
            return JSONResponse({"error": str(ex), "event_types": list(EVENT_TYPES)}, status_code=400, headers=CORS)
        return JSONResponse({"recorded": True, "event": ev, "label_url": f"{public_url}/label/{ev['record_hash']}"}, headers=CORS)

    @mcp.custom_route("/api/chainflow/label/{fp}", methods=["GET"], include_in_schema=False)
    async def label_json(request: Request) -> JSONResponse:
        fp = request.path_params["fp"]
        try:
            info = label_info(store, fp, onchain)
        except ValueError as ex:
            return JSONResponse({"found": False, "error": str(ex)}, status_code=400, headers=CORS)
        return JSONResponse(info or {"found": False}, status_code=200 if info else 404, headers=CORS)

    @mcp.custom_route("/label/{fp}", methods=["GET"], include_in_schema=False)
    async def label_page(request: Request) -> Response:
        fp = request.path_params["fp"]
        try:
            info = label_info(store, fp, onchain)
        except ValueError:
            info = None
        return HTMLResponse(_label_page(info, fp, public_url, chainflow_url), status_code=200 if info else 404,
                            headers={"Cache-Control": "no-store"})
