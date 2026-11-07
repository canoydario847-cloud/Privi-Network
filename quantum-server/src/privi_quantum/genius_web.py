# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Quantum - https://priviflow.us - dariocanoy@priviflow.us
"""HTTP routes and pages for Privi GENIUS (see genius.py)."""
from __future__ import annotations

import html
import json

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response

from .genius import ASSET_CLASSES, DASP_DEADLINE, EFFECTIVE_DATE, PLAN, Genius, GeniusError
from .realcheck_web import _JS_B64, _STYLE, _bearer, _json

NOSTORE = {"Cache-Control": "no-store"}


def _err(e: GeniusError) -> JSONResponse:
    return JSONResponse({"error": str(e), "plan": PLAN}, status_code=e.status, headers=NOSTORE)


def _page(title: str, body: str, script: str = "") -> HTMLResponse:
    return HTMLResponse(f"<!DOCTYPE html><html lang=en><head><meta charset=utf-8><title>{html.escape(title)}</title>{_STYLE}"
                        f"</head><body>{body}<script>{_JS_B64}{script}</script></body></html>", headers=NOSTORE)


def _checks_html(checks: dict) -> str:
    rows = "".join(f"<li>{'✅' if f['pass'] else '❌'} <b>{html.escape(f['check'])}</b>: {html.escape(f['detail'])}</li>"
                   for f in checks.get("findings", []))
    return f"<ul>{rows}</ul>"


def register(mcp, gen: Genius, is_admin) -> None:
    route = mcp.custom_route

    def admin_only(fn):
        async def wrapped(request: Request) -> Response:
            if not is_admin(request):
                return JSONResponse({"error": "operator only"}, status_code=403)
            try:
                return JSONResponse(await fn(request, await _json(request)), headers=NOSTORE)
            except (GeniusError, ValueError) as e:
                return _err(e if isinstance(e, GeniusError) else GeniusError(str(e)))
        return wrapped

    @route("/genius/v1/issuers", methods=["POST"], include_in_schema=False)
    @admin_only
    async def issuer_create(_, b):
        return gen.create_issuer(str(b.get("name", "")), int(b.get("paid_days", 30)))

    @route("/genius/v1/issuers/{issuer_id}/license", methods=["POST"], include_in_schema=False)
    @admin_only
    async def issuer_license(request, b):
        return gen.set_license(request.path_params["issuer_id"], str(b.get("status", "")), str(b.get("regulator", "")),
                               str(b.get("source_url", "")))

    @route("/genius/v1/issuers/{issuer_id}/coins", methods=["POST"], include_in_schema=False)
    @admin_only
    async def issuer_coin(request, b):
        return gen.add_coin(request.path_params["issuer_id"], str(b.get("chain", "")), str(b.get("address", "")),
                            str(b.get("symbol", "")), int(b.get("decimals", 6)))

    @route("/genius/v1/issuers/{issuer_id}/extend", methods=["POST"], include_in_schema=False)
    @admin_only
    async def issuer_extend(request, b):
        return gen.extend(request.path_params["issuer_id"], int(b.get("days", 30)))

    # ---- issuer API (issuer key) ----
    @route("/genius/v1/officers", methods=["POST"], include_in_schema=False)
    async def officer_add(request: Request) -> Response:
        b = await _json(request)
        try:
            return JSONResponse(gen.add_officer(gen.issuer_from_key(_bearer(request)), str(b.get("name", "")), str(b.get("role", ""))),
                                headers=NOSTORE)
        except GeniusError as e:
            return _err(e)

    @route("/genius/v1/reports", methods=["POST"], include_in_schema=False)
    async def report_submit(request: Request) -> Response:
        try:
            return JSONResponse(gen.submit(gen.issuer_from_key(_bearer(request)), await _json(request)), headers=NOSTORE)
        except GeniusError as e:
            return _err(e)

    @route("/genius/v1/reports/{report_id}/seal", methods=["POST"], include_in_schema=False)
    async def report_seal(request: Request) -> Response:
        try:
            return JSONResponse(gen.seal(gen.issuer_from_key(_bearer(request)), request.path_params["report_id"]), headers=NOSTORE)
        except GeniusError as e:
            return _err(e)

    @route("/genius/v1/check/{chain}/{address}", methods=["GET"], include_in_schema=False)
    async def check_http(request: Request) -> Response:
        """HTTP form of the check for issuer-plan holders (issuer key); agents use the paid MCP tool."""
        try:
            gen.issuer_from_key(_bearer(request))
            return JSONResponse(gen.check(request.path_params["chain"], request.path_params["address"]), headers=NOSTORE)
        except GeniusError as e:
            return _err(e)

    # ---- officer enrollment ----
    @route("/genius/enroll/{token}", methods=["GET"], include_in_schema=False)
    async def enroll_page(request: Request) -> Response:
        try:
            o = gen.enroll_options(request.path_params["token"])
        except GeniusError as e:
            return _page("Privi GENIUS", f"<h1>Link not valid</h1><p>{html.escape(str(e))}</p>")
        body = (f"<h1>Privi GENIUS</h1><div class=card><p><b>{html.escape(o['officer'])}</b> ({html.escape(o['role'])}), "
                f"{html.escape(o['issuer'])}: set up the passkey you will use to certify monthly reserve reports.</p>"
                "<p class=mute>Use your own phone or laptop. Privi stores only the passkey's public key.</p>"
                "<button class=go id=b>Set up my certification passkey</button><p id=out></p></div>")
        script = f"""const O={json.dumps(o['create'])};document.getElementById('b').onclick=async()=>{{const out=document.getElementById('out');try{{
const c=await navigator.credentials.create({{publicKey:{{...O,challenge:ub64u(O.challenge),user:{{...O.user,id:ub64u(O.user.id)}}}}}});
const r=await fetch(location.pathname+'/finish',{{method:'POST',headers:{{'content-type':'application/json'}},body:JSON.stringify({{id:c.id,rawId:b64u(c.rawId),type:c.type,
response:{{clientDataJSON:b64u(c.response.clientDataJSON),attestationObject:b64u(c.response.attestationObject)}}}})}});
const j=await r.json();out.textContent=r.ok?'Done. You can now certify reserve reports from this device.':(j.error||'Failed')}}catch(e){{out.textContent='Not completed: '+e.message}}}};"""
        return _page("Privi GENIUS: officer setup", body, script)

    @route("/genius/enroll/{token}/finish", methods=["POST"], include_in_schema=False)
    async def enroll_finish(request: Request) -> Response:
        try:
            return JSONResponse(gen.enroll_finish(request.path_params["token"], await _json(request)), headers=NOSTORE)
        except GeniusError as e:
            return _err(e)

    # ---- certification page (CEO / CFO / examiner) ----
    @route("/genius/certify/{report_id}", methods=["GET"], include_in_schema=False)
    async def certify_page(request: Request) -> Response:
        try:
            v = gen.certify_view(request.path_params["report_id"])
        except GeniusError as e:
            return _page("Privi GENIUS", f"<h1>Report not found</h1><p>{html.escape(str(e))}</p>")
        b = v["body"]
        assets = "".join(f"<li>{html.escape(ASSET_CLASSES.get(a['class'], {}).get('label', a['class']))}: ${a['value_usd']:,.2f}</li>"
                         for a in b["reserves"])
        opts = "".join(f"<option value='{o['officer_id']}'>{html.escape(o['name'])} ({o['role']}){' ✓ signed' if o['signed'] else ''}</option>"
                       for o in v["officers"])
        body = (f"<h1>Certify the {html.escape(v['period'])} reserve report</h1><div class=card><p><b>{html.escape(v['issuer'])}</b></p>"
                f"<p>Outstanding: <b>${b['outstanding_total_usd']:,.2f}</b><br>Reserves: <b>${v['checks']['reserves_total_usd']:,.2f}</b>"
                f" (coverage {v['checks']['coverage_ratio']})</p><ul>{assets}</ul>{_checks_html(v['checks'])}"
                f"<p class=mute>Report SHA-256: <code>{v['body_sha256']}</code></p></div>"
                f"<div class=card><label>I am</label><select id=o>{opts}</select>"
                "<button class=yes id=c>I certify this report is accurate</button><p id=out class=mute></p></div>")
        script = """document.getElementById('c').onclick=async()=>{const out=document.getElementById('out'),o=document.getElementById('o').value;try{
const op=await (await fetch(location.pathname+'/options?officer='+o)).json();if(!op.get)throw new Error(op.error||'unavailable');
const a=await navigator.credentials.get({publicKey:{...op.get,challenge:ub64u(op.get.challenge)}});
const r=await fetch(location.pathname+'/sign?officer='+o,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({id:a.id,rawId:b64u(a.rawId),type:a.type,
response:{clientDataJSON:b64u(a.response.clientDataJSON),authenticatorData:b64u(a.response.authenticatorData),signature:b64u(a.response.signature)}})});
const j=await r.json();out.textContent=r.ok?('Certified by '+j.certified_by+' ('+j.role+').'):(j.error||'Failed')}catch(e){out.textContent='Not completed: '+e.message}};"""
        return _page("Privi GENIUS: certify", body, script)

    @route("/genius/certify/{report_id}/options", methods=["GET"], include_in_schema=False)
    async def certify_options(request: Request) -> Response:
        try:
            return JSONResponse(gen.certify_options(request.path_params["report_id"], request.query_params.get("officer", "")),
                                headers=NOSTORE)
        except GeniusError as e:
            return _err(e)

    @route("/genius/certify/{report_id}/sign", methods=["POST"], include_in_schema=False)
    async def certify_sign(request: Request) -> Response:
        try:
            return JSONResponse(gen.certify(request.path_params["report_id"], request.query_params.get("officer", ""),
                                            await _json(request)), headers=NOSTORE)
        except GeniusError as e:
            return _err(e)

    # ---- public sealed reports ----
    @route("/genius/reports/{report_id}.json", methods=["GET"], include_in_schema=False)
    async def report_json(request: Request) -> Response:
        try:
            return JSONResponse(gen.public_report(request.path_params["report_id"]),
                                headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "max-age=60"})
        except GeniusError as e:
            return _err(e)

    @route("/genius/reports/{report_id}", methods=["GET"], include_in_schema=False)
    async def report_page(request: Request) -> Response:
        try:
            r = gen.public_report(request.path_params["report_id"])
        except GeniusError as e:
            return _page("Privi GENIUS", f"<h1>Report not found</h1><p>{html.escape(str(e))}</p>")
        b, c = r["report"], r["checks"]
        verdict = "All checks pass" if c["all_pass"] else "Some checks did not pass"
        body = (f"<h1>{html.escape(r['issuer'])}: {html.escape(r['period'])} reserve report</h1>"
                f"<div class=card><p><b>{verdict}</b>. Sealed {html.escape(r['sealed_at'])}.</p>"
                f"<p>Outstanding ${b['outstanding_total_usd']:,.2f} · Reserves ${c['reserves_total_usd']:,.2f} · Coverage {c['coverage_ratio']}</p>"
                f"{_checks_html(c)}<p class=mute>Examination: {html.escape(b['examination']['firm'] or 'not recorded')}. "
                f"Signed receipt: <a href='{r['receipt_url']}'>{html.escape(r['receipt']['id'])}</a> (Ed25519 + ML-DSA-87). "
                f"<a href='{request.url.path}.json'>JSON</a></p></div>"
                f"<p class=mute>GENIUS Act in force {EFFECTIVE_DATE}; permitted-issuer rule for service providers from {DASP_DEADLINE}. "
                "Privi records mechanical checks and signatures; this is not a license, an examination or a legal opinion.</p>")
        return _page(f"{r['issuer']} reserve report {r['period']}", body)
