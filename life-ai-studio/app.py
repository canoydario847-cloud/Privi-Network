"""Privi LIFE AI Studio: multi-project AI teamwork with wallet-gated utility credits."""
import asyncio
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from pathlib import Path

import httpx
from eth_account import Account
from fastapi import FastAPI, HTTPException, Request, Response, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

import agents
import store
import fastlane
import multichain

app = FastAPI(title="Privi LIFE AI Studio", version="0.1.0")
store.init()
STATIC = Path(__file__).parent / "public"
ORIGIN = os.getenv("PUBLIC_ORIGIN", "http://localhost:8080").rstrip("/")
COOKIE_SECURE = os.getenv("LIFE_COOKIE_SECURE", "0") == "1"
FEE_BPS = 1000
AGENT_COST = 2
STAGING_MODE = os.getenv("LIFE_STAGING_ONLY", "0") == "1"
_demo_requests = {}  # One process only: sandbox is NOT a production signup service.

# Product-wide PRVI utility directory. Other Privi services consume credits
# through the authenticated /api/internal/charge API after integration.
UTILITIES = {
    "agent_run": ("Team AI agent execution", 2, True),
    "fast_answer": ("Fast Lane parallel response", 2, True),
    "code_review": ("Collaborative code review", 2, True),
    "hey_jose": ("Hey Jose assistant", 1, False),
    "life_backup": ("LIFE settings and data backup", 1, False),
    "iot_ledger": ("Privi IoT event processing", 1, False),
    "privi_guard": ("Privi Guard security scan", 1, False),
    "privi_ledger": ("Privi Ledger audit record", 1, False),
    "privi_anchor": ("Privi Anchor notarization", 1, False),
    "privi_verify": ("Privi Verify data authenticity", 1, False),
    "privi_os": ("Privi OS cloud tools", 1, False),
    "data_label": ("Privi AI metadata labeling", 1, False),
    "api_gateway": ("Privi API gateway requests", 1, False),
}

class AuthInput(BaseModel):
    email: str = Field(min_length=5, max_length=250)
    password: str = Field(min_length=12, max_length=200)

class WalletInput(BaseModel):
    wallet: str
class WalletLink(WalletInput):
    signature: str
class ProjectCreate(BaseModel):
    title: str = Field(min_length=2, max_length=100)
    kind: str = "code"
class FileInput(BaseModel):
    path: str
    content: str = Field(max_length=60000)
    expected_version: int = Field(ge=0)
class TeamRun(BaseModel):
    task: str = Field(min_length=4, max_length=4500)
    agents: list[str] = Field(min_length=1, max_length=6)
    mode: str = "parallel"  # team_up gives each member an explicit coding role

class FastAnswerRequest(BaseModel):
    question: str = Field(min_length=4, max_length=4500)
    providers: list[str] = Field(min_length=1, max_length=3)
class QuoteInput(BaseModel):
    credits: int = Field(ge=1, le=1000)
class RedeemInput(BaseModel):
    quote_id: str
    tx_hash: str
class InternalCharge(BaseModel):
    user_id: str
    service: str
    idempotency_key: str = Field(min_length=8, max_length=180)

def fail(code, message):
    raise HTTPException(code, detail=message)

def password_hash(password):
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return salt.hex() + ":" + digest.hex()

def valid_password(password, encoded):
    try:
        salt, expected = encoded.split(":")
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
        return hmac.compare_digest(actual, bytes.fromhex(expected))
    except (ValueError, TypeError):
        return False

def session_response(response, user_id):
    token = secrets.token_urlsafe(36)
    with store.transaction() as db:
        db.execute("INSERT INTO sessions VALUES(?,?,?)", (store.sha(token), user_id, store.now()+604800))
    response.set_cookie("life_session", token, httponly=True, secure=COOKIE_SECURE,
                        samesite="strict", max_age=604800, path="/")

def current(request: Request):
    user = store.session_user(request.cookies.get("life_session"))
    if not user:
        fail(401, "Sign in with LIFE membership")
    return user

def member_wallet(user=Depends(current)):
    if not user["wallet"]:
        fail(403, "Connect and sign with your Privi wallet first")
    return user

def own(project_id, user):
    project = store.owns(project_id, user["id"])
    if not project:
        fail(404, "Project not found")
    return project

@app.middleware("http")
async def origin_guard(request: Request, call_next):
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        origin = request.headers.get("origin")
        # If browser sends Origin, it must match this site's configured origin.
        if origin is not None and origin.rstrip("/") != ORIGIN:
            return Response(status_code=403, content="Cross-origin write rejected")
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = ("default-src 'self'; script-src 'self'; "
        "style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'")
    return response

@app.get("/")
def root():
    return FileResponse(STATIC / "index.html")
@app.get("/app.js")
def javascript():
    return FileResponse(STATIC / "app.js", media_type="text/javascript")
@app.get("/style.css")
def stylesheet():
    return FileResponse(STATIC / "style.css", media_type="text/css")
@app.get("/health")
def health():
    return {"status": "ok", "service": "privi-life-ai-studio", "staging": STAGING_MODE, "prvi_settlement_enabled": payment_ready()}

@app.get("/api/public-config")
def public_config():
    return {"staging": STAGING_MODE, "real_money_enabled": payment_ready()}

@app.post("/api/auth/demo")
def demo_login(request: Request, response: Response):
    """Disposable isolated sandbox; fake EVM address and valueless demo credits."""
    if not STAGING_MODE:
        fail(404, "Not available")
    existing = store.session_user(request.cookies.get("life_session"))
    if existing:
        return store.get_user(existing["id"])
    ip = request.client.host if request.client else "unknown"
    current = time.monotonic()
    # Prevent unbounded public account creation on a free ephemeral host.
    recent = [t for t in _demo_requests.get(ip, []) if current-t < 3600]
    if len(recent) >= 5:
        fail(429, "Sandbox account limit reached for this hour")
    _demo_requests[ip] = recent + [current]
    user_id = store.uid("demo")
    email = f"{secrets.token_hex(12)}@example.invalid"
    fake_wallet = "0x" + secrets.token_hex(20)
    with store.transaction() as db:
        db.execute("INSERT INTO users (id,email,pwdhash,wallet,member_since) VALUES(?,?,?,?,?)",
                   (user_id,email,password_hash(secrets.token_urlsafe(32)),fake_wallet,store.now()))
    store.credit(user_id, 60, "SANDBOX_VALUELESS_CREDITS", "demo:"+user_id)
    session_response(response,user_id)
    return {**store.get_user(user_id), "demo": True}

@app.post("/api/auth/signup")
def signup(data: AuthInput, response: Response):
    if STAGING_MODE:
        fail(403, "Public signup is disabled in sandbox: use disposable Demo Workspace")
    email = data.email.strip().lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        fail(400, "Invalid email")
    user_id = store.uid("life")
    try:
        with store.transaction() as db:
            db.execute("INSERT INTO users (id,email,pwdhash,member_since) VALUES(?,?,?,?)",
                       (user_id, email, password_hash(data.password), store.now()))
    except Exception as exc:
        if "UNIQUE constraint" in str(exc):
            fail(409, "Account already exists")
        raise
    # Trial balances are explicitly valueless developer credits, never PRVI.
    trial = int(os.getenv("LIFE_DEV_TRIAL_CREDITS", "0"))
    if trial > 0 and not COOKIE_SECURE:
        store.credit(user_id, min(20, trial), "DEV_TRIAL_ONLY", "signup:"+user_id)
    session_response(response, user_id)
    return store.get_user(user_id)

@app.post("/api/auth/login")
def login(data: AuthInput, response: Response):
    if STAGING_MODE:
        fail(403, "Public login disabled in disposable sandbox")
    with store.transaction() as db:
        row = db.execute("SELECT * FROM users WHERE email=?", (data.email.strip().lower(),)).fetchone()
    if not row or not valid_password(data.password, row["pwdhash"]):
        fail(401, "Invalid credentials")
    session_response(response, row["id"])
    return store.get_user(row["id"])

@app.post("/api/auth/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get("life_session")
    if token:
        with store.transaction() as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (store.sha(token),))
    response.delete_cookie("life_session", path="/")
    return {"ok": True}

@app.get("/api/me")
def me(user=Depends(current)):
    return {**user, "membership": "LIFE Member",
            "test_credits": int(os.getenv("LIFE_DEV_TRIAL_CREDITS", "0")) > 0 and not COOKIE_SECURE}

@app.get("/api/catalog")
def catalog(user=Depends(current)):
    return {"agents": agents.catalog(), "services": [
        {"id": k, "name": v[0], "credits": v[1], "integrated": v[2]} for k,v in UTILITIES.items()
    ], "real_prvi_payments": payment_ready(), "fee_bps": FEE_BPS}

@app.post("/api/wallet/challenge")
def challenge(data: WalletInput, user=Depends(current)):
    if STAGING_MODE:
        fail(403, "Use a sandbox wallet only; real wallet linking disabled")
    if not re.fullmatch(r"0x[a-fA-F0-9]{40}", data.wallet):
        fail(400, "Invalid EVM wallet address")
    wallet = data.wallet.lower()
    nonce = secrets.token_urlsafe(24)
    expires = store.now() + 300
    message = (f"Privi LIFE wallet link\nOrigin: {ORIGIN}\nMember: {user['id']}\n"
               f"Wallet: {wallet}\nNonce: {nonce}\nExpires: {expires}")
    with store.transaction() as db:
        db.execute("DELETE FROM challenges WHERE user_id=?", (user["id"],))
        db.execute("INSERT INTO challenges VALUES(?,?,?,?,?)",
                   (store.sha(nonce), user["id"], wallet, message, expires))
    return {"message": message, "wallet": wallet}

@app.post("/api/wallet/link")
def wallet_link(data: WalletLink, user=Depends(current)):
    if STAGING_MODE:
        fail(403, "Wallet linking disabled in sandbox")
    with store.transaction() as db:
        row = db.execute("SELECT * FROM challenges WHERE user_id=? AND wallet=? AND expires>?",
                         (user["id"], data.wallet.lower(), store.now())).fetchone()
        if not row:
            fail(400, "Wallet challenge missing or expired")
        try:
            signer = Account.recover_message(
                __import__("eth_account").messages.encode_defunct(text=row["message"]),
                signature=data.signature).lower()
        except Exception:
            fail(400, "Invalid signature")
        if signer != row["wallet"]:
            fail(403, "Wallet signature does not match")
        used = db.execute("SELECT id FROM users WHERE wallet=? AND id!=?",
                          (signer, user["id"])).fetchone()
        if used:
            fail(409, "Wallet already linked to another membership")
        db.execute("UPDATE users SET wallet=? WHERE id=?", (signer, user["id"]))
        db.execute("DELETE FROM challenges WHERE user_id=?", (user["id"],))
    return store.get_user(user["id"])

@app.get("/api/projects")
def projects(user=Depends(current)):
    with store.transaction() as db:
        return [dict(row) for row in db.execute(
            "SELECT * FROM projects WHERE owner_id=? ORDER BY created DESC", (user["id"],)).fetchall()]

@app.post("/api/projects")
def create_project(data: ProjectCreate, user=Depends(member_wallet)):
    if data.kind not in ("code", "research", "business", "design", "writing", "automation"):
        fail(400, "Invalid project type")
    ident = store.uid("prj")
    with store.transaction() as db:
        db.execute("INSERT INTO projects VALUES (?,?,?,?,?)",
                   (ident, user["id"], data.title.strip(), data.kind, store.now()))
    return {"id": ident, "title": data.title, "kind": data.kind}

@app.get("/api/projects/{project_id}")
def project_detail(project_id: str, user=Depends(current)):
    return own(project_id, user)

@app.get("/api/projects/{project_id}/files")
def list_files(project_id: str, user=Depends(current)):
    own(project_id, user)
    with store.transaction() as db:
        return [dict(r) for r in db.execute("SELECT * FROM files WHERE project_id=? ORDER BY path",
                                           (project_id,)).fetchall()]

@app.put("/api/projects/{project_id}/files")
def save_file(project_id: str, data: FileInput, user=Depends(member_wallet)):
    own(project_id, user)
    try:
        path = agents.safe_path(data.path)
    except ValueError as exc:
        fail(400, str(exc))
    with store.transaction() as db:
        row = db.execute("SELECT version FROM files WHERE project_id=? AND path=?",
                         (project_id, path)).fetchone()
        current_version = row["version"] if row else 0
        if current_version != data.expected_version:
            fail(409, "File changed. Refresh to avoid overwriting another agent.")
        db.execute("INSERT INTO files (project_id,path,content,version) VALUES(?,?,?,?) "
                   "ON CONFLICT(project_id,path) DO UPDATE SET content=excluded.content, "
                   "version=excluded.version",
                   (project_id, path, data.content, current_version+1))
    return {"path": path, "version": current_version+1}

@app.get("/api/projects/{project_id}/runs")
def list_runs(project_id: str, user=Depends(current)):
    own(project_id, user)
    with store.transaction() as db:
        return [dict(r) for r in db.execute(
            "SELECT * FROM runs WHERE project_id=? ORDER BY created DESC", (project_id,)).fetchall()]

@app.get("/api/projects/{project_id}/proposals")
def proposals(project_id: str, user=Depends(current)):
    own(project_id, user)
    with store.transaction() as db:
        rows = db.execute("SELECT * FROM proposals WHERE project_id=? ORDER BY rowid DESC",
                          (project_id,)).fetchall()
    return [{**dict(r), "payload": json.loads(r["payload"])} for r in rows]

async def run_one(run_id, provider, project, task, user_id, snapshots, suggestions, responsibility=""):
    files_context = json.dumps(snapshots, ensure_ascii=False)[:45000]
    instructions = ("You are one of several independent agents working together in Privi LIFE AI Studio. "
        "Only propose changes; NEVER claim to have run code or deployed software. "
        "The human reviews all changes before they merge. "
        "For coding tasks respond ONLY with JSON: "
        '{"summary":"your work","files":[{"path":"src/example.py","content":"full file contents"}]}. '
        "For non-coding tasks, provide a helpful plain text response. "
        "Do not include secrets, private keys, or destructive instructions.")
    prompt = (f"Project: {project['title']} ({project['kind']})\nShared task: {task}\n"
              f"Committed shared files: {files_context}\nOther agent proposals available for review: "
              f"{json.dumps(suggestions)[:12000]}\nWork on a distinct component where sensible.\n"
              f"Your assigned Team Up role: {responsibility or 'General collaborator'}. "
              "Coordinate interfaces through shared requirements. Do not claim another agent approved your code.")
    try:
        result = await agents.generate(provider, instructions, prompt)
        proposed = agents.extract_code_proposal(result) if project["kind"] == "code" else None
        with store.transaction() as db:
            db.execute("UPDATE runs SET status='done',output=? WHERE id=?", (result[:90000], run_id))
            if proposed:
                snapshot_versions = {f["path"]: f["version"] for f in snapshots}
                proposed["files"] = [{**p, "expected_version": snapshot_versions.get(p["path"],0)}
                                     for p in proposed["files"]]
                db.execute("INSERT INTO proposals VALUES(?,?,?,?,?,?)",
                           (store.uid("patch"), run_id, project["id"], proposed["summary"],
                            json.dumps(proposed), "pending"))
    except Exception as exc:
        # Refund failed provider requests; do not expose provider tokens or URLs in errors.
        with store.transaction() as db:
            db.execute("UPDATE runs SET status='failed',error=? WHERE id=?",
                       (type(exc).__name__ + ": provider request failed", run_id))
        store.credit(user_id, AGENT_COST, "AGENT_REFUND", "refund:"+run_id)

@app.post("/api/projects/{project_id}/run-team")
async def run_team(project_id: str, data: TeamRun, user=Depends(member_wallet)):
    project = own(project_id, user)
    if data.mode not in ("parallel", "team_up"):
        fail(400, "Unsupported team mode")
    if data.mode == "team_up" and (project["kind"] != "code" or len(data.agents) < 2):
        fail(400, "Team Up requires a coding project and at least two agents")
    if len(set(data.agents)) != len(data.agents):
        fail(400, "Duplicate agents")
    ready = {a["id"] for a in agents.catalog() if a["ready"]}
    if not set(data.agents).issubset(ready):
        fail(400, "One or more agents are not configured")
    if any(a not in agents.SERVICES and (not STAGING_MODE or a not in agents.SANDBOX_AGENTS) for a in data.agents):
        fail(400, "Unknown agent")
    roles = ["Frontend & user experience", "Backend & integrations",
             "Tests & quality assurance", "Security & reliability",
             "Documentation & developer experience", "System integration"]
    responsibilities = {provider: roles[i] for i, provider in enumerate(data.agents)} if data.mode == "team_up" else {}
    run_ids = [store.uid("run") for _ in data.agents]
    total = AGENT_COST * len(run_ids)
    with store.transaction() as db:
        balance = db.execute("SELECT credits FROM users WHERE id=?", (user["id"],)).fetchone()
        active = db.execute("SELECT COUNT(*) AS n FROM runs r JOIN projects p ON r.project_id=p.id WHERE p.owner_id=? AND r.status='running'", (user["id"],)).fetchone()["n"]
        if active + len(run_ids) > 12:
            fail(429, "Too many active agents; finish current runs before starting more")
        if not balance or balance["credits"] < total:
            fail(402, "Insufficient Privi utility credits")
        db.execute("UPDATE users SET credits=credits-? WHERE id=?", (total,user["id"]))
        for run_id, provider in zip(run_ids, data.agents):
            db.execute("INSERT INTO runs (id,project_id,agent,status,task,created) VALUES(?,?,?,?,?,?)",
                       (run_id, project_id, provider, "running",
                        (f"[Team Up: {responsibilities[provider]}] " if responsibilities else "") + data.task, store.now()))
            db.execute("INSERT INTO ledger VALUES (?,?,?,?,?,?,?,?)",
                       (store.uid("led"),user["id"],"charge","agent_run",-AGENT_COST,
                        AGENT_COST*FEE_BPS*100, "run:"+run_id,store.now()))
        snapshots = [dict(r) for r in db.execute(
            "SELECT path,content,version FROM files WHERE project_id=? ORDER BY path LIMIT 50",
            (project_id,)).fetchall()]
        previews = [dict(r) for r in db.execute(
            "SELECT summary FROM proposals WHERE project_id=? AND status='pending' LIMIT 15",
            (project_id,)).fetchall()]
    await asyncio.gather(*(run_one(run_id, provider, project, data.task, user["id"], snapshots, previews,
                                        responsibilities.get(provider, ""))
                           for run_id, provider in zip(run_ids, data.agents)))
    return {"runs": list_runs(project_id,user), "proposals": proposals(project_id,user),
            "mode": data.mode, "assignments": responsibilities,
            "credits": store.get_user(user["id"])["credits"]}


@app.get("/api/networks/assets")
def network_assets(user=Depends(current)):
    """AI vendors are API providers, not presumed crypto networks."""
    return multichain.inventory(payconfig())


@app.post("/api/networks/swap/quote")
def swap_quote(user=Depends(member_wallet)):
    # No real quoted rate, calldata, wallet approvals, or relayer until a
    # third-party audited bridge and verified token allowlist are integrated.
    fail(503, "PRVI cross-chain swaps are disabled: no audited route or liquidity source")


@app.post("/api/projects/{project_id}/fast-answer")
async def fast_answer(project_id: str, data: FastAnswerRequest, user=Depends(member_wallet)):
    project = own(project_id, user)
    if len(set(data.providers)) != len(data.providers):
        fail(400, "Duplicate providers")
    ready = {a["id"] for a in agents.catalog() if a["ready"]}
    if not set(data.providers).issubset(ready):
        fail(400, "One or more AI providers are unavailable")
    # Key includes LIFE member and project ID, question, exact configured
    # agent selection and accepted file versions. Other members never share cache.
    with store.transaction() as db:
        versions = [dict(row) for row in db.execute(
            "SELECT path,version FROM files WHERE project_id=? ORDER BY path", (project_id,))]
    context_fingerprint = hashlib.sha256(json.dumps({
        "uid": user["id"], "project": project_id, "question": data.question,
        "providers": data.providers, "versions": versions
    },sort_keys=True).encode()).hexdigest()
    cached = fastlane.cache.get(context_fingerprint)
    if cached is not None:
        return {**cached, "cached": True, "charged_credits": 0}

    run_ids = [store.uid("fast") for _ in data.providers]
    total = AGENT_COST * len(run_ids)
    with store.transaction() as db:
        active = db.execute("SELECT COUNT(*) AS n FROM runs r JOIN projects p ON r.project_id=p.id WHERE p.owner_id=? AND r.status='running'", (user["id"],)).fetchone()["n"]
        row = db.execute("SELECT credits FROM users WHERE id=?", (user["id"],)).fetchone()
        if active + len(run_ids) > 12:
            fail(429, "Too many running agents")
        if not row or row["credits"] < total:
            fail(402, "Insufficient Privi utility credits")
        db.execute("UPDATE users SET credits=credits-? WHERE id=?", (total, user["id"]))
        for name, run_id in zip(data.providers, run_ids):
            db.execute("INSERT INTO runs (id,project_id,agent,status,task,created) VALUES (?,?,?,?,?,?)",
                       (run_id,project_id,name,"running","[Fast Lane] "+data.question,store.now()))
            db.execute("INSERT INTO ledger VALUES (?,?,?,?,?,?,?,?)",
                       (store.uid("led"), user["id"], "charge", "fast_answer", -AGENT_COST,
                        AGENT_COST*FEE_BPS*100, "fast:"+run_id,store.now()))

    async def one_provider(name, run_id):
        try:
            reply = await agents.generate(
                name, "Answer precisely and concisely. Never claim to be a quantum processor. "
                      "Do not reveal credentials, and separate speculation from facts.",
                f"Project: {project['title']}\\nQuestion: {data.question}")
            with store.transaction() as db:
                db.execute("UPDATE runs SET status='done',output=? WHERE id=?",
                           (reply[:90000], run_id))
            return reply
        except asyncio.CancelledError:
            # A cancelled dispatched request might have cost provider API tokens.
            with store.transaction() as db:
                db.execute("UPDATE runs SET status='cancelled' WHERE id=?", (run_id,))
            raise
        except Exception:
            with store.transaction() as db:
                db.execute("UPDATE runs SET status='failed',error=? WHERE id=?",
                           ("AI provider failed", run_id))
            store.credit(user["id"],AGENT_COST,"FAST_FAILED_REFUND","refund:"+run_id)
            raise
    workers = {name: (lambda p=name,r=r_id: one_provider(p,r))
               for name,r_id in zip(data.providers,run_ids)}
    try:
        answer = await fastlane.first_success(workers)
    except RuntimeError:
        fail(502,"No selected provider returned an answer")
    payload = {**answer, "cached": False, "charged_credits": total,
               "quantum_hardware_used": False, "method": "classical_parallel_first_success"}
    fastlane.cache.put(context_fingerprint,payload)
    return payload


@app.post("/api/projects/{project_id}/proposals/{proposal_id}/apply")
def apply_proposal(project_id: str, proposal_id: str, user=Depends(member_wallet)):
    own(project_id,user)
    with store.transaction() as db:
        proposal = db.execute("SELECT * FROM proposals WHERE id=? AND project_id=?",
                              (proposal_id, project_id)).fetchone()
        if not proposal:
            fail(404, "Proposal not found")
        if proposal["status"] == "applied":
            return {"status": "applied", "unchanged": True}
        if proposal["status"] != "pending":
            fail(409, "Proposal already closed")
        changed = json.loads(proposal["payload"])["files"]
        for f in changed:
            row = db.execute("SELECT version FROM files WHERE project_id=? AND path=?",
                             (project_id, f["path"])).fetchone()
            if (row["version"] if row else 0) != f["expected_version"]:
                fail(409, "Merge conflict: an agent or member changed "+f["path"])
        for f in changed:
            db.execute("INSERT INTO files VALUES(?,?,?,?) "
                       "ON CONFLICT(project_id,path) DO UPDATE SET "
                       "content=excluded.content,version=excluded.version",
                       (project_id,f["path"],f["content"],f["expected_version"]+1))
        db.execute("UPDATE proposals SET status='applied' WHERE id=?", (proposal_id,))
    return {"status": "applied", "files": [f["path"] for f in changed]}

@app.get("/api/wallet/ledger")
def ledger(user=Depends(current)):
    with store.transaction() as db:
        return [dict(r) for r in db.execute(
            "SELECT * FROM ledger WHERE user_id=? ORDER BY created DESC LIMIT 100",
            (user["id"],)).fetchall()]

def payconfig():
    if STAGING_MODE or os.getenv("PRVI_MAINNET_PAYMENTS_ENABLED") != "1":
        return None
    try:
        chain_id = int(os.environ["PRVI_EVM_CHAIN_ID"])
        rpc = os.environ["PRVI_RPC_URL"]
        treasury = os.environ["PRVI_TREASURY_ADDRESS"].lower()
        genesis = os.environ["PRVI_GENESIS_BLOCK_HASH"].lower()
        per_credit = int(os.environ["PRVI_WEI_PER_CREDIT"])
        confirms = int(os.getenv("PRVI_REQUIRED_CONFIRMATIONS", "12"))
        if (chain_id in (0,1,56,97,11155111,262144) or chain_id < 100 or
            not rpc.startswith("https://") or not re.fullmatch(r"0x[a-f0-9]{64}", genesis) or
            not re.fullmatch(r"0x[a-f0-9]{40}", treasury) or
            per_credit <= 0 or confirms < 12 or not COOKIE_SECURE):
            return None
        return chain_id,rpc,treasury,per_credit,confirms,genesis
    except (KeyError,ValueError):
        return None

def payment_ready():
    return payconfig() is not None

async def verify_chain(config):
    chain_id,rpc_url,treasury,unit,confirms,genesis=config
    if int(await rpc(rpc_url,'eth_chainId',[]),16)!=chain_id:
        fail(503,'Configured chain does not match RPC')
    block=await rpc(rpc_url,'eth_getBlockByNumber',['0x0',False])
    if not block or block.get('hash','').lower()!=genesis:
        fail(503,'PRVI chain genesis does not match verified configuration')

async def rpc(url, method, params):
    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
        response = await client.post(url,json={"jsonrpc":"2.0","id":1,"method":method,"params":params})
        response.raise_for_status()
        data = response.json()
    if "error" in data or "result" not in data:
        fail(503, "Blockchain RPC unavailable")
    return data["result"]

@app.post("/api/wallet/quote")
async def buy_quote(data: QuoteInput, user=Depends(member_wallet)):
    config = payconfig()
    if not config:
        fail(503, "Native PRVI purchases are disabled pending verified mainnet release")
    chain_id,rpc_url,treasury,unit,confirms,genesis = config
    await verify_chain(config)
    amount_wei = str(unit * data.credits)
    quote_id = store.uid("quote")
    with store.transaction() as db:
        db.execute("INSERT INTO quotes VALUES (?,?,?,?,?,?,?,NULL)",
                   (quote_id,user["id"],user["wallet"],data.credits,amount_wei,store.now()+7200,store.now()))
    return {"quote_id":quote_id,"to":treasury,"value_hex":hex(int(amount_wei)),
            "chain_id_hex":hex(chain_id),"credits":data.credits,"required_confirmations":confirms}

@app.post("/api/wallet/redeem")
async def redeem(data: RedeemInput, user=Depends(member_wallet)):
    config = payconfig()
    if not config:
        fail(503,"Native PRVI purchases are disabled")
    if not re.fullmatch(r"0x[a-fA-F0-9]{64}",data.tx_hash):
        fail(400,"Invalid transaction hash")
    with store.transaction() as db:
        quote = db.execute("SELECT * FROM quotes WHERE id=? AND user_id=? AND used_tx IS NULL "
                           "AND wallet=? AND expires>?",
                           (data.quote_id,user["id"],user["wallet"],store.now())).fetchone()
        if not quote:
            fail(409,"Quote expired or already redeemed")
        q = dict(quote)
    chain,rpc_url,treasury,unit,confirms,genesis=config
    await verify_chain(config)
    tx = await rpc(rpc_url,"eth_getTransactionByHash",[data.tx_hash])
    receipt = await rpc(rpc_url,"eth_getTransactionReceipt",[data.tx_hash])
    height = await rpc(rpc_url,"eth_blockNumber",[])
    block = await rpc(rpc_url,"eth_getBlockByNumber",[tx["blockNumber"],False]) if tx and tx.get("blockNumber") else None
    if not tx or not receipt or not tx.get("blockNumber") or not receipt.get("blockNumber"):
        fail(409,"Transaction is not mined")
    if (tx.get("from","").lower()!=q["wallet"] or
        tx.get("to","").lower()!=treasury or
        int(tx.get("value","0x0"),16)<int(q["amount_wei"]) or
        int(receipt.get("status","0x0"),16)!=1 or
        receipt.get("transactionHash","").lower()!=data.tx_hash.lower() or
        receipt.get("blockHash")!=tx.get("blockHash") or
        not block or block.get("hash")!=tx.get("blockHash") or
        int(block.get("timestamp","0x0"),16)<q["created"] or
        int(height,16)-int(receipt["blockNumber"],16)+1<confirms):
        fail(409,"Transaction did not pass wallet, amount, receipt or confirmation checks")
    with store.transaction() as db:
        exists = db.execute("SELECT 1 FROM redemptions WHERE tx_hash=?",
                            (data.tx_hash.lower(),)).fetchone()
        row = db.execute("SELECT * FROM quotes WHERE id=? AND user_id=? AND used_tx IS NULL "
                         "AND expires>?", (q["id"],user["id"],store.now())).fetchone()
        if exists or not row:
            fail(409,"Transaction or quote already used")
        db.execute("INSERT INTO redemptions VALUES(?,?,?,?,?)",
                   (data.tx_hash.lower(),q["id"],user["id"],q["credits"],store.now()))
        db.execute("UPDATE quotes SET used_tx=? WHERE id=?", (data.tx_hash.lower(),q["id"]))
        db.execute("UPDATE users SET credits=credits+? WHERE id=?", (q["credits"],user["id"]))
        db.execute("INSERT INTO ledger VALUES (?,?,?,?,?,?,?,?)",
                   (store.uid("led"),user["id"],"credit","native_prvi_purchase",
                    q["credits"],0,"tx:"+data.tx_hash.lower(),store.now()))
    return {"status":"confirmed","credits_added":q["credits"],
            "balance":store.get_user(user["id"])["credits"]}

@app.post("/api/internal/charge")
def integration_charge(data: InternalCharge,request: Request):
    """Privi-only backend service integration. Never expose service keys to browsers."""
    try:
        keys = json.loads(os.getenv("PRIVI_SERVICE_KEYS_JSON","{}"))
    except ValueError:
        fail(503,"Invalid service configuration")
    token = request.headers.get("x-privi-service-key","")
    if (data.service not in UTILITIES or not isinstance(keys,dict) or
        not isinstance(keys.get(data.service),str) or
        len(keys[data.service])<32 or not hmac.compare_digest(token,keys[data.service])):
        fail(403,"Service key missing or unauthorized")
    user = store.get_user(data.user_id)
    if not user:
        fail(404,"LIFE member not found")
    _,cost,_ = UTILITIES[data.service]
    try:
        ok = store.charge(user["id"],data.service,cost,data.idempotency_key,FEE_BPS)
    except ValueError as exc:
        fail(409,str(exc))
    if not ok:
        fail(402,"Insufficient Privi credits or wallet not linked")
    return {"charged":cost,"service":data.service,"balance":store.get_user(user["id"])["credits"]}
