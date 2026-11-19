"""Privi Universe — prelaunch navigation portal. Stdlib-only and read-only.

Links to TWO known Render demos, and Github source references for products
whose independent live endpoints have not been verified. Does not collect data,
authorize payments, execute tools, or claim that production services are live.
"""
from __future__ import annotations
import json
import os
import importlib.util
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

_spec = importlib.util.spec_from_file_location(
    "privi_universe_status_monitor", Path(__file__).with_name("status_monitor.py"))
if _spec is None or _spec.loader is None:
    raise RuntimeError("Privi Universe status monitor unavailable")
_status_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_status_mod)
MONITOR = _status_mod.StatusMonitor()
_auth_spec = importlib.util.spec_from_file_location(
    "privi_universe_account_access", Path(__file__).with_name("account_access.py"))
if _auth_spec is None or _auth_spec.loader is None:
    raise RuntimeError("Privi account verifier unavailable")
account_access = importlib.util.module_from_spec(_auth_spec)
_auth_spec.loader.exec_module(account_access)

PRODUCTS = [
    {"id":"one","number":"01","name":"Privi ONE","tag":"AGENT INTELLIGENCE","summary":"Cost-aware routes, Guard inspection and synthetic action receipts.","status":"INTERACTIVE DEMO","mode":"demo","href":"https://privi-one-demo.onrender.com/","symbol":"✦"},
    {"id":"outcome","number":"02","name":"OutcomeGrid","tag":"AGENT TRUST","summary":"Independent-review scenarios and evidence-aware agent reputation.","status":"INTERACTIVE DEMO","mode":"demo","href":"https://privi-outcomegrid-demo.onrender.com/","symbol":"◎"},
    {"id":"callproof","number":"03","name":"CallProof","tag":"AUTHORIZATION","summary":"Agent call authorization and receipt design; review the pilot scope.","status":"SOURCE / PILOT","mode":"reference","href":"https://github.com/canoydario847-cloud/Privi-Network/blob/main/marketing/CALLPROOF_ENTERPRISE_PILOT_2026-11.md","symbol":"◇"},
    {"id":"guard","number":"04","name":"Privi Guard","tag":"RISK INSPECTION","summary":"Prompt and tool risk inspection engine; source reference.","status":"SOURCE REFERENCE","mode":"reference","href":"https://github.com/canoydario847-cloud/Privi-Network/blob/main/ledger-server/src/privi_ledger/guard_engine.py","symbol":"⬡"},
    {"id":"ledger","number":"05","name":"Privi Ledger","tag":"EVIDENCE & AUDIT","summary":"Ledger and scanner implementation; source reference, not a verified live chain.","status":"SOURCE REFERENCE","mode":"reference","href":"https://github.com/canoydario847-cloud/Privi-Network/tree/main/ledger-server","symbol":"⌁"},
]

def render_card(p):
    import html
    esc = lambda t: html.escape(str(t),quote=True)
    status_class = "live" if p["mode"] == "demo" else "reference"
    verb = "Launch sandbox ↗" if p["mode"]=="demo" else "Explore reference ↗"
    return f'''<article class="module" id="{esc(p["id"])}">
      <div class="module-top"><span class="num">{esc(p["number"])}/05</span><span class="state {status_class}">{esc(p["status"])}</span></div>
      <div class="glyph" aria-hidden="true">{esc(p["symbol"])}</div>
      <div class="tag">{esc(p["tag"])}</div><h3>{esc(p["name"])}</h3>
      <p>{esc(p["summary"])}</p>
      <a class="go" target="_blank" rel="noopener noreferrer" href="{esc(p["href"])}">{verb}<span aria-hidden="true"> ↗</span></a>
    </article>'''.replace(" ↗</a>","</a>") # decorative right arrow in span

CSS = r"""
:root{color-scheme:dark;--ink:#edf8ff;--muted:#99afd0;--cyan:#6bf7f1;--purple:#ab9cff;--line:rgba(127,190,255,.20)}
*{box-sizing:border-box}html{scroll-behavior:smooth}
body{margin:0;background:#040818;color:var(--ink);font:15px/1.65 system-ui,-apple-system,Segoe UI,sans-serif;min-height:100vh;overflow-x:hidden}
body:before{content:"";pointer-events:none;position:fixed;inset:0;background:radial-gradient(ellipse at 79% 7%,rgba(86,55,179,.30),transparent 48%),radial-gradient(ellipse at 4% 48%,rgba(19,129,147,.24),transparent 50%),linear-gradient(180deg,#040918,#060a1c 60%,#040712);z-index:-2}
body:after{content:"";pointer-events:none;position:fixed;inset:0;background-image:radial-gradient(1px 1px at 20% 40%,white 99%,transparent),radial-gradient(1px 1px at 80% 10%,#cffaff 99%,transparent),radial-gradient(1px 1px at 54% 80%,white 99%,transparent),radial-gradient(2px 2px at 90% 56%,#b3e7ff 99%,transparent);background-size:269px 260px,377px 320px,461px 410px,582px 540px;opacity:.46;z-index:-1}
.shell{max-width:1180px;margin:auto;padding:0 24px 75px}
header{display:flex;align-items:center;justify-content:space-between;gap:20px;min-height:84px;border-bottom:1px solid var(--line);flex-wrap:wrap}
.logo{font-weight:850;font-size:15px;letter-spacing:.20em;color:var(--ink);text-decoration:none;display:flex;align-items:center;gap:10px}
.logo span{display:grid;place-items:center;width:36px;height:36px;background:linear-gradient(125deg,rgba(95,245,242,.28),rgba(129,99,251,.28));border:1px solid rgba(95,245,242,.54);color:var(--cyan);border-radius:11px;box-shadow:0 0 28px rgba(95,245,242,.13)}
.links{display:flex;gap:17px;flex-wrap:wrap}.links a{font-size:11px;letter-spacing:.12em;color:#b9cce6;text-decoration:none;font-weight:700}
.links a:hover,.links a:focus-visible{color:var(--cyan)}
.mode{font:700 10px/1.4 ui-monospace,monospace;letter-spacing:.10em;color:var(--cyan);white-space:nowrap}.mode:before{content:"";display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--cyan);box-shadow:0 0 14px var(--cyan);margin-right:8px}
.hero{display:grid;grid-template-columns:1.12fr .88fr;gap:20px;align-items:center;padding:62px 0 45px;min-height:460px}
.overline,.tag{font:750 11px/1.8 ui-monospace,monospace;color:var(--cyan);letter-spacing:.18em}
.overline:before{content:"";display:inline-block;background:var(--cyan);width:24px;height:1px;vertical-align:middle;margin-right:12px}
h1{font-size:clamp(45px,7vw,84px);line-height:1.025;letter-spacing:-.065em;font-weight:770;margin:18px 0 25px}
.grad{background:linear-gradient(105deg,#f2fcff 10%,#6bf7f1 54%,#aea0ff);-webkit-background-clip:text;background-clip:text;color:transparent}
.lead{color:#b7c7e2;max-width:590px;font-size:16px;margin:0 0 24px}
.primary{display:inline-flex;gap:12px;align-items:center;padding:14px 22px;background:linear-gradient(105deg,#68eee9,#9bafff);border:1px solid rgba(144,239,252,.54);border-radius:10px;color:#071023;text-decoration:none;font:850 12px/1 system-ui;letter-spacing:.09em;text-transform:uppercase}
.primary:hover{filter:brightness(1.1);transform:translateY(-1px)}
.hero-art{height:360px;position:relative;display:grid;place-items:center;isolation:isolate}
.ring{position:absolute;border-radius:50%;width:min(94%,400px);aspect-ratio:1;border:1px solid rgba(95,237,246,.34);transform:rotate(28deg) scaleY(.63);box-shadow:0 0 47px rgba(82,167,255,.08)}
.ring:nth-child(2){width:min(77%,330px);transform:rotate(110deg) scaleY(.63);border-color:rgba(179,141,255,.4)}
.ring:nth-child(3){width:min(56%,220px);transform:rotate(-30deg) scaleY(.63);border-color:rgba(95,237,246,.3)}
.world{width:180px;height:180px;border-radius:50%;display:grid;place-items:center;position:relative;z-index:2;font-size:12px;letter-spacing:.25em;font-weight:900;text-align:center;background:radial-gradient(circle at 31% 22%,#45cad7,#29559d 35%,#251953 65%,#070d23 99%);box-shadow:inset -20px -17px 35px rgba(0,3,16,.75),0 0 90px rgba(102,108,238,.38),0 0 140px rgba(56,205,250,.13)}
.dot{width:8px;height:8px;background:var(--cyan);border-radius:50%;box-shadow:0 0 13px var(--cyan);position:absolute;right:23%;top:13%}
.meta{display:flex;gap:30px;flex-wrap:wrap;margin-top:27px}.meta b{display:block;font-size:23px;line-height:1.2}.meta span{font:11px ui-monospace,monospace;color:var(--muted);letter-spacing:.07em}
.section-top{display:flex;justify-content:space-between;align-items:end;gap:12px;flex-wrap:wrap;margin:28px 0 23px}
.section-top h2{font-size:clamp(25px,4vw,37px);line-height:1.1;letter-spacing:-.04em;margin:7px 0}
.section-top p{max-width:440px;color:var(--muted);margin:0}
.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:17px}
.module{position:relative;border-radius:17px;border:1px solid var(--line);background:linear-gradient(145deg,rgba(18,33,64,.9),rgba(8,16,34,.9));padding:23px;min-height:310px;display:flex;flex-direction:column;box-shadow:inset 0 1px rgba(200,238,255,.04)}
.module:before{content:"";position:absolute;top:-1px;left:25px;width:64px;height:2px;background:linear-gradient(90deg,#69f9f1,transparent)}
.module:hover{border-color:rgba(108,244,240,.46);transform:translateY(-3px)}
.module-top{display:flex;justify-content:space-between;align-items:center;gap:8px}.num{color:#7d93b2;font:11px ui-monospace,monospace}
.state{font:700 9px/1.45 ui-monospace,monospace;letter-spacing:.07em;padding:6px 7px;border-radius:7px;border:1px solid rgba(129,167,210,.25);color:#b5c7e4;text-align:right}
.state.live{color:#82f4ee;border-color:rgba(95,244,233,.36);background:rgba(49,170,175,.09)}
.glyph{font-size:38px;color:#9af6ef;margin:18px 0 4px;text-shadow:0 0 26px rgba(100,249,238,.29)}
.module h3{font-size:24px;letter-spacing:-.03em;line-height:1.2;margin:3px 0 7px}
.module p{color:var(--muted);font-size:13px;margin:0 0 21px}
.go{margin-top:auto;color:#98f8f2;font:800 11px system-ui;text-transform:uppercase;letter-spacing:.1em;text-decoration:none}
.go:hover{text-decoration:underline}.go:focus-visible,.primary:focus-visible,a:focus-visible{outline:2px solid var(--cyan);outline-offset:4px}
.info{margin-top:27px;border:1px solid rgba(130,168,227,.19);border-radius:14px;background:rgba(12,22,48,.72);padding:23px}.info h2{margin:0 0 9px;font-size:19px}.info p{margin:0;color:var(--muted)}
footer{border-top:1px solid var(--line);margin-top:65px;padding-top:24px;color:var(--muted);font-size:12px;display:flex;justify-content:space-between;gap:20px;flex-wrap:wrap}footer a{color:#91f4f0}

.status-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin:17px 0}
.status-card{background:rgba(14,29,59,.72);border:1px solid var(--line);border-radius:13px;padding:19px}
.status-card h3{margin:0 0 8px;font-size:17px}
.status-indicator{display:inline-flex;align-items:center;gap:7px;color:#c7d4ea;font:700 12px ui-monospace,monospace}
.status-indicator:before{content:"";height:8px;width:8px;border-radius:50%;background:#e9c17c;box-shadow:0 0 8px rgba(233,193,124,.33)}
.status-indicator.responding{color:#7cf1e8}.status-indicator.responding:before{background:#7cf1e8;box-shadow:0 0 11px rgba(124,241,232,.6)}
.meta-label{color:var(--muted);font-size:12px}
.access-row{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:13px;margin:15px 0}
.access-cell{padding:16px;border:1px solid var(--line);border-radius:10px;background:rgba(14,29,59,.55)}
.access-cell b{display:block;margin-bottom:5px;color:#c7f5ff}
.access-cell span{font-size:12px;color:var(--muted)}
@media(max-width:650px){.status-grid,.access-row{grid-template-columns:1fr}}

@media(max-width:850px){.hero{grid-template-columns:1fr;min-height:unset;padding:44px 0 20px}.hero-art{height:260px;max-width:430px;width:100%;margin:auto}.world{height:145px;width:145px}.grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:540px){.shell{padding:0 16px 55px}header{padding:14px 0}.links{gap:12px}.grid{grid-template-columns:1fr}.hero-art{height:220px}h1{font-size:53px}.meta{gap:20px}.module{min-height:265px}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}.module:hover,.primary:hover{transform:none}}
"""

HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="description" content="Privi Universe: explore prelaunch AI agent demos and verified source references from Privi World Corp."><title>Privi Universe — Mission Control</title><style>""" + CSS + """</style></head><body>
<div class="shell"><header><a href="/" class="logo"><span>✦</span> PRIVI UNIVERSE</a>
<nav class="links" aria-label="Main navigation"><a href="#missions">EXPLORE TOOLS</a><a href="#status">STATUS</a><a href="#access">ACCOUNT</a><a href="#about">THE NETWORK</a><a href="https://github.com/canoydario847-cloud/Privi-Network" target="_blank" rel="noopener noreferrer">SOURCE ↗</a></nav>
<div class="mode">PRELAUNCH · DEMO PORTAL</div></header>
<main><section class="hero"><div><div class="overline">PRIVI WORLD CORP / DIGITAL FRONTIER</div><h1>One universe.<br><span class="grad">Infinite potential.</span></h1>
<p class="lead">The command center for Privi's agent intelligence, verifiable outcomes, and emerging trust infrastructure. Explore working sandbox demonstrations and inspect the research behind the network.</p>
<a class="primary" href="#missions">Enter the universe ↗</a>
<div class="meta"><div><b>02</b><span>Interactive demos</span></div><div><b>05</b><span>Featured modules</span></div><div><b>00</b><span>Live token operations</span></div></div></div>
<div class="hero-art" aria-hidden="true"><div class="ring"></div><div class="ring"></div><div class="ring"></div><div class="world">PRIVI<br>UNIVERSE</div><div class="dot"></div></div></section>
<section id="missions"><div class="section-top"><div><div class="overline">THE PRivi ECOSYSTEM / NAVIGATION</div><h2>Choose your mission.</h2></div>
<p>Live links are labeled as demos. Other modules link to source material rather than claiming public production availability.</p></div>
<div class="grid">""" + "\n".join(render_card(p) for p in PRODUCTS) + """</div></section>

<section id="status" class="info" aria-labelledby="status-heading">
  <div class="overline">OPERATIONS / READ-ONLY HEALTH OBSERVATION</div>
  <h2 id="status-heading">Mission status.</h2>
  <p>Checks whether two prelaunch demo health endpoints respond. This is not proof of uptime, production readiness, payment processing, or PRVI mainnet health.</p>
  <div class="status-grid">
    <div class="status-card"><h3>Privi ONE</h3><span class="status-indicator" id="status-one">Not yet checked</span><div class="meta-label">Sandbox health endpoint</div></div>
    <div class="status-card"><h3>OutcomeGrid</h3><span class="status-indicator" id="status-outcome">Not yet checked</span><div class="meta-label">Sandbox health endpoint</div></div>
  </div>
  <p class="meta-label" id="status-updated" aria-live="polite">Status updates are cached for 90 seconds. CallProof, Guard and Ledger are source references, not monitored production services.</p>
</section>
<section id="access" class="info" aria-labelledby="access-heading">
  <div class="overline">PRIVI PASSPORT / ACCESS ROADMAP</div>
  <h2 id="access-heading">One future account. No imaginary privileges.</h2>
  <p>Unified login and paid account entitlements are not connected to this portal. No passwords, session tokens or payments are collected here. Sandbox demos remain public.</p>
  <div class="access-row">
    <div class="access-cell"><b>Guest</b><span>Access public demo experiences and source references</span></div>
    <div class="access-cell"><b>Account holder</b><span>Not enabled — requires a verified identity provider</span></div>
    <div class="access-cell"><b>Privi Pro</b><span>Not enabled — requires trusted server-side entitlement verification</span></div>
  </div>
  <p class="meta-label">Future controls must verify identity, payment entitlements, revocation, and cross-product access on the server. This page cannot authorize protected services.</p>
  <p class="meta-label" id="auth-readiness" aria-live="polite">Checking identity and entitlement readiness…</p>
</section>

<section class="info" id="about"><h2>Built for accountable intelligence.</h2><p>Privi Universe is a navigation portal—not an exchange, wallet, production blockchain explorer, or login system. Privi ONE and OutcomeGrid are synthetic demonstrations. The other links are reference material and pilot documentation. No payment, model call, customer information, or PRVI operation occurs on this portal.</p></section>
</main><footer><span>© 2026 Privi World Corp · Made by Dario Canoy</span><span>PRELAUNCH / PROTOTYPE PORTAL · No live financial transactions</span></footer></div>

<script>
(async()=>{
 const labels={one:document.getElementById('status-one'),outcome:document.getElementById('status-outcome')};
 const stamp=document.getElementById('status-updated');
 try{
   const controller=new AbortController();
   const timer=setTimeout(()=>controller.abort(),12000);
   let response;
   try{response=await fetch('/api/status',{cache:'no-store',signal:controller.signal});}
   finally{clearTimeout(timer);}
   if(!response.ok)throw Error('Health snapshot unavailable');
   const data=await response.json();
   for(const key of Object.keys(labels)){
     const value=data.services?.[key]?.state;
     const good=value==='health_responding';
     labels[key].classList.toggle('responding',good);
     labels[key].textContent=good?'HEALTH ENDPOINT RESPONDING':'UNREACHABLE / UNVERIFIED';
   }
   stamp.textContent='Checked '+new Date(data.checked_at_unix*1000).toLocaleString()+
     ' · Cached 90 seconds · Demo health only; no live payment or mainnet verification.';
 }catch{
   Object.values(labels).forEach(element=>element.textContent='STATUS UNAVAILABLE');
   stamp.textContent='Unable to retrieve current sandbox health observations.';
 }
})();
</script>

<script>
(async()=>{
  const status=document.getElementById('auth-readiness');
  try{
    const response=await fetch('/api/access/config',{cache:'no-store'});
    if(!response.ok)throw Error('Unavailable');
    const config=await response.json();
    const identity=config.identity_provider==='settings_present_unverified'?'Settings present, provider unverified — login disabled':'Not configured';
    const billing=config.billing_proof==='settings_present_unverified'?'Settings present, entitlements unverified — access disabled':'Not configured';
    status.textContent='Identity provider: '+identity+' · Privi Pro entitlement verifier: '+billing+
       ' · Registration and login remain disabled.';
  }catch{status.textContent='Identity and entitlement readiness cannot be verified. Access remains disabled.';}
})();
</script>
</body></html>"""

class Handler(BaseHTTPRequestHandler):
    server_version="PriviUniversePreview/1"
    sys_version=""
    def log_message(self, format, *args):
        # Do not log visitors or request query strings.
        pass
    def respond(self, code, content, content_type):
        data = content if isinstance(content,bytes) else content.encode()
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length",str(len(data)))
        self.send_header("Cache-Control","no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("Referrer-Policy","no-referrer")
        self.send_header("X-Frame-Options","DENY")
        self.send_header("Content-Security-Policy","default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; img-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)
    def do_GET(self):
        path=urlsplit(self.path).path
        if path=="/health":
            return self.respond(200,json.dumps({"ok":True,"service":"privi-universe","mode":"PRELAUNCH_PORTAL"}),"application/json; charset=utf-8")
        if path=="/api/access/config":
            settings=account_access.config_from_env()
            payload={"identity_provider":"settings_present_unverified" if account_access.configured(settings) else "not_configured",
                     "billing_proof":"settings_present_unverified" if account_access.billing_configured(settings) else "not_configured",
                     "browser_login":"NOT_IMPLEMENTED",
                     "registration":"NOT_IMPLEMENTED",
                     "privileges":"DENIED_UNTIL_VERIFIED"}
            return self.respond(200,json.dumps(payload),"application/json; charset=utf-8")
        if path in ("/api/account/me","/api/pro/verify"):
            settings=account_access.config_from_env()
            if not account_access.configured(settings):
                return self.respond(503,'{"error":"identity_provider_not_configured"}',
                                    "application/json; charset=utf-8")
            try:
                account=account_access.verify_account_token(
                    account_access.bearer(self.headers.get("Authorization")),settings)
            except account_access.AccessDenied:
                return self.respond(401,'{"error":"valid_account_access_token_required"}',
                                    "application/json; charset=utf-8")
            if path=="/api/account/me":
                result={"subject":account["sub"],"authenticated":True,
                        "pro_status":"NOT_CHECKED","scope":"READ_ONLY_ACCOUNT"}
                return self.respond(200,json.dumps(result),"application/json; charset=utf-8")
            if not account_access.billing_configured(settings):
                return self.respond(503,'{"error":"billing_entitlement_verifier_not_configured"}',
                                    "application/json; charset=utf-8")
            try:
                entitlement=account_access.verify_pro_entitlement(
                    account, account_access.bearer(self.headers.get("X-Privi-Entitlement")), settings)
                return self.respond(200,json.dumps(entitlement),"application/json; charset=utf-8")
            except account_access.AccessDenied:
                return self.respond(403,'{"error":"trusted_paid_entitlement_required"}',
                                    "application/json; charset=utf-8")
        if path=="/api/status":
            return self.respond(200,json.dumps(MONITOR.snapshot()),"application/json; charset=utf-8")
        if path=="/":
            return self.respond(200,HTML,"text/html; charset=utf-8")
        return self.respond(404,'{"error":"not_found"}',"application/json; charset=utf-8")

def main():
    port=int(os.environ.get("PORT","10000"))
    ThreadingHTTPServer(("0.0.0.0",port),Handler).serve_forever()

if __name__=="__main__":
    main()
