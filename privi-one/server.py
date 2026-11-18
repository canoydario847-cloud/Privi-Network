"""Render-hosted Privi ONE synthetic sandbox. Public demo only.

Stdlib-only HTTP app. Never calls payment, token, mainnet, model or external APIs.
Per-process HMAC key is ephemeral: receipts are locally authenticated within
this process only, and are NOT durable Ledger entries or public signatures.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import secrets
from urllib.parse import urlsplit
import importlib.util

DEMO_FILE = Path(__file__).with_name("demo.py")
spec = importlib.util.spec_from_file_location("privi_one_demo", DEMO_FILE)
if spec is None or spec.loader is None:
    raise RuntimeError("Privi ONE demo is unavailable")
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)
quote_spec = importlib.util.spec_from_file_location('privi_one_quote_integrity', DEMO_FILE.with_name('quote_integrity.py'))
if quote_spec is None or quote_spec.loader is None:
    raise RuntimeError('Quote integrity module unavailable')
quote_integrity = importlib.util.module_from_spec(quote_spec)
quote_spec.loader.exec_module(quote_integrity)
id_spec = importlib.util.spec_from_file_location('privi_one_sandbox_identity', DEMO_FILE.with_name('sandbox_identity.py'))
if id_spec is None or id_spec.loader is None:
    raise RuntimeError('Sandbox identity unavailable')
sandbox_identity = importlib.util.module_from_spec(id_spec)
id_spec.loader.exec_module(sandbox_identity)
journal_spec = importlib.util.spec_from_file_location('privi_one_receipt_journal', DEMO_FILE.with_name('receipt_journal.py'))
if journal_spec is None or journal_spec.loader is None:
    raise RuntimeError('Sandbox receipt journal unavailable')
receipt_journal = importlib.util.module_from_spec(journal_spec)
journal_spec.loader.exec_module(receipt_journal)
SECRET = secrets.token_bytes(32)
QUOTE_SECRET = secrets.token_bytes(32)
SESSIONS = sandbox_identity.SandboxIdentity(secrets.token_bytes(32))
JOURNAL = receipt_journal.Journal(os.environ.get('PRIVI_ONE_SANDBOX_DB', '/tmp/privi-one-sandbox-receipts.sqlite3'))
MAX_BODY = 16_384
HOST = "0.0.0.0"
HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Privi ONE — Prelaunch Sandbox</title><style>

:root{color-scheme:dark;--bg:#030712;--surface:rgba(9,19,41,.76);--edge:rgba(100,170,250,.22);--white:#edf6ff;--muted:#96accb;--cyan:#5df4ed;--blue:#6689ff;--violet:#bb87ff;--gold:#f9c887}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;min-height:100vh;overflow-x:hidden;background:#030712;color:var(--white);font:15px/1.65 system-ui,-apple-system,"Segoe UI",sans-serif;background-image:radial-gradient(ellipse 65% 45% at 76% 8%,rgba(76,58,182,.28),transparent 76%),radial-gradient(ellipse 48% 38% at 17% 40%,rgba(22,118,169,.19),transparent 76%),linear-gradient(180deg,#050a18,#030713 50%,#070a1b)}
body:before{content:"";position:fixed;inset:0;z-index:0;pointer-events:none;background-image:radial-gradient(1px 1px at 7% 14%,#defaff 98%,transparent),radial-gradient(1px 1px at 39% 21%,#defaff 98%,transparent),radial-gradient(2px 2px at 81% 32%,#defaff 98%,transparent),radial-gradient(1px 1px at 71% 74%,#defaff 98%,transparent),radial-gradient(1px 1px at 18% 80%,#defaff 98%,transparent),radial-gradient(1px 1px at 90% 12%,#defaff 98%,transparent);background-size:310px 290px,370px 270px,410px 330px,500px 430px,270px 360px,580px 490px;opacity:.58}
main{max-width:1120px;margin:auto;padding:0 24px 88px;position:relative;z-index:1}
nav{display:flex;align-items:center;justify-content:space-between;gap:16px;min-height:80px;border-bottom:1px solid var(--edge);flex-wrap:wrap}
.brand{display:flex;align-items:center;gap:10px;font-weight:850;letter-spacing:.16em;font-size:14px;text-decoration:none;color:var(--white)}
.brand-mark{display:grid;place-items:center;width:33px;height:33px;border-radius:10px;border:1px solid rgba(93,244,237,.65);background:linear-gradient(135deg,rgba(93,244,237,.25),rgba(147,109,255,.2));box-shadow:0 0 26px rgba(93,244,237,.18);color:var(--cyan);font-size:21px}
.links{display:flex;gap:12px;align-items:center;flex-wrap:wrap}
.links a{color:#aec7e8;text-decoration:none;font-size:12px;font-weight:700;letter-spacing:.09em;padding:9px 12px;border:1px solid transparent;border-radius:9px}
.links a:hover,.links a:focus-visible{color:var(--cyan);border-color:var(--edge);background:rgba(81,139,221,.08)}
.status{color:var(--cyan);font:700 11px/1.5 ui-monospace,monospace;letter-spacing:.08em;white-space:nowrap}
.status:before{content:"";display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--cyan);box-shadow:0 0 12px var(--cyan);margin-right:8px}
.hero{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(270px,.85fr);gap:22px;align-items:center;padding:74px 0 46px;min-height:400px}
.eyebrow,.badge,.banner{display:inline-flex;align-items:center;gap:10px;color:var(--cyan);font:750 11px/1.6 ui-monospace,monospace;letter-spacing:.16em;text-transform:uppercase}
.eyebrow:before,.badge:before,.banner:before{content:"";height:1px;width:28px;background:var(--cyan);box-shadow:0 0 8px var(--cyan)}
h1{font-weight:780;font-size:clamp(39px,6vw,69px);line-height:1.06;letter-spacing:-.052em;margin:18px 0 22px}
.gradient{background:linear-gradient(100deg,#fff 6%,#83f9f5 53%,#b4a0ff 100%);-webkit-background-clip:text;background-clip:text;color:transparent}
.sub,.muted{color:var(--muted);font-size:15px;max-width:640px}
.hero-visual{height:300px;position:relative;display:grid;place-items:center;isolation:isolate}
.orbit{position:absolute;width:min(95%,340px);aspect-ratio:1;border-radius:50%;border:1px solid rgba(104,214,255,.23);transform:rotate(-26deg) scaleY(.62);box-shadow:0 0 38px rgba(45,167,225,.08),inset 0 0 26px rgba(41,122,213,.07)}
.orbit:nth-child(2){transform:rotate(52deg) scaleY(.57);width:min(75%,290px);border-color:rgba(181,125,250,.34)}
.orbit:nth-child(3){transform:rotate(120deg) scaleY(.45);width:min(56%,210px);border-color:rgba(93,244,237,.28)}
.planet{height:154px;width:154px;border-radius:50%;display:grid;place-items:center;position:relative;z-index:1;background:radial-gradient(circle at 29% 26%,#3cbcd0 0%,#284c97 34%,#241456 68%,#090b23 100%);box-shadow:inset -17px -17px 35px rgba(0,3,17,.85),0 0 62px rgba(80,86,255,.42),0 0 100px rgba(52,200,238,.15);font-size:13px;letter-spacing:.23em;font-weight:850}
.planet:after{content:"";position:absolute;inset:-12px;border:1px solid rgba(136,201,255,.11);border-radius:50%}
.satellite{position:absolute;width:8px;height:8px;border-radius:50%;background:var(--cyan);box-shadow:0 0 14px var(--cyan);top:34px;right:25%}
.hero-metrics{display:flex;gap:20px;margin-top:25px;flex-wrap:wrap}
.metric{border-left:2px solid var(--cyan);padding:2px 0 3px 12px}
.metric b{font-size:17px;display:block;line-height:1.3}
.metric span{font:11px ui-monospace,monospace;color:var(--muted);letter-spacing:.08em;text-transform:uppercase}
.panel{position:relative;background:linear-gradient(135deg,rgba(17,34,67,.85),rgba(8,17,37,.88));border:1px solid var(--edge);border-radius:18px;padding:26px;margin:21px 0;box-shadow:inset 0 1px rgba(204,237,255,.05),0 18px 55px rgba(0,0,0,.18);backdrop-filter:blur(12px)}
.panel:before{content:"";position:absolute;top:-1px;left:28px;width:68px;height:2px;background:linear-gradient(90deg,var(--cyan),transparent)}
h2{font-size:20px;letter-spacing:-.025em;margin:0 0 14px}
h3{font-size:13px;text-transform:uppercase;letter-spacing:.13em;color:#b8d8f6;margin:24px 0 12px}
p{margin-top:8px}
small,.footnote{color:var(--muted);font-size:12px}
.cols,.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:13px}
.item,.step{border:1px solid rgba(101,160,220,.17);border-radius:12px;padding:19px;background:linear-gradient(145deg,rgba(31,51,86,.48),rgba(8,20,43,.56));min-width:0}
.item b,.step b{display:block;font-size:14px;letter-spacing:.012em;color:#e4f4ff;margin-bottom:7px}
.step p{font-size:12px;color:var(--muted);margin-bottom:0}
input,textarea{border-radius:10px;background:rgba(0,6,21,.72);color:#f5fcff;border:1px solid rgba(122,175,226,.32);width:100%;padding:13px 15px;font:inherit}
textarea{resize:vertical}
label{display:block;margin:15px 0 7px;color:#c7d9ed;font-weight:650;font-size:13px}
input:focus-visible,textarea:focus-visible,button:focus-visible,a:focus-visible{outline:2px solid var(--cyan);outline-offset:3px}
button{font:750 12px/1.5 system-ui,sans-serif;text-transform:uppercase;letter-spacing:.075em;border-radius:10px;padding:13px 18px;cursor:pointer;border:1px solid rgba(111,235,248,.45);background:linear-gradient(110deg,#70f3ee,#7699ff);color:#061021;box-shadow:0 5px 26px rgba(67,178,220,.16);margin:7px 7px 7px 0}
button:hover{filter:brightness(1.12);transform:translateY(-1px)}
button.secondary{color:#c8e9ff;background:rgba(23,48,91,.6);box-shadow:none}
pre,.output{white-space:pre-wrap;overflow-wrap:anywhere;overflow:auto;max-height:500px;padding:19px;border-radius:12px;background:#050e21;border:1px solid rgba(87,155,218,.22);color:#a8fff7;font:12px/1.8 ui-monospace,"Cascadia Code",monospace}
footer{margin-top:36px;padding-top:24px;border-top:1px solid var(--edge);color:var(--muted);font-size:12px}
footer a{color:#90e7f3}
@media(max-width:780px){.hero{grid-template-columns:1fr;padding:46px 0 22px}.hero-visual{height:230px;max-width:400px;width:100%;margin:0 auto}.planet{width:128px;height:128px}.cols,.grid{grid-template-columns:1fr 1fr}nav{padding:12px 0}.links{gap:2px}main{padding:0 16px 55px}}
@media(max-width:520px){.cols,.grid{grid-template-columns:1fr}.hero{padding-top:32px}h1{font-size:42px}.hero-visual{height:200px}.panel{padding:19px}.status{font-size:10px}.links a{padding:5px 8px}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}button:hover{transform:none}}

</style></head><body><main><nav><a class="brand" href="/"><span class="brand-mark">✦</span> PRIVI <span style="color:var(--cyan)">ONE</span></a><div class="links"><a href="https://privi-outcomegrid-demo.onrender.com">OUTCOMEGRID</a><a href="#route">SMARTROUTE</a><a href="#console">MISSION CONTROL</a></div><span class="status">PRELAUNCH · SYNTHETIC SIMULATION</span></nav>
<section class="hero"><div><span class="eyebrow">PRIVI NETWORK / INTELLIGENT AGENT INFRASTRUCTURE</span><h1>Spend smarter.<br><span class="gradient">Verify every action.</span></h1><p class="sub">Navigate AI work through cost-aware routing, Guard inspection, policy controls, and tamper-checkable receipts. A simulation designed for the next frontier of trustworthy agents.</p><div class="hero-metrics"><div class="metric"><b>03</b><span>Synthetic routes</span></div><div class="metric"><b>00</b><span>Live charges</span></div><div class="metric"><b>100%</b><span>Prelaunch</span></div></div></div><div class="hero-visual" aria-hidden="true"><div class="orbit"></div><div class="orbit"></div><div class="orbit"></div><div class="planet">PRIVI / ONE</div><div class="satellite"></div></div></section>
<section id="route" class="panel"><span class="eyebrow">01 / ROUTE INTELLIGENCE</span><h2>Compare simulated model routes</h2>
<div class="cols"><div class="item"><b>Budget model</b>3¢ · quality 78/100 · reliability 96%</div>
<div class="item"><b>Balanced model</b>8¢ · quality 91/100 · reliability 99%</div>
<div class="item"><b>Premium baseline</b>19¢ · quality 96/100 · reliability 99%</div></div><small>Prices and scores are illustrative, not live quotes or measured performance.</small></section>
<section id="console" class="panel"><span class="eyebrow">02 / MISSION CONTROL</span><h2>Run an offline policy simulation</h2>
<label for="task">Synthetic task (no confidential data)</label>
<textarea id="task" maxlength="10000" rows="3">Summarize a synthetic non-sensitive report</textarea>
<label for="budget">Maximum estimated cost in cents</label><input id="budget" type="number" value="10" min="0" max="100000">
<label><input id="approve" type="checkbox" style="width:auto" checked> Simulated approval (not verified human authorization)</label>
<button id="go">Compare &amp; generate simulated receipt</button> <button id="verify" class="secondary" type="button">Verify receipt in this session</button>
<h3 id="resultHeading" aria-live="polite">No simulation run yet</h3>
<pre id="result" class="output" aria-live="polite"></pre></section>
<footer>© 2026 Privi World Corp. Original proprietary Privi materials reserved, subject to existing licenses and third-party rights. This demo is not a live CallProof, payment, or PRVI mainnet service.</footer>
</main><script>
let lastReceipt=null, sandboxToken=null;
async function getSandboxToken(){
 if(sandboxToken)return sandboxToken;
 const response=await fetch("/api/session",{method:"POST",headers:{"content-type":"application/json"},body:"{}"});
 if(!response.ok)throw Error("Sandbox session unavailable");
 sandboxToken=(await response.json()).token;return sandboxToken;
}
document.querySelector('#go').addEventListener('click',async()=>{
 const output=document.querySelector('#result'), head=document.querySelector('#resultHeading');
 head.textContent='Simulating...';output.textContent='';
 try{
  const token=await getSandboxToken();
  const response=await fetch('/api/simulate-secure',{method:'POST',headers:{'content-type':'application/json','authorization':'Bearer '+token},
   body:JSON.stringify({task:document.querySelector('#task').value,budget_cents:Number(document.querySelector('#budget').value),
    approved:document.querySelector('#approve').checked, request_id:crypto.randomUUID()})});
  const body=await response.json();head.textContent=response.ok?(body.receipt?.decision||'Done'):'Error';
  lastReceipt=response.ok?body:null;
  output.textContent=JSON.stringify(body,null,2);
 }catch{head.textContent='Unavailable';output.textContent='The demo could not be reached.';}
});
document.querySelector('#verify').addEventListener('click',async()=>{
 const output=document.querySelector('#result'),head=document.querySelector('#resultHeading');
 if(!lastReceipt){head.textContent='Generate a receipt first';return;}
 try{
 const resp=await fetch('/api/verify',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(lastReceipt)});
 const body=await resp.json();head.textContent=body.verified?'Receipt verified in this server session':'Verification failed';
 output.textContent=JSON.stringify(body,null,2)+'\\n\\n'+JSON.stringify(lastReceipt,null,2);
 }catch{head.textContent='Verification unavailable';}
});
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "PriviOnePrelaunch/1"
    sys_version = ""

    def log_message(self, format, *args):
        # Never log visitor task text or request bodies.
        pass

    def headers_common(self, content_type, length):
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
        self.send_header("Access-Control-Allow-Origin", "null")

    def reply(self, code, obj):
        raw = json.dumps(obj, separators=(",", ":"), allow_nan=False).encode()
        self.send_response(code)
        self.headers_common("application/json; charset=utf-8", len(raw))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/health":
            return self.reply(200, {"ok": True, "service": "privi-one-demo", "mode": "PRELAUNCH_SIMULATION"})
        if path == "/api/audit":
            # Sandbox-only aggregate result; never expose sessions or raw receipts.
            try:
                return self.reply(200, JOURNAL.audit())
            except Exception:
                return self.reply(503, {"error": "journal_unavailable"})
        if path == "/api/checkpoint":
            # User must independently preserve this unsigned checkpoint;
            # serving it does NOT provide an external trust anchor.
            try:
                return self.reply(200, receipt_journal.checkpoint(JOURNAL))
            except Exception:
                return self.reply(503, {"error": "checkpoint_unavailable"})
        if path != "/":
            return self.reply(404, {"error": "not_found"})
        raw = HTML.encode()
        self.send_response(200)
        self.headers_common("text/html; charset=utf-8", len(raw))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        path = urlsplit(self.path).path
        if path not in ("/api/simulate", "/api/simulate-secure", "/api/session", "/api/verify", "/api/checkpoint/verify"):
            return self.reply(404, {"error": "not_found"})
        if self.headers.get_content_type() != "application/json":
            return self.reply(415, {"error": "json_only"})
        try:
            length = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            return self.reply(400, {"error": "invalid_content_length"})
        if not 1 <= length <= MAX_BODY:
            return self.reply(413, {"error": "body_size_invalid"})
        try:
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                return self.reply(400, {"error": "invalid_payload"})
            if path == "/api/session":
                if data:
                    return self.reply(400, {"error": "invalid_session_request"})
                return self.reply(200, SESSIONS.issue())
            if path == "/api/checkpoint/verify":
                if set(data) != {"checkpoint"}:
                    return self.reply(400, {"error": "checkpoint_required"})
                try:
                    return self.reply(200, receipt_journal.check_pinned_checkpoint(
                        JOURNAL, data["checkpoint"]))
                except Exception:
                    return self.reply(503, {"error": "journal_unavailable"})
            secure = path == "/api/simulate-secure"
            if secure:
                auth = self.headers.get("Authorization", "")
                sid = SESSIONS.verify(auth[7:] if auth.startswith("Bearer ") else None)
                if sid is None:
                    return self.reply(401, {"error": "sandbox_session_required"})
            if path == "/api/verify":
                envelope = {k: data.get(k) for k in ("receipt", "digest_sha256", "auth")}
                bundle = data.get("quote_attestation")
                verified_receipt = demo.verify(envelope, SECRET)
                if not isinstance(bundle, dict) or not isinstance(envelope["receipt"], dict):
                    return self.reply(200, {"verified": False, "scope": "CURRENT_SERVER_SESSION_ONLY"})
                receipt = envelope["receipt"]
                binding = receipt.get("routing", {}).get("quote_bundle_sha256")
                valid_bundle = quote_integrity.verify(bundle, receipt.get("task_sha256"), key=QUOTE_SECRET)
                bound = (isinstance(binding, str) and
                         hmac.compare_digest(binding, demo.digest(bundle.get("body"))))
                return self.reply(200, {"verified": bool(verified_receipt and valid_bundle and bound),
                                        "scope": "CURRENT_SERVER_SESSION_ONLY",
                                        "ledger": "NOT_SUBMITTED", "signature": "HMAC_LOCAL_NOT_PUBLIC_KEY"})
            allowed_keys = {"task", "budget_cents", "approved", "request_id"} if secure else {"task", "budget_cents", "approved"}
            if set(data) - allowed_keys:
                return self.reply(400, {"error": "invalid_payload"})
            task = data.get("task")
            budget = data.get("budget_cents")
            approved = data.get("approved", False)
            if (not isinstance(task, str) or not task.strip() or len(task) > 10000
                    or type(budget) is not int or type(approved) is not bool):
                return self.reply(400, {"error": "invalid_fields"})
            if secure and not isinstance(data.get("request_id"), str):
                return self.reply(400, {"error": "request_id_required"})
            def build_receipt():
                task_hash = hashlib.sha256(task.encode("utf-8")).hexdigest()
                bundle = quote_integrity.issue(demo.DEMO_OPTIONS, task_hash, key=QUOTE_SECRET)
                if not quote_integrity.verify(bundle, task_hash, key=QUOTE_SECRET):
                    raise RuntimeError("Quote integrity failed")
                result = demo.evaluate(
                task, tool="report_summary", allowed_tools=["report_summary"],
                budget_cents=budget, approved=approved, secret=SECRET,
                options=bundle["body"]["options"],
            )
                result["receipt"]["routing"]["quote_bundle_sha256"] = demo.digest(bundle["body"])
                if secure:
                    result["receipt"]["sandbox_identity"] = {"mode": "ANONYMOUS_SANDBOX_NOT_REAL_AUTH",
                                                             "session_sha256": hashlib.sha256(sid.encode()).hexdigest(),
                                                             "request_id": data["request_id"]}
                result["digest_sha256"] = demo.digest(result["receipt"])
                result["auth"]["mac"] = hmac.new(SECRET, demo.canonical(result["receipt"]), hashlib.sha256).hexdigest()
                result["quote_attestation"] = bundle
                return result
            if secure:
                payload = {"task_sha256": hashlib.sha256(task.encode()).hexdigest(),
                           "budget_cents": budget, "approved": approved}
                result, replayed = JOURNAL.run_once(sid, data["request_id"], payload, build_receipt)
                # Replay metadata is outside the signed receipt; no mutation of cached result.
                return self.reply(200, dict(result, idempotent_replay=replayed))
            return self.reply(200, build_receipt())
        except (ValueError, UnicodeError, json.JSONDecodeError):
            return self.reply(400, {"error": "invalid_request"})
        except Exception:
            return self.reply(503, {"error": "simulation_unavailable"})


def main():
    port = int(os.environ.get("PORT", "10000"))
    server = ThreadingHTTPServer((HOST, port), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
