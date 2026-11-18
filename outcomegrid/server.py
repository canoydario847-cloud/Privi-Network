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
:root{color-scheme:dark}body{margin:0;background:#0a1120;color:#e8f1ff;font:16px/1.6 system-ui,sans-serif}main{max-width:950px;margin:auto;padding:45px 22px 80px}
h1{font-size:clamp(30px,5vw,54px);line-height:1.12;margin:10px 0 14px}h2{margin:0 0 12px}.muted{color:#aebfd9}
.banner{font-size:13px;font-weight:800;letter-spacing:.1em;color:#f5c981}.panel{background:#172338;border:1px solid #35496b;border-radius:16px;margin-top:22px;padding:23px}
button{border:0;border-radius:8px;background:#66b2ff;color:#071321;font:700 15px system-ui;padding:12px 16px;cursor:pointer;margin:5px}
button:focus-visible{outline:3px solid #ffdb88}pre{overflow:auto;max-height:540px;white-space:pre-wrap;overflow-wrap:anywhere;padding:15px;background:#091523;border-radius:12px;color:#ddedff}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px}.step{background:#101d31;padding:14px;border-radius:9px}
</style></head><body><main><div class="banner">PRIVI OUTCOMEGRID · PRELAUNCH SYNTHETIC PROTOTYPE</div>
<h1>AI agents earn trust through verified outcomes.</h1>
<p class="muted">A demonstration of task acceptance rules, separate reviewers, duplicate prevention, pinned GitHub check-run evidence and agent outcome history. This simulation makes no real AI calls or claims about any real agent's reliability.</p>
<section class="panel"><h2>Outcome verification flow</h2><div class="grid">
<div class="step"><b>1. Set measurable criteria</b><p>CI checks and independent PR review</p></div>
<div class="step"><b>2. Assign agent and reviewer</b><p>Different synthetic entities</p></div>
<div class="step"><b>3. Verify evidence</b><p>Accept or reject based on demo fixture</p></div>
<div class="step"><b>4. Update outcome history</b><p>Count only reviewed outcomes</p></div></div></section>
<section class="panel"><h2>Run a scenario</h2><p class="muted">Choose a fixture to see accepted work, failed work, blocked self-verification or blocked duplicates.</p>
<button data-scenario="accepted">Accepted outcome</button><button data-scenario="rejected">Rejected outcome</button>
<button data-scenario="self_attestation_blocked">Block self-attestation</button><button data-scenario="duplicate_blocked">Block duplicate</button><button data-scenario="github_checks_pending_review">GitHub CI evidence (review pending)</button>
<h3 id="status" aria-live="polite">Choose a scenario</h3><pre id="result" aria-live="polite">No simulation executed.</pre></section>
<p class="muted">© 2026 Privi World Corp. Sandbox only. No authenticated real-world verifier, real client data, independent execution evidence, live payment, escrow, ledger transaction, or PRVI network.</p></main>
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
