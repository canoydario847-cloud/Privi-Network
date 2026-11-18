"""Read-only OutcomeGrid synthetic proof demo for Render.

All roles and evidence are local fixtures, never user-provided identity.
Does not claim a real verification, accept external jobs, execute agents,
charge funds, or make PRVI token or ledger calls.
"""
from __future__ import annotations
import hashlib
import html
import importlib.util
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("outcomegrid_core", HERE / "core.py")
if spec is None or spec.loader is None:
    raise RuntimeError("OutcomeGrid core missing")
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)
evidence_spec = importlib.util.spec_from_file_location("outcomegrid_github_evidence", HERE / "github_evidence.py")
if evidence_spec is None or evidence_spec.loader is None:
    raise RuntimeError("OutcomeGrid evidence adapter missing")
github_evidence = importlib.util.module_from_spec(evidence_spec)
evidence_spec.loader.exec_module(github_evidence)

SCENARIOS = frozenset({"accepted", "rejected", "self_attestation_blocked", "duplicate_blocked", "github_checks_pending_review"})
MAX_BYTES = 256


def run_fixture(scenario):
    if scenario not in SCENARIOS:
        raise ValueError("unsupported simulation")
    with tempfile.TemporaryDirectory(prefix="outcomegrid-demo-") as folder:
        grid = core.OutcomeGrid(str(Path(folder) / "scenario.sqlite3"))
        task = grid.post_job(
            job_id="synthetic-task-001", buyer="synthetic-buyer",
            agent="synthetic-agent", verifier="synthetic-independent-reviewer",
            criteria={"check": "approved pull request and CI checks",
                      "expected": "all sandbox tests passing"}, now=1000)
        evidence = hashlib.sha256(b"synthetic-ci-result-not-real").hexdigest()
        denial = None
        if scenario == "github_checks_pending_review":
            repo = "synthetic-org/synthetic-repo"
            sha = "a" * 40
            checks = {"repository": repo, "head_sha": sha, "total_count": 1,
                      "check_runs": [{"id": 101, "name": "ci/test", "head_sha": sha,
                                      "status": "completed", "conclusion": "success",
                                      "app": {"slug": "github-actions"}}]}
            verdict = github_evidence.verify_check_runs(checks, repo=repo, head_sha=sha,
                                                        required_checks=["ci/test"])
            return {"mode": "SYNTHETIC_PRELAUNCH_NO_REAL_AGENTS",
                    "scenario": scenario, "task": task,
                    "github_check_evidence": verdict, "outcome": grid.job_status("synthetic-task-001"),
                    "reputation": grid.scoreboard(), "review_required": True,
                    "payment": "NOT_USED", "PRVI": "NOT_USED", "ledger": "NOT_USED"}
        if scenario == "self_attestation_blocked":
            try:
                grid.attest(job_id="synthetic-task-001", actor="synthetic-agent",
                            decision="accepted", evidence_digest=evidence, now=1001)
            except PermissionError:
                denial = "executor_cannot_verify_self"
        else:
            decision = "rejected" if scenario == "rejected" else "accepted"
            grid.attest(job_id="synthetic-task-001", actor="synthetic-independent-reviewer",
                        decision=decision, evidence_digest=evidence, now=1001)
            if scenario == "duplicate_blocked":
                try:
                    grid.attest(job_id="synthetic-task-001", actor="synthetic-independent-reviewer",
                                decision="accepted", evidence_digest=evidence, now=1002)
                except ValueError:
                    denial = "duplicate_outcome_refused"
        return {"mode": "SYNTHETIC_PRELAUNCH_NO_REAL_AGENTS",
                "scenario": scenario, "task": task,
                "outcome": grid.job_status("synthetic-task-001"),
                "reputation": grid.scoreboard(),
                "blocked_reason": denial,
                "payment": "NOT_USED", "PRVI": "NOT_USED", "ledger": "NOT_USED"}


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Privi OutcomeGrid · Sandbox</title><style>

:root{color-scheme:dark;--bg:#030712;--surface:rgba(9,19,41,.76);--edge:rgba(100,170,250,.22);--white:#edf6ff;--muted:#96accb;--cyan:#5df4ed;--blue:#6689ff;--violet:#bb87ff;--gold:#f9c887}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;min-height:100vh;overflow-x:hidden;background:#030712;color:var(--white);font:15px/1.65 system-ui,-apple-system,"Segoe UI",sans-serif;background-image:radial-gradient(ellipse 65% 45% at 76% 8%,rgba(76,58,182,.28),transparent 76%),radial-gradient(ellipse 48% 38% at 17% 40%,rgba(22,118,169,.19),transparent 76%),linear-gradient(180deg,#050a18,#030713 50%,#070a1b)}
body:before{content:"";position:fixed;inset:0;z-index:-1;pointer-events:none;background-image:radial-gradient(1px 1px at 7% 14%,#defaff 98%,transparent),radial-gradient(1px 1px at 39% 21%,#defaff 98%,transparent),radial-gradient(2px 2px at 81% 32%,#defaff 98%,transparent),radial-gradient(1px 1px at 71% 74%,#defaff 98%,transparent),radial-gradient(1px 1px at 18% 80%,#defaff 98%,transparent),radial-gradient(1px 1px at 90% 12%,#defaff 98%,transparent);background-size:310px 290px,370px 270px,410px 330px,500px 430px,270px 360px,580px 490px;opacity:.58}
main{max-width:1120px;margin:auto;padding:0 24px 88px;position:relative}
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

</style></head><body><main><nav><a class="brand" href="/"><span class="brand-mark">✧</span> PRIVI <span style="color:var(--cyan)">OUTCOMEGRID</span></a><div class="links"><a href="https://privi-one-demo.onrender.com">PRIVI ONE</a><a href="#process">VERIFICATION</a><a href="#console">MISSION CONTROL</a></div><span class="status">SANDBOX ONLINE</span></nav>
<section class="hero"><div><span class="eyebrow">PRIVI NETWORK / AGENT OUTCOME PROTOCOL</span><h1>Trust is earned.<br><span class="gradient">Proof is everything.</span></h1><p class="sub">The future of AI-agent reputation is grounded in demonstrable results, separate reviewers, and evidence that survives scrutiny. Explore the verification journey in a controlled prelaunch simulation.</p><div class="hero-metrics"><div class="metric"><b>05</b><span>Test scenarios</span></div><div class="metric"><b>00</b><span>Real outcomes</span></div><div class="metric"><b>100%</b><span>Synthetic data</span></div></div></div><div class="hero-visual" aria-hidden="true"><div class="orbit"></div><div class="orbit"></div><div class="orbit"></div><div class="planet">OUTCOME / GRID</div><div class="satellite"></div></div></section>
<section id="process" class="panel"><span class="eyebrow">01 / TRUST PROTOCOL</span><h2>Outcome verification flow</h2><div class="grid">
<div class="step"><b>1. Set measurable criteria</b><p>CI checks and independent PR review</p></div>
<div class="step"><b>2. Assign agent and reviewer</b><p>Different synthetic entities</p></div>
<div class="step"><b>3. Verify evidence</b><p>Accept or reject based on demo fixture</p></div>
<div class="step"><b>4. Update outcome history</b><p>Count only reviewed outcomes</p></div></div></section>
<section id="console" class="panel"><span class="eyebrow">02 / MISSION CONTROL</span><h2>Run a scenario</h2><p class="muted">Choose a fixture to see accepted work, failed work, blocked self-verification or blocked duplicates.</p>
<button data-scenario="accepted">Accepted outcome</button><button data-scenario="rejected">Rejected outcome</button>
<button data-scenario="self_attestation_blocked">Block self-attestation</button><button data-scenario="duplicate_blocked">Block duplicate</button><button data-scenario="github_checks_pending_review">GitHub CI evidence (review pending)</button>
<h3 id="status" aria-live="polite">Choose a scenario</h3><pre id="result" aria-live="polite">No simulation executed.</pre></section>
<footer>© 2026 Privi World Corp. Sandbox only. No authenticated real-world verifier, real client data, independent execution evidence, live payment, escrow, ledger transaction, or PRVI network.</footer></main>
<script>
document.querySelectorAll('button[data-scenario]').forEach(button=>button.addEventListener('click',async()=>{
const scenario=button.dataset.scenario, status=document.querySelector('#status'), out=document.querySelector('#result');
status.textContent='Evaluating synthetic scenario…';
try{const response=await fetch('/api/simulate',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({scenario})});
const data=await response.json();status.textContent=response.ok?'Simulation: '+scenario:'Unavailable';out.textContent=JSON.stringify(data,null,2);}
catch{status.textContent='Unavailable';out.textContent='Could not reach demo.';}
}));
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "OutcomeGridSandbox/1"
    sys_version = ""

    def log_message(self, fmt, *args):
        pass

    def respond(self, status, payload, content_type="application/json; charset=utf-8"):
        raw = payload if isinstance(payload, bytes) else json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/health":
            return self.respond(200, {"ok": True, "mode": "SYNTHETIC_PRELAUNCH"})
        if path == "/":
            return self.respond(200, PAGE.encode(), "text/html; charset=utf-8")
        return self.respond(404, {"error": "not_found"})

    def do_POST(self):
        if urlsplit(self.path).path != "/api/simulate":
            return self.respond(404, {"error": "not_found"})
        if self.headers.get_content_type() != "application/json":
            return self.respond(415, {"error": "json_only"})
        try:
            n = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            return self.respond(400, {"error": "invalid_length"})
        if not 1 <= n <= MAX_BYTES:
            return self.respond(413, {"error": "body_limit"})
        try:
            request = json.loads(self.rfile.read(n))
            if not isinstance(request, dict) or set(request) != {"scenario"}:
                return self.respond(400, {"error": "scenario_required"})
            return self.respond(200, run_fixture(request["scenario"]))
        except (ValueError, TypeError, UnicodeError, json.JSONDecodeError):
            return self.respond(400, {"error": "invalid_scenario"})
        except Exception:
            return self.respond(503, {"error": "simulation_unavailable"})


def main():
    port = int(os.environ.get("PORT", "10000"))
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
