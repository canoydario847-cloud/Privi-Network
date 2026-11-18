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
:root{color-scheme:dark}*{box-sizing:border-box}body{font:16px/1.55 system-ui,sans-serif;background:#0c1425;color:#e8f0ff;margin:0}
main{max-width:980px;margin:auto;padding:38px 20px 72px}.badge{color:#ffdb91;font-size:13px;font-weight:700;letter-spacing:.09em}
h1{font-size:clamp(30px,5vw,48px);line-height:1.1;margin:12px 0}.sub{color:#b5c7e3;max-width:58rem}
.panel{background:#172740;border:1px solid #2b4569;border-radius:14px;padding:23px;margin:20px 0}
label{display:block;margin:14px 0 5px;font-weight:650}textarea,input{width:100%;background:#0d1b30;color:#fff;border:1px solid #496287;border-radius:8px;padding:11px;font:inherit}
button{background:#59a7ff;color:#081523;border:0;padding:12px 18px;border-radius:8px;font:700 15px system-ui;cursor:pointer;margin-top:15px}
button:focus-visible,textarea:focus-visible,input:focus-visible{outline:3px solid #ffcf74}
.output{white-space:pre-wrap;overflow-wrap:anywhere;background:#091426;padding:16px;border-radius:8px;font:13px/1.65 ui-monospace,monospace;max-height:480px;overflow:auto}
small{color:#aec2df}a{color:#89c6ff}.cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}
.item{border:1px solid #476181;border-radius:10px;padding:14px}.item b{display:block}
</style></head><body><main><div class="badge">PRIVI ONE · PRELAUNCH · SYNTHETIC DEMONSTRATION</div>
<h1>Spend smarter. Verify every AI action.</h1><p class="sub">A safe demonstration of SmartRoute, the existing Privi Guard inspection engine, CallProof-style policy checks and a tamper-checkable local receipt. No models or tools are called, no payments are made, no ledger is updated, and no tokens are moved.</p>
<section class="panel"><h2>Compare simulated model routes</h2>
<div class="cols"><div class="item"><b>Budget model</b>3¢ · quality 78/100 · reliability 96%</div>
<div class="item"><b>Balanced model</b>8¢ · quality 91/100 · reliability 99%</div>
<div class="item"><b>Premium baseline</b>19¢ · quality 96/100 · reliability 99%</div></div><small>Prices and scores are illustrative, not live quotes or measured performance.</small></section>
<section class="panel"><h2>Run an offline policy simulation</h2>
<label for="task">Synthetic task (no confidential data)</label>
<textarea id="task" maxlength="10000" rows="3">Summarize a synthetic non-sensitive report</textarea>
<label for="budget">Maximum estimated cost in cents</label><input id="budget" type="number" value="10" min="0" max="100000">
<label><input id="approve" type="checkbox" style="width:auto" checked> Simulated approval (not verified human authorization)</label>
<button id="go">Compare &amp; generate simulated receipt</button> <button id="verify" type="button">Verify receipt in this session</button>
<h3 id="resultHeading" aria-live="polite">No simulation run yet</h3>
<pre id="result" class="output" aria-live="polite"></pre></section>
<p><small>© 2026 Privi World Corp. Original proprietary Privi materials reserved, subject to existing licenses and third-party rights. This demo is not a live CallProof, payment, or PRVI mainnet service.</small></p>
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
        if path not in ("/api/simulate", "/api/simulate-secure", "/api/session", "/api/verify"):
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
