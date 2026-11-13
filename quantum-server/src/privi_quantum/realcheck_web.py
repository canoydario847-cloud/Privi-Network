# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Quantum - https://priviflow.us - dariocanoy@priviflow.us
"""HTTP routes and pages for Privi RealCheck (see realcheck.py)."""
from __future__ import annotations

import html
import json
import os

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response

from .realcheck import CHANNELS, PRICE, RealCheck, RealCheckError

NOSTORE = {"Cache-Control": "no-store"}

_STYLE = """<meta name="viewport" content="width=device-width,initial-scale=1"><style>
body{font:17px/1.5 system-ui,-apple-system,sans-serif;max-width:560px;margin:0 auto;padding:28px 18px;color:#0f172a;background:#f8fafc}
.card{background:#fff;border:1px solid #e2e8f0;border-radius:14px;padding:20px;margin:14px 0}
button{font:inherit;font-weight:600;border:0;border-radius:12px;padding:14px;width:100%;margin:6px 0;cursor:pointer}
.yes{background:#15803d;color:#fff}.no{background:#b91c1c;color:#fff}.go{background:#5b21b6;color:#fff}
.mute{color:#475569;font-size:15px}input,select,textarea{font:inherit;width:100%;padding:10px;border:1px solid #cbd5e1;border-radius:10px;margin:4px 0 10px;box-sizing:border-box}
#out{white-space:pre-wrap;font-size:15px}code{word-break:break-all}
</style>"""

_JS_B64 = """
const b64u=b=>btoa(String.fromCharCode(...new Uint8Array(b))).replace(/\\+/g,'-').replace(/\\//g,'_').replace(/=+$/,'');
const ub64u=s=>Uint8Array.from(atob(s.replace(/-/g,'+').replace(/_/g,'/')+'='.repeat((4-s.length%4)%4)),c=>c.charCodeAt(0));
"""


def _page(title: str, body: str, script: str = "") -> HTMLResponse:
    return HTMLResponse(f"<!DOCTYPE html><html lang=en><head><meta charset=utf-8><title>{html.escape(title)}</title>{_STYLE}"
                        f"<link rel=manifest href=/real/manifest.webmanifest><meta name=theme-color content=#0f172a></head><body>{body}<script>{_JS_B64}{script}</script></body></html>", headers=NOSTORE)


def _err(e: RealCheckError) -> JSONResponse:
    return JSONResponse({"error": str(e), "plan": PRICE}, status_code=e.status, headers=NOSTORE)


def _bearer(request: Request) -> str:
    a = request.headers.get("authorization", "")
    return a[7:].strip() if a.lower().startswith("bearer ") else ""


async def _json(request: Request) -> dict:
    try:
        b = await request.json()
        return b if isinstance(b, dict) else {}
    except ValueError:
        return {}


def register(mcp, real: RealCheck, is_admin) -> None:
    route = mcp.custom_route

    # ---- operator: activate a paying organization ----
    @route("/real/v1/orgs", methods=["POST"], include_in_schema=False)
    async def org_create(request: Request) -> Response:
        if not is_admin(request):
            return JSONResponse({"error": "operator only"}, status_code=403)
        b = await _json(request)
        try:
            return JSONResponse(real.create_org(str(b.get("name", "")), int(b.get("seats", 25)), int(b.get("paid_days", 30))),
                                headers=NOSTORE)
        except (RealCheckError, ValueError) as e:
            return _err(e if isinstance(e, RealCheckError) else RealCheckError(str(e)))

    @route("/real/v1/orgs/{org_id}/extend", methods=["POST"], include_in_schema=False)
    async def org_extend(request: Request) -> Response:
        if not is_admin(request):
            return JSONResponse({"error": "operator only"}, status_code=403)
        b = await _json(request)
        try:
            return JSONResponse(real.extend(request.path_params["org_id"], int(b.get("days", 30))), headers=NOSTORE)
        except (RealCheckError, ValueError) as e:
            return _err(e if isinstance(e, RealCheckError) else RealCheckError(str(e)))

    # ---- organization API (org key) ----
    @route("/real/v1/members", methods=["GET", "POST"], include_in_schema=False)
    async def members(request: Request) -> Response:
        try:
            org = real.org_from_key(_bearer(request))
            if request.method == "GET":
                return JSONResponse({"members": real.members(org), "paid_until": org["paid_until"]}, headers=NOSTORE)
            b = await _json(request)
            return JSONResponse(real.add_member(org, str(b.get("name", "")), str(b.get("role", ""))), headers=NOSTORE)
        except RealCheckError as e:
            return _err(e)

    @route("/real/v1/members/{member_id}", methods=["DELETE"], include_in_schema=False)
    async def member_remove(request: Request) -> Response:
        try:
            return JSONResponse(real.remove_member(real.org_from_key(_bearer(request)), request.path_params["member_id"]))
        except RealCheckError as e:
            return _err(e)

    @route("/real/v1/checks", methods=["POST"], include_in_schema=False)
    async def check_create(request: Request) -> Response:
        b = await _json(request)
        try:
            org = real.org_from_key(_bearer(request))
            return JSONResponse(real.create_check(org, str(b.get("member_id", "")), str(b.get("requested_by", "")),
                                                  str(b.get("reason", "")), str(b.get("channel", "other"))), headers=NOSTORE)
        except RealCheckError as e:
            return _err(e)

    @route("/real/v1/checks/{check_id}", methods=["GET"], include_in_schema=False)
    async def check_status(request: Request) -> Response:
        try:
            return JSONResponse(real.status(real.org_from_key(_bearer(request)), request.path_params["check_id"]),
                                headers=NOSTORE)
        except RealCheckError as e:
            return _err(e)

    # ---- enrollment page (the person, on their own phone) ----
    @route("/real/enroll/{token}", methods=["GET"], include_in_schema=False)
    async def enroll_page(request: Request) -> Response:
        try:
            o = real.enroll_options(request.path_params["token"])
        except RealCheckError as e:
            return _page("Privi RealCheck", f"<h1>Link not valid</h1><p>{html.escape(str(e))}</p>")
        body = (f"<h1>Privi RealCheck</h1><div class=card><p><b>{html.escape(o['member'])}</b>, "
                f"{html.escape(o['organization'])} uses RealCheck so nobody can pretend to be you on a call, text or email.</p>"
                "<p class=mute>Set it up on <b>your own phone</b>. You'll use Face ID, your fingerprint or your screen lock. "
                "Privi stores only a public key, never your face or fingerprint.</p>"
                "<button class=go id=b>Set up on this device</button><p id=out></p></div>")
        script = f"""const O={json.dumps(o['create'])};
document.getElementById('b').onclick=async()=>{{const out=document.getElementById('out');try{{
const pk={{...O,challenge:ub64u(O.challenge),user:{{...O.user,id:ub64u(O.user.id)}}}};
const c=await navigator.credentials.create({{publicKey:pk}});
const r=await fetch(location.pathname+'/finish',{{method:'POST',headers:{{'content-type':'application/json'}},body:JSON.stringify({{id:c.id,rawId:b64u(c.rawId),type:c.type,
response:{{clientDataJSON:b64u(c.response.clientDataJSON),attestationObject:b64u(c.response.attestationObject)}}}})}});
const j=await r.json();out.textContent=r.ok?'Done. When your company sends you a RealCheck, open it on this device.':(j.error||'Failed');
}}catch(e){{out.textContent='Not completed: '+e.message}}}};"""
        return _page("Privi RealCheck: set up", body, script)

    @route("/real/enroll/{token}/finish", methods=["POST"], include_in_schema=False)
    async def enroll_finish(request: Request) -> Response:
        try:
            return JSONResponse(real.enroll_finish(request.path_params["token"], await _json(request)), headers=NOSTORE)
        except RealCheckError as e:
            return _err(e)

    # ---- approve page (the person being checked) ----
    @route("/real/c/{check_id}", methods=["GET"], include_in_schema=False)
    async def approve_page(request: Request) -> Response:
        try:
            c = real.public_check(request.path_params["check_id"])
        except RealCheckError as e:
            return _page("Privi RealCheck", f"<h1>Check not found</h1><p>{html.escape(str(e))}</p>")
        if c["status"] != "pending":
            return _page("Privi RealCheck", f"<h1>This check is {html.escape(c['status'])}</h1>")
        body = (f"<h1>Is this really you, {html.escape(c['member'])}?</h1><div class=card>"
                f"<p><b>{html.escape(c['requested_by'])}</b> at {html.escape(c['organization'])} got a "
                f"<b>{html.escape(c['channel'])}</b> that says it's from you:</p><p>“{html.escape(c['reason'])}”</p>"
                "<button class=yes id=y>Yes, that was me</button><button class=no id=n>No, that's not me</button>"
                "<p id=out class=mute>Confirm with Face ID, your fingerprint or your screen lock.</p></div>")
        script = """async function go(d){const out=document.getElementById('out');try{
const o=(await (await fetch(location.pathname+'/options?decision='+d)).json());if(!o.get)throw new Error(o.error||'unavailable');
const a=await navigator.credentials.get({publicKey:{...o.get,challenge:ub64u(o.get.challenge)}});
const r=await fetch(location.pathname+'/decide?decision='+d,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({id:a.id,rawId:b64u(a.rawId),type:a.type,
response:{clientDataJSON:b64u(a.response.clientDataJSON),authenticatorData:b64u(a.response.authenticatorData),signature:b64u(a.response.signature)}})});
const j=await r.json();out.textContent=r.ok?(j.result==='confirmed'?'Confirmed. They know it was really you.':'Reported as impersonation. Thank you.'):(j.error||'Failed');
}catch(e){out.textContent='Not completed: '+e.message}}
document.getElementById('y').onclick=()=>go('confirm');document.getElementById('n').onclick=()=>go('deny');"""
        return _page("Privi RealCheck", body, script)

    @route("/real/c/{check_id}/options", methods=["GET"], include_in_schema=False)
    async def approve_options(request: Request) -> Response:
        try:
            return JSONResponse(real.decide_options(request.path_params["check_id"], request.query_params.get("decision", "")),
                                headers=NOSTORE)
        except RealCheckError as e:
            return _err(e)

    @route("/real/c/{check_id}/decide", methods=["POST"], include_in_schema=False)
    async def approve_decide(request: Request) -> Response:
        try:
            return JSONResponse(real.decide(request.path_params["check_id"], request.query_params.get("decision", ""),
                                            await _json(request)), headers=NOSTORE)
        except RealCheckError as e:
            return _err(e)

    # ---- Android app (Trusted Web Activity, package us.priviflow.realcheck) ----
    @route("/.well-known/assetlinks.json", methods=["GET"], include_in_schema=False)
    async def assetlinks(_: Request) -> Response:
        fps = [f.strip().upper() for f in os.getenv("REALCHECK_ANDROID_SHA256", "").split(",") if f.strip()]
        body = [{"relation": ["delegate_permission/common.handle_all_urls"],
                 "target": {"namespace": "android_app", "package_name": "us.priviflow.realcheck",
                            "sha256_cert_fingerprints": fps}}] if fps else []
        from .webapp import asset_statements
        body = body + asset_statements()            # the Privi Quantum app (us.priviflow.quantum)
        return JSONResponse(body, headers={"Cache-Control": "max-age=300"})

    @route("/real/manifest.webmanifest", methods=["GET"], include_in_schema=False)
    async def web_manifest(_: Request) -> Response:
        return JSONResponse({"name": "Privi RealCheck", "short_name": "RealCheck", "start_url": "/real?source=pwa",
                             "scope": "/real", "display": "standalone", "background_color": "#f8fafc",
                             "theme_color": "#0f172a", "description": "Confirm it's really them before you act.",
                             "icons": []},
                            media_type="application/manifest+json")

    # ---- console for the finance / front desk (org key kept in this browser only) ----
    @route("/real", methods=["GET"], include_in_schema=False)
    async def console(_: Request) -> Response:
        opts = "".join(f"<option>{c}</option>" for c in CHANNELS)
        body = ("<h1>Privi RealCheck</h1><p class=mute>Someone claims to be a colleague and wants money, data or access? "
                "Check it's really them before you act. Only their own enrolled phone can confirm.</p>"
                "<div class=card><label>Organization key</label><input id=k type=password placeholder='rck_...'>"
                "<button class=go id=load>Load my people</button></div>"
                "<div class=card id=f hidden><label>Who do they claim to be?</label><select id=m></select>"
                f"<label>How did the request arrive?</label><select id=ch>{opts}</select>"
                "<label>Your name</label><input id=by><label>What are they asking for?</label>"
                "<textarea id=r rows=2 placeholder='Wire $25,000 to a new vendor today'></textarea>"
                "<button class=go id=go>Send RealCheck</button><p id=out></p></div>"
                f"<p class=mute>{PRICE['plan']}: ${PRICE['usd_per_month']}/month for up to {PRICE['seats']} people. "
                f"<a href='{PRICE['pay']}'>Buy</a></p>")
        script = """const $=i=>document.getElementById(i);try{$('k').value=localStorage.getItem('rck')||''}catch(e){}
const H=()=>({'authorization':'Bearer '+$('k').value,'content-type':'application/json'});
$('load').onclick=async()=>{try{localStorage.setItem('rck',$('k').value)}catch(e){}const r=await fetch('/real/v1/members',{headers:H()});const j=await r.json();
if(!r.ok){alert(j.error);return}$('m').innerHTML=j.members.filter(x=>x.enrolled).map(x=>`<option value="${x.member_id}">${x.name}${x.role?' ('+x.role+')':''}</option>`).join('');$('f').hidden=false};
$('go').onclick=async()=>{const out=$('out');const r=await fetch('/real/v1/checks',{method:'POST',headers:H(),body:JSON.stringify({member_id:$('m').value,channel:$('ch').value,requested_by:$('by').value,reason:$('r').value})});
const j=await r.json();if(!r.ok){out.textContent=j.error;return}
out.textContent='Send this link to '+j.member+' on a channel you already trust (NOT the one the request came on):\\n'+j.approve_url+'\\n\\nWaiting...';
const t=setInterval(async()=>{const s=await (await fetch('/real/v1/checks/'+j.check_id,{headers:H()})).json();
if(s.status!=='pending'){clearInterval(t);out.textContent=s.verdict+(s.receipt_url?'\\nReceipt: '+s.receipt_url:'')}},3000)};"""
        return _page("Privi RealCheck", body, script)
