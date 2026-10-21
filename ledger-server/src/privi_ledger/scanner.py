"""Privi Scan: a public, tamper-evident trust registry for remote MCP servers.

What it does
  * Syncs the official MCP Registry and keeps a list of every public streamable-HTTP MCP endpoint.
  * Probes each one read-only: initialize + tools/list. It never calls a tool.
  * Scores the tool definitions for tool poisoning (hidden instructions, concealment, credential
    exfiltration, tool shadowing, invisible characters) and records whether auth or payment is required.
  * Hashes every tool definition. The first observation and every later change is written to the Privi
    Ledger transparency log, which is Merkle-logged and anchored on-chain. Nobody, including Privi, can
    rewrite after the fact what a server's tools said and when they changed. That history is the asset.
  * Publishes a searchable directory, badges, a change feed (Privi Live channel "scan" / "scan:<id>"),
    and a free check any agent can run before it connects to a server.

Paid hooks: watchlists with pinned tool hashes (free 3, Pro 500) and real-time change events; on-demand
rescans; owners claim their listing by publishing a token at /.well-known/privi-scan.txt.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import secrets
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx2

REGISTRY_URL = os.getenv("SCAN_REGISTRY_URL", "https://registry.modelcontextprotocol.io").rstrip("/")
SCAN_ORG_ID = "org_5ca95ca95ca95ca9"
SCAN_STREAM = "mcp-registry"
REPROBE_S = float(os.getenv("SCAN_REPROBE_S", str(6 * 3600)))
SYNC_S = float(os.getenv("SCAN_SYNC_S", str(6 * 3600)))
BATCH = int(os.getenv("SCAN_BATCH", "150"))
WORKERS = int(os.getenv("SCAN_WORKERS", "16"))
FRESH_S = 3600                      # a check newer than this is served from cache
LIVE_PROBES_PER_MIN = int(os.getenv("SCAN_LIVE_PER_MIN", "20"))
MAX_BODY = 2_000_000
MAX_TOOLS = 500
MAX_WATCH = {"free": 3, "pro": 500, "enterprise": 5000}
CHANGE_FLAG_DAYS = 30
UA = "PriviScan/1.0 (read-only MCP trust probe; never calls tools; +https://privi-ledger.onrender.com/scan)"
PROTOCOL = "2025-06-18"
LISTED = ("ok", "auth_required", "paid_gate")
ANALYZER_VERSION = "2"     # bump when rules change; stored servers are re-graded from their saved tools

SCHEMA = """
CREATE TABLE IF NOT EXISTS scan_servers (
    server_id    TEXT PRIMARY KEY,
    url          TEXT NOT NULL UNIQUE,
    name         TEXT, title TEXT, description TEXT, version TEXT, website TEXT, repository TEXT,
    source       TEXT NOT NULL,
    registry_status TEXT,
    first_seen   TEXT NOT NULL,
    last_probe   TEXT,
    status       TEXT NOT NULL DEFAULT 'pending',
    detail       TEXT,
    http_status  INTEGER, latency_ms INTEGER,
    server_name  TEXT, server_version TEXT, protocol TEXT, auth TEXT,
    tools_hash   TEXT, tool_count INTEGER, tools TEXT,
    score        INTEGER, grade TEXT, findings TEXT,
    changes      INTEGER NOT NULL DEFAULT 0,
    last_change_at TEXT, changed_tools TEXT,
    ledger_seq   INTEGER, ledger_hash TEXT,
    claimed_org  TEXT, claim_token TEXT, hidden INTEGER NOT NULL DEFAULT 0,
    fails        INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_scan_probe ON scan_servers (last_probe);
CREATE TABLE IF NOT EXISTS scan_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id TEXT NOT NULL, at TEXT NOT NULL, kind TEXT NOT NULL,
    tools_hash TEXT, tool_count INTEGER, score INTEGER, grade TEXT,
    diff TEXT, manifest TEXT, tools TEXT, ledger_seq INTEGER, ledger_hash TEXT
);
CREATE INDEX IF NOT EXISTS idx_scan_hist ON scan_history (server_id, id);
CREATE TABLE IF NOT EXISTS scan_watch (
    org_id TEXT NOT NULL, server_id TEXT NOT NULL, pinned_hash TEXT, created_at TEXT NOT NULL,
    PRIMARY KEY (org_id, server_id)
);
CREATE TABLE IF NOT EXISTS scan_meta (k TEXT PRIMARY KEY, v TEXT);
"""


class ScanError(Exception):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime | None = None) -> str:
    return (d or _now()).isoformat(timespec="seconds")


def _parse(s: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(s) if s else None
    except ValueError:
        return None


def canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def normalize_url(url: str) -> str:
    u = urlsplit((url or "").strip())
    if u.scheme not in ("https", "http") or not u.hostname:
        raise ScanError("url must be an absolute https:// URL of an MCP endpoint")
    if u.username or u.password:
        raise ScanError("do not put credentials in the URL")
    host = u.hostname.lower()
    netloc = host + (f":{u.port}" if u.port and u.port not in (80, 443) else "")
    return urlunsplit((u.scheme, netloc, u.path or "/", u.query, ""))


def server_id_for(url: str) -> str:
    return "mcp_" + sha(url)[:12]


# ---------------------------------------------------------------- tool analysis

def tool_canon(t: dict) -> dict:
    return {k: t.get(k) for k in ("name", "title", "description", "inputSchema", "outputSchema", "annotations")
            if t.get(k) is not None}


def tool_hash(t: dict) -> str:
    return sha(canon(tool_canon(t)))


def manifest_of(tools: list[dict]) -> dict[str, str]:
    return {str(t.get("name", ""))[:200]: tool_hash(t) for t in tools}


def tools_hash_of(manifest: dict[str, str]) -> str:
    return sha("\n".join(f"{n}:{h}" for n, h in sorted(manifest.items())))


def _strings(obj: Any, out: list[str], depth: int = 0) -> None:
    if depth > 12:
        return
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            out.append(str(k))
            _strings(v, out, depth + 1)
    elif isinstance(obj, list):
        for v in obj[:200]:
            _strings(v, out, depth + 1)


I = re.IGNORECASE | re.DOTALL
VERB = r"(read|cat|open|send|upload|include|pass|forward|post|paste|exfiltrate|copy|attach|share)"
SECRET_FILE = (r"(\.ssh/id_|\bid_(rsa|ed25519|ecdsa|dsa)\b(?!\.pub)|\.ssh/(config|known_hosts)\b|\.aws/credentials|\.npmrc\b|\.netrc\b"
               r"|claude_desktop_config|\bmcp\.json\b|\.cursor/mcp|\.env\b)")
SECRET_WORD = r"(seed\s+phrase|mnemonic|private\s+keys?\b|wallet\s+keys?)"
RULES: list[tuple[str, str, str, re.Pattern]] = [
    ("high", "prompt_injection", "text tries to override the agent's instructions",
     re.compile(r"ignore\s+(all\s+|any\s+)?(the\s+|your\s+)?(previous|prior|above|earlier|system|other)\s+(instructions|prompts?|rules|messages)"
                r"|disregard\s+(all\s+|the\s+|your\s+)?(previous|prior|above|system)\s+(instructions|prompts?|rules)"
                r"|(^|[\s>])<\s*/?\s*(important|system|instructions?)\s*>|\[\s*(system|important)\s*\]\s*:?"
                r"|new\s+system\s+prompt|you\s+are\s+now\s+(in\s+)?(developer|admin|god|jailbreak)\s+mode", I)),
    ("high", "concealment", "text tells the agent to hide its actions or these instructions from the user",
     re.compile(r"(do\s+not|don'?t|never)\s+(tell|inform|mention\s+to|notify|alert)\s+the\s+user\s+(about\s+|of\s+)?"
                r"(this|these|that\s+you|what\s+you|the\s+(instruction|step|note|request|tool\s+call)s?)\b"
                r"|(do\s+not|don'?t|never)\s+(mention|reveal|disclose|show)\s+(this|these)\s+(instruction|step|note|tool|requirement)s?\s+(to\s+the\s+user)?"
                r"|without\s+(telling|informing|notifying|alerting|asking)\s+the\s+user"
                r"|the\s+user\s+(must|should)\s+(not|never)\s+(know|see|be\s+told|find\s+out)\s+(about\s+)?(this|these|that)", I)),
    ("high", "exfiltration", "text asks the agent to read or send private files (SSH keys, credentials, .env, MCP configs)",
     re.compile(VERB + r"\b.{0,80}" + SECRET_FILE + r"|" + SECRET_FILE + r".{0,80}\b" + VERB + r"\b", I)),
    ("medium", "secret_request", "text asks for a seed phrase or private key; an honest tool almost never needs one",
     re.compile(VERB + r"\b.{0,60}" + SECRET_WORD + r"|" + SECRET_WORD + r".{0,60}\b" + VERB + r"\b", I)),
    ("medium", "tool_shadowing", "text tries to change how the agent uses other tools or servers",
     re.compile(r"(instead\s+of|rather\s+than)\s+(using|calling)\s+(the\s+|any\s+)?(other|another)\s+(tools?|servers?)"
                r"|(always|must)\s+(call|use|run|invoke)\s+this\s+tool\s+(first|before|instead)"
                r"|before\s+(using|calling)\s+any\s+other\s+tool"
                r"|when(ever)?\s+(the\s+user|you)\s+(asks?|wants?|requests?)\s+to\s+.{0,60}(email|send|pay|transfer).{0,40}(use|call)\s+this\s+tool", I)),
]
HIDDEN = re.compile("[​-‏⁠-⁤‪-‮⁦-⁩﻿\U000e0000-\U000e007f]|\x1b\\[")
SECRET_ARG = re.compile(r"^(password|passwd|secret|private_?key|seed|mnemonic|seed_?phrase|wallet_?key)$", re.I)
IMPACT = re.compile(r"(^|[_.\-])(exec|execute|shell|bash|command|terminal|eval|run_code|delete|drop|destroy|purge|wipe|"
                    r"transfer|withdraw|send_money|send_payment|send_funds|payout|sign_transaction|write_file|rm)([_.\-]|$)", re.I)
PENALTY = {"high": 35, "medium": 12, "low": 4, "info": 0}


def analyze(tools: list[dict] | None, status: str, auth: str | None, changed: list[str] | None = None) -> list[dict]:
    out: list[dict] = []
    if tools is None:
        return out
    impactful = []
    for t in tools:
        name = str(t.get("name", ""))[:120]
        texts: list[str] = []
        _strings({k: t.get(k) for k in ("title", "description", "inputSchema", "annotations")}, texts)
        blob = "\n".join(texts)
        seen = set()
        for sev, code, why, rx in RULES:
            m = rx.search(blob)
            if m and code not in seen:
                seen.add(code)
                s = max(0, m.start() - 40)
                out.append({"severity": sev, "code": code, "tool": name, "detail": why,
                            "evidence": blob[s:m.end() + 40].replace("\n", " ")[:220]})
        if HIDDEN.search(blob) or HIDDEN.search(name):
            out.append({"severity": "medium", "code": "hidden_characters", "tool": name,
                        "detail": "invisible or terminal-control characters in the tool definition"})
        desc = t.get("description") or ""
        if isinstance(desc, str) and len(desc) > 4000:
            out.append({"severity": "low", "code": "oversized_description", "tool": name,
                        "detail": f"description is {len(desc)} characters; long text can hide instructions"})
        props = ((t.get("inputSchema") or {}).get("properties") or {}) if isinstance(t.get("inputSchema"), dict) else {}
        bad = [p for p in props if SECRET_ARG.match(str(p))] if isinstance(props, dict) else []
        if bad:
            out.append({"severity": "low", "code": "secret_in_arguments", "tool": name,
                        "detail": f"asks the agent to pass {', '.join(bad[:3])} as an argument (secrets end up in model context and logs)"})
        if IMPACT.search(name):
            impactful.append(name)
    if impactful:
        out.append({"severity": "info", "code": "high_impact_capability", "tool": ", ".join(impactful[:8]),
                    "detail": "can run commands, delete data or move money; require a human approval for these"})
        if status == "ok" and not auth:
            out.append({"severity": "low", "code": "public_high_impact", "tool": ", ".join(impactful[:8]),
                        "detail": "high-impact tools are listed without authentication; confirm the server authenticates each call"})
    if changed:
        out.append({"severity": "medium", "code": "definition_changed", "tool": ", ".join(changed[:8]),
                    "detail": "tool definitions changed in the last 30 days; re-review before trusting (rug-pull risk)"})
    return out


def score_of(findings: list[dict]) -> tuple[int, str]:
    s = max(0, 100 - sum(PENALTY[f["severity"]] for f in findings))
    g = "A" if s >= 90 else "B" if s >= 75 else "C" if s >= 60 else "D" if s >= 40 else "F"
    return s, g


def verdict_of(row: dict) -> str:
    st = row.get("status")
    if st not in LISTED:
        return "unreachable" if st in ("unreachable", "error", "not_mcp", "blocked") else "unknown"
    f = row.get("findings") or []
    if any(x["severity"] == "high" for x in f):
        return "danger"
    if st != "ok":
        return "unverified"
    if any(x["severity"] == "medium" for x in f) or (row.get("score") or 0) < 75:
        return "caution"
    return "ok"


# ---------------------------------------------------------------- the service

class Scanner:
    def __init__(self, ledger, live=None, public_url: str = "", client: httpx2.Client | None = None,
                 allow_private: bool = False):
        self.ledger, self.live = ledger, live
        self.db, self.lock = ledger._db, ledger._lock
        self.public_url = (public_url or "").rstrip("/")
        self.allow_private = allow_private or os.getenv("SCAN_ALLOW_PRIVATE") == "1"
        self._client = client
        self._probe_times: list[float] = []
        self._pl = threading.Lock()
        with self.lock:
            self.db.executescript(SCHEMA)
            if not self.db.execute("SELECT 1 FROM orgs WHERE org_id=?", (SCAN_ORG_ID,)).fetchone():
                self.db.execute("INSERT INTO orgs (org_id, name, key_hash, created_at) VALUES (?,?,?,?)",
                                (SCAN_ORG_ID, "Privi Scan (public MCP trust registry)", "!" + secrets.token_hex(32), _iso()))
            self.db.commit()

    @property
    def client(self) -> httpx2.Client:
        if self._client is None:
            self._client = httpx2.Client(timeout=httpx2.Timeout(connect=8.0, read=20.0, write=10.0, pool=10.0),
                                         follow_redirects=False, headers={"User-Agent": UA})
        return self._client

    # ---- safety ---------------------------------------------------------

    def check_url(self, url: str) -> str:
        url = normalize_url(url)
        u = urlsplit(url)
        if u.scheme != "https" and not self.allow_private:
            raise ScanError("only https:// endpoints are scanned")
        host = u.hostname or ""
        if host == "localhost" or host.endswith((".local", ".internal", ".localhost", ".lan")):
            raise ScanError("host is not public")
        if self.public_url and host == urlsplit(self.public_url).hostname and not self.allow_private:
            raise ScanError("cannot scan this server itself")
        if not self.allow_private:
            try:
                infos = socket.getaddrinfo(host, u.port or 443, 0, socket.SOCK_STREAM)
            except OSError:
                raise ScanError(f"cannot resolve {host}")
            for *_, sa in infos:
                if not ipaddress.ip_address(sa[0]).is_global:
                    raise ScanError("host resolves to a non-public address")
        return url

    # ---- MCP probe --------------------------------------------------------

    def _post(self, url: str, payload: dict, session: str | None, proto: str | None):
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if session:
            h["Mcp-Session-Id"] = session
        if proto:
            h["MCP-Protocol-Version"] = proto
        target = url
        for _ in range(3):
            with self.client.stream("POST", target, content=json.dumps(payload).encode(), headers=h) as r:
                if r.status_code in (301, 302, 307, 308) and r.headers.get("location"):
                    target = self.check_url(urljoin(target, r.headers["location"]))
                    continue
                buf = bytearray()
                for chunk in r.iter_bytes():
                    buf += chunk
                    if len(buf) > MAX_BODY:
                        raise ScanError("response too large")
                return r.status_code, r.headers, bytes(buf)
        raise ScanError("too many redirects")

    @staticmethod
    def _message(body: bytes, ctype: str, rid) -> dict | None:
        cands: list = []
        text = body.decode("utf-8", "replace")
        if "event-stream" in ctype:
            for block in text.split("\n\n"):
                data = "\n".join(l[5:].lstrip() for l in block.splitlines() if l.startswith("data:"))
                if data:
                    try:
                        cands.append(json.loads(data))
                    except ValueError:
                        pass
        else:
            try:
                cands.append(json.loads(text))
            except ValueError:
                return None
        for c in cands:
            for m in (c if isinstance(c, list) else [c]):
                if isinstance(m, dict) and m.get("id") == rid and ("result" in m or "error" in m):
                    return m
        return None

    def probe(self, url: str) -> dict:
        out: dict[str, Any] = {"status": "error", "detail": "", "http_status": None, "latency_ms": None, "auth": None,
                               "tools": None, "server_name": None, "server_version": None, "protocol": None}
        t0 = time.monotonic()
        try:
            url = self.check_url(url)
            init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": PROTOCOL, "capabilities": {},
                               "clientInfo": {"name": "privi-scan", "version": "1.0",
                                              "title": "Privi Scan (read-only; never calls tools)"}}}
            st, hdr, body = self._post(url, init, None, None)
            out["http_status"], out["latency_ms"] = st, int((time.monotonic() - t0) * 1000)
            wa = hdr.get("www-authenticate", "")
            if st in (401, 403):
                out.update(status="auth_required", auth="oauth" if "resource_metadata" in wa else "required",
                           detail="tools are behind authentication; listing shows registry metadata only")
                return out
            if st == 402:
                out.update(status="paid_gate", detail="the endpoint asks for payment before initialize")
                return out
            msg = self._message(body, hdr.get("content-type", ""), 1)
            if st >= 400 or not msg or "result" not in msg:
                out.update(status="not_mcp", detail=f"no MCP initialize result (HTTP {st})")
                return out
            res = msg["result"] if isinstance(msg["result"], dict) else {}
            info = res.get("serverInfo") or {}
            out.update(server_name=str(info.get("name", ""))[:200] or None, server_version=str(info.get("version", ""))[:60] or None,
                       protocol=str(res.get("protocolVersion", ""))[:20] or None)
            session = hdr.get("mcp-session-id")
            proto = out["protocol"]
            try:
                self._post(url, {"jsonrpc": "2.0", "method": "notifications/initialized"}, session, proto)
            except Exception:
                pass
            caps = res.get("capabilities") if isinstance(res.get("capabilities"), dict) else {}
            if "tools" not in caps:
                out.update(status="ok", tools=[], detail="server exposes no tools")
                return out
            tools: list[dict] = []
            cursor = None
            for page in range(10):
                params = {"cursor": cursor} if cursor else {}
                st, hdr, body = self._post(url, {"jsonrpc": "2.0", "id": 2 + page, "method": "tools/list", "params": params},
                                           session, proto)
                if st in (401, 403):
                    out.update(status="auth_required", auth="oauth" if "resource_metadata" in hdr.get("www-authenticate", "")
                               else "required", detail="initialize is open but tools/list needs authentication")
                    return out
                m = self._message(body, hdr.get("content-type", ""), 2 + page)
                if not m or "result" not in m:
                    out.update(status="error", detail=f"tools/list failed (HTTP {st})")
                    return out
                r = m["result"] if isinstance(m["result"], dict) else {}
                tools += [t for t in (r.get("tools") or []) if isinstance(t, dict) and t.get("name")]
                cursor = r.get("nextCursor")
                if not cursor or len(tools) >= MAX_TOOLS:
                    break
            out.update(status="ok", tools=tools[:MAX_TOOLS])
            return out
        except ScanError as e:
            out.update(status="blocked", detail=str(e))
        except httpx2.TimeoutException:
            out.update(status="unreachable", detail="timed out")
        except httpx2.HTTPError as e:
            out.update(status="unreachable", detail=type(e).__name__)
        except Exception as e:  # never let one server break the crawl
            out.update(status="error", detail=f"{type(e).__name__}: {str(e)[:120]}")
        out["latency_ms"] = out["latency_ms"] or int((time.monotonic() - t0) * 1000)
        return out

    # ---- registry sync ----------------------------------------------------

    def sync_registry(self, max_pages: int = 300) -> int:
        cursor, n = None, 0
        for _ in range(max_pages):
            params = {"limit": "100", "version": "latest"}
            if cursor:
                params["cursor"] = cursor
            r = self.client.get(f"{REGISTRY_URL}/v0/servers", params=params, headers={"Accept": "application/json"})
            r.raise_for_status()
            data = r.json()
            for item in data.get("servers") or []:
                s = item.get("server") or {}
                meta = (item.get("_meta") or {}).get("io.modelcontextprotocol.registry/official") or {}
                if meta.get("isLatest") is False:
                    continue
                for rem in s.get("remotes") or []:
                    url = rem.get("url") or ""
                    if rem.get("type") not in ("streamable-http", "http") or "{" in url or not url.startswith("https://"):
                        continue
                    try:
                        url = normalize_url(url)
                    except ScanError:
                        continue
                    n += self._upsert(url, "registry", s, meta.get("status"))
            cursor = (data.get("metadata") or {}).get("nextCursor")
            if not cursor:
                break
        with self.lock:
            self.db.execute("INSERT INTO scan_meta (k, v) VALUES ('registry_synced', ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                            (_iso(),))
            self.db.commit()
        return n

    def _upsert(self, url: str, source: str, s: dict | None = None, reg_status: str | None = None) -> int:
        s = s or {}
        repo = s.get("repository") or {}
        vals = (str(s.get("name", ""))[:200] or None, str(s.get("title", ""))[:200] or None,
                str(s.get("description", ""))[:1000] or None, str(s.get("version", ""))[:60] or None,
                str(s.get("websiteUrl", ""))[:300] or None, str(repo.get("url", "") if isinstance(repo, dict) else "")[:300] or None)
        sid = server_id_for(url)
        with self.lock:
            new = not self.db.execute("SELECT 1 FROM scan_servers WHERE server_id=?", (sid,)).fetchone()
            if new:
                self.db.execute("INSERT INTO scan_servers (server_id, url, name, title, description, version, website, repository, "
                                "source, registry_status, first_seen) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                                (sid, url, *vals, source, reg_status, _iso()))
            elif source == "registry":
                self.db.execute("UPDATE scan_servers SET name=?, title=?, description=?, version=?, website=?, repository=?, "
                                "source='registry', registry_status=? WHERE server_id=?", (*vals, reg_status, sid))
            self.db.commit()
        return 1 if new else 0

    # ---- recording a probe --------------------------------------------------

    def _row(self, sid: str) -> dict | None:
        with self.lock:
            r = self.db.execute("SELECT * FROM scan_servers WHERE server_id=?", (sid,)).fetchone()
        if not r:
            return None
        d = dict(r)
        for k in ("tools", "findings", "changed_tools"):
            d[k] = json.loads(d[k]) if d.get(k) else None
        return d

    def store(self, sid: str, p: dict) -> dict:
        prev = self._row(sid)
        if not prev:
            raise ScanError("unknown server")
        now = _now()
        tools = p["tools"]
        manifest = manifest_of(tools) if tools is not None else None
        th = tools_hash_of(manifest) if manifest is not None else None
        changed_tools = prev.get("changed_tools") or []
        lc = _parse(prev.get("last_change_at"))
        if lc and now - lc > timedelta(days=CHANGE_FLAG_DAYS):
            changed_tools = []
        diff = None
        kind = None
        if th and th != prev.get("tools_hash"):
            if prev.get("tools_hash"):
                old = {}
                with self.lock:
                    h = self.db.execute("SELECT manifest FROM scan_history WHERE server_id=? AND manifest IS NOT NULL "
                                        "ORDER BY id DESC LIMIT 1", (sid,)).fetchone()
                if h:
                    old = json.loads(h["manifest"])
                diff = {"added": sorted(set(manifest) - set(old))[:100], "removed": sorted(set(old) - set(manifest))[:100],
                        "modified": sorted(n for n in manifest if n in old and old[n] != manifest[n])[:100],
                        "from_hash": prev["tools_hash"], "to_hash": th}
                changed_tools = sorted(set(changed_tools) | set(diff["modified"]))[:100]
                kind = "changed"
            else:
                kind = "first_seen"
        findings = analyze(tools, p["status"], p["auth"], changed_tools) if tools is not None else (prev.get("findings") or [])
        score, grade = score_of(findings) if tools is not None else (None, None)
        if tools is None and p["status"] in ("unreachable", "error", "blocked") and prev.get("tools_hash"):
            score, grade = prev.get("score"), prev.get("grade")   # keep last known good analysis while temporarily down
        seq = ehash = None
        if kind:
            label = prev.get("name") or p.get("server_name") or sid
            summary = (f"First observed tools of MCP server {label}: {len(tools)} tools, tools_hash {th}" if kind == "first_seen" else
                       f"Tools of MCP server {label} changed: +{len(diff['added'])} -{len(diff['removed'])} "
                       f"~{len(diff['modified'])}; tools_hash {th}")
            # facts only: what the server published and when. Grades are Privi's (revisable) opinion and are not logged.
            det = {"server_id": sid, "url": prev["url"], "registry_name": prev.get("name"), "tools_hash": th,
                   "tool_count": len(tools), "kind": kind, "tool_hashes_sample": {n[:60]: h for n, h in sorted(manifest.items())[:40]}}
            if diff:
                det["diff"] = {k: (v[:40] if isinstance(v, list) else v) for k, v in diff.items()}
            try:
                e = self.ledger.record(SCAN_ORG_ID, SCAN_STREAM, "Privi Scan", "data_access", summary[:1900],
                                       prev["url"][:500], "success", det)
                seq, ehash = e["seq"], e["entry_hash"]
            except ValueError:
                pass
            tools_json = canon(tools)
            with self.lock:
                self.db.execute("INSERT INTO scan_history (server_id, at, kind, tools_hash, tool_count, score, grade, diff, manifest, "
                                "tools, ledger_seq, ledger_hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                                (sid, _iso(now), kind, th, len(tools), score, grade, canon(diff) if diff else None,
                                 canon(manifest), tools_json if len(tools_json) < 600_000 else None, seq, ehash))
                self.db.commit()
        upd = {"last_probe": _iso(now), "status": p["status"], "detail": p["detail"][:300], "http_status": p["http_status"],
               "latency_ms": p["latency_ms"], "auth": p["auth"],
               "fails": 0 if p["status"] in LISTED else (prev.get("fails") or 0) + 1}
        if p["status"] == "ok":
            upd.update(server_name=p["server_name"], server_version=p["server_version"], protocol=p["protocol"])
        if tools is not None:
            upd.update(tools_hash=th, tool_count=len(tools), tools=canon(tools)[:600_000], findings=canon(findings),
                       score=score, grade=grade, changed_tools=canon(changed_tools))
        elif p["status"] in ("auth_required", "paid_gate"):
            upd.update(findings=canon([]), score=None, grade=None)
        if kind == "changed":
            upd.update(changes=(prev.get("changes") or 0) + 1, last_change_at=_iso(now))
        if seq:
            upd.update(ledger_seq=seq, ledger_hash=ehash)
        with self.lock:
            self.db.execute(f"UPDATE scan_servers SET {', '.join(k + '=?' for k in upd)} WHERE server_id=?",
                            (*upd.values(), sid))
            self.db.commit()
        row = self._row(sid)
        self._announce(row, prev, kind, diff, findings)
        return row

    def _announce(self, row: dict, prev: dict, kind: str | None, diff: dict | None, findings: list[dict]) -> None:
        if not self.live or row.get("hidden"):
            return
        base = {"server_id": row["server_id"], "name": row.get("name") or row.get("server_name"), "url": row["url"],
                "grade": row.get("grade"), "score": row.get("score"), "page": f"{self.public_url}/scan/s/{row['server_id']}"}
        events = []
        if kind == "changed":
            events.append(("scan.tools_changed", {**base, **(diff or {}), "ledger_seq": row.get("ledger_seq")}))
        elif kind == "first_seen":
            events.append(("scan.server_listed", {**base, "tool_count": row.get("tool_count")}))
        had_high = any(f["severity"] == "high" for f in (prev.get("findings") or []))
        highs = [f for f in findings if f["severity"] == "high"]
        if highs and not had_high:
            events.append(("scan.risk_found", {**base, "findings": highs[:10]}))
        if prev.get("status") in LISTED and row["status"] not in LISTED and (prev.get("fails") or 0) == 0:
            events.append(("scan.server_down", {**base, "status": row["status"], "detail": row.get("detail")}))
        for typ, data in events:
            try:
                self.live.emit("scan", typ, data)
                self.live.emit(f"scan:{row['server_id']}", typ, data)
                with self.lock:
                    orgs = [r["org_id"] for r in self.db.execute("SELECT org_id FROM scan_watch WHERE server_id=?",
                                                                    (row["server_id"],)).fetchall()]
                    if row.get("claimed_org") and row["claimed_org"] not in orgs:
                        orgs.append(row["claimed_org"])
                for o in orgs:
                    self.live.emit(f"org:{o}", typ, data)
            except Exception:
                pass

    # ---- crawl loop --------------------------------------------------------

    def due(self, limit: int) -> list[dict]:
        cutoff = _iso(_now() - timedelta(seconds=REPROBE_S))
        day = _iso(_now() - timedelta(days=1))
        with self.lock:
            rows = self.db.execute(
                "SELECT server_id, url FROM scan_servers WHERE hidden=0 AND (last_probe IS NULL OR (last_probe < ? AND "
                "(fails < 3 OR last_probe < ?))) ORDER BY last_probe IS NOT NULL, last_probe LIMIT ?",
                (cutoff, day, limit)).fetchall()
        return [dict(r) for r in rows]

    def reanalyze_all(self) -> int:
        """Re-grade every stored tool list with the current rules (no network, no log entries: the evidence is the
        tool definitions, which do not change; only Privi's opinion of them does)."""
        with self.lock:
            m = self.db.execute("SELECT v FROM scan_meta WHERE k='analyzer'").fetchone()
            if m and m["v"] == ANALYZER_VERSION:
                return 0
            ids = [r["server_id"] for r in self.db.execute("SELECT server_id FROM scan_servers WHERE tools IS NOT NULL").fetchall()]
        n = 0
        for sid in ids:
            row = self._row(sid)
            if row is None or row.get("tools") is None:
                continue
            f = analyze(row["tools"], row["status"], row.get("auth"), row.get("changed_tools") or [])
            sc, g = score_of(f)
            with self.lock:
                self.db.execute("UPDATE scan_servers SET findings=?, score=?, grade=? WHERE server_id=?", (canon(f), sc, g, sid))
            n += 1
        with self.lock:
            self.db.execute("INSERT INTO scan_meta (k, v) VALUES ('analyzer', ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                            (ANALYZER_VERSION,))
            self.db.commit()
        print(f"privi-scan: re-graded {n} servers with analyzer v{ANALYZER_VERSION}", flush=True)
        return n

    def run_once(self) -> int:
        self.reanalyze_all()
        with self.lock:
            m = self.db.execute("SELECT v FROM scan_meta WHERE k='registry_synced'").fetchone()
        last = _parse(m["v"]) if m else None
        if not last or (_now() - last).total_seconds() > SYNC_S:
            try:
                n = self.sync_registry()
                print(f"privi-scan: registry synced, {n} new endpoints", flush=True)
            except Exception as e:
                print(f"privi-scan: registry sync failed: {e}", flush=True)
        batch = self.due(BATCH)
        if not batch:
            return 0
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            results = list(ex.map(lambda r: (r["server_id"], self.probe(r["url"])), batch))
        changed = 0
        for sid, p in results:
            try:
                before = self._row(sid)
                after = self.store(sid, p)
                changed += int(after.get("tools_hash") != before.get("tools_hash"))
            except Exception as e:
                print(f"privi-scan: store {sid} failed: {e}", flush=True)
        print(f"privi-scan: probed {len(batch)}, {changed} new or changed", flush=True)
        return changed

    def start(self, interval_s: float = 300.0) -> threading.Thread:
        def loop():
            time.sleep(30)
            while True:
                try:
                    self.run_once()
                except Exception as e:
                    print(f"privi-scan: round failed: {e}", flush=True)
                time.sleep(interval_s)
        t = threading.Thread(target=loop, daemon=True, name="privi-scan")
        t.start()
        return t

    # ---- public reads -------------------------------------------------------

    def _live_budget(self) -> bool:
        with self._pl:
            now = time.monotonic()
            self._probe_times = [t for t in self._probe_times if now - t < 60]
            if len(self._probe_times) >= LIVE_PROBES_PER_MIN:
                return False
            self._probe_times.append(now)
            return True

    def check(self, url: str, expected_tools_hash: str | None = None, force: bool = False) -> dict:
        """The free pre-connection check. Cached when fresh; otherwise probed now (rate-limited)."""
        url = self.check_url(url)
        sid = server_id_for(url)
        row = self._row(sid)
        fresh = row and row.get("last_probe") and (_now() - _parse(row["last_probe"])).total_seconds() < FRESH_S
        probed_now = False
        if not fresh or force:
            if not self._live_budget():
                if not row:
                    raise ScanError("live check capacity is busy; retry in a minute")
            else:
                p = self.probe(url)
                probed_now = True
                if not row:
                    if p["status"] not in LISTED:
                        return {"url": url, "listed": False, "verdict": "unreachable" if p["status"] != "not_mcp" else "not_mcp",
                                "status": p["status"], "detail": p["detail"],
                                "note": "Not added to the directory: the endpoint did not answer as an MCP server."}
                    self._upsert(url, "submitted")
                row = self.store(sid, p)
        out = self.public(row, full=False)
        out["probed_now"] = probed_now
        if expected_tools_hash:
            exp = expected_tools_hash.strip().lower()
            same = exp == (row.get("tools_hash") or "")
            out["matches_expected_tools_hash"] = same
            if not same:
                out["verdict"] = "danger" if out["verdict"] == "danger" else "changed"
                with self.lock:
                    h = self.db.execute("SELECT at FROM scan_history WHERE server_id=? AND tools_hash=? ORDER BY id DESC LIMIT 1",
                                        (sid, exp)).fetchone()
                out["expected_hash_last_seen"] = h["at"] if h else None
                out["advice"] = ("The tools changed since you approved this server. Re-review the definitions "
                                 f"({self.public_url}/scan/s/{sid}) before letting an agent use them.")
        return out

    GRADING_NOTE = ("Grades and findings are automated heuristics over the server's public tool text, not a security audit "
                    "or an accusation. Read the evidence. Owners can claim the listing (scan_claim_start) to rescan or respond.")

    def public(self, row: dict, full: bool = True) -> dict:
        sid = row["server_id"]
        f = row.get("findings") or []
        d = {"server_id": sid, "name": row.get("name"), "title": row.get("title") or row.get("server_name"),
             "url": row["url"], "description": row.get("description"), "status": row["status"], "detail": row.get("detail"),
             "verdict": verdict_of(row), "score": row.get("score"), "grade": row.get("grade"),
             "tool_count": row.get("tool_count"), "tools_hash": row.get("tools_hash"), "auth": row.get("auth"),
             "findings": {"high": sum(1 for x in f if x["severity"] == "high"),
                          "medium": sum(1 for x in f if x["severity"] == "medium"),
                          "low": sum(1 for x in f if x["severity"] == "low")},
             "changes": row.get("changes") or 0, "last_change_at": row.get("last_change_at"),
             "first_seen": row["first_seen"], "last_probe": row.get("last_probe"), "source": row["source"],
             "owner_verified": bool(row.get("claimed_org")),
             "page": f"{self.public_url}/scan/s/{sid}", "badge": f"{self.public_url}/scan/badge/{sid}.svg"}
        if full:
            d.update(grading_note=self.GRADING_NOTE, findings_detail=f, version=row.get("version"), website=row.get("website"), repository=row.get("repository"),
                     server_name=row.get("server_name"), server_version=row.get("server_version"), protocol=row.get("protocol"),
                     latency_ms=row.get("latency_ms"), registry_status=row.get("registry_status"),
                     tools=[{"name": t.get("name"), "title": t.get("title"), "description": t.get("description"),
                             "inputSchema": t.get("inputSchema"), "annotations": t.get("annotations"), "hash": tool_hash(t)}
                            for t in (row.get("tools") or [])],
                     evidence={"what": "every first observation and change of this server's tools is an entry in the Privi Ledger "
                                       "transparency log (Merkle tree, anchored on-chain); the tools_hash commits to every tool definition",
                               "org_id": SCAN_ORG_ID, "stream_id": SCAN_STREAM, "seq": row.get("ledger_seq"),
                               "entry_hash": row.get("ledger_hash"),
                               "inclusion_proof": f"{self.public_url}/log/inclusion?hash={row['ledger_hash']}" if row.get("ledger_hash") else None,
                               "tools_hash_rule": "sha256 of sorted lines '<name>:<sha256 of canonical tool JSON>' joined by \\n; "
                                                  "canonical tool = {name,title,description,inputSchema,outputSchema,annotations}, "
                                                  "JSON with sorted keys and no spaces"})
        return d

    def get(self, sid: str) -> dict:
        row = self._row((sid or "").strip())
        if not row or row.get("hidden"):
            raise ScanError("no such server in Privi Scan")
        return row

    def history(self, sid: str, limit: int = 50, with_tools: bool = False) -> list[dict]:
        self.get(sid)
        with self.lock:
            rows = self.db.execute("SELECT * FROM scan_history WHERE server_id=? ORDER BY id DESC LIMIT ?",
                                   (sid, max(1, min(limit, 200)))).fetchall()
        out = []
        for r in rows:
            d = {"at": r["at"], "kind": r["kind"], "tools_hash": r["tools_hash"], "tool_count": r["tool_count"],
                 "score": r["score"], "grade": r["grade"], "diff": json.loads(r["diff"]) if r["diff"] else None,
                 "ledger_seq": r["ledger_seq"], "entry_hash": r["ledger_hash"]}
            if with_tools and r["tools"]:
                d["tools"] = json.loads(r["tools"])
            out.append(d)
        return out

    def search(self, q: str = "", grade: str = "", verdict: str = "", limit: int = 50, offset: int = 0,
               include_unreachable: bool = False, sort: str = "name") -> dict:
        where, args = ["hidden=0"], []
        if not include_unreachable:
            where.append(f"status IN ({','.join('?' * len(LISTED))})")
            args += list(LISTED)
        if q:
            where.append("(name LIKE ? OR title LIKE ? OR description LIKE ? OR url LIKE ? OR server_name LIKE ?)")
            args += [f"%{q[:80]}%"] * 5
        if grade:
            where.append("grade=?")
            args.append(grade.upper()[:1])
        order = {"name": "COALESCE(title, name, server_name, url) COLLATE NOCASE",
                 "score": "score IS NULL, score DESC", "risk": "score IS NULL, score ASC",
                 "changed": "last_change_at IS NULL, last_change_at DESC", "new": "first_seen DESC"}.get(sort, "name")
        sql_w = " AND ".join(where)
        with self.lock:
            total = self.db.execute(f"SELECT COUNT(*) FROM scan_servers WHERE {sql_w}", args).fetchone()[0]
            rows = self.db.execute(f"SELECT server_id FROM scan_servers WHERE {sql_w} ORDER BY {order} LIMIT ? OFFSET ?",
                                   (*args, max(1, min(limit, 200)), max(0, offset))).fetchall()
        items = [self.public(self._row(r["server_id"]), full=False) for r in rows]
        if verdict:
            items = [i for i in items if i["verdict"] == verdict]
        return {"total": total, "offset": offset, "items": items}

    def changes(self, limit: int = 50) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT h.*, s.name, s.title, s.url, s.hidden FROM scan_history h JOIN scan_servers s "
                                   "USING (server_id) WHERE h.kind='changed' AND s.hidden=0 ORDER BY h.id DESC LIMIT ?",
                                   (max(1, min(limit, 200)),)).fetchall()
        return [{"server_id": r["server_id"], "name": r["title"] or r["name"], "url": r["url"], "at": r["at"],
                 "diff": json.loads(r["diff"]) if r["diff"] else None, "grade": r["grade"], "ledger_seq": r["ledger_seq"],
                 "page": f"{self.public_url}/scan/s/{r['server_id']}"} for r in rows]

    def stats(self) -> dict:
        with self.lock:
            by_status = {r["status"]: r["n"] for r in self.db.execute(
                "SELECT status, COUNT(*) n FROM scan_servers WHERE hidden=0 GROUP BY status").fetchall()}
            by_grade = {r["grade"]: r["n"] for r in self.db.execute(
                "SELECT grade, COUNT(*) n FROM scan_servers WHERE hidden=0 AND grade IS NOT NULL GROUP BY grade").fetchall()}
            tools = self.db.execute("SELECT COALESCE(SUM(tool_count),0) FROM scan_servers WHERE hidden=0 AND status='ok'").fetchone()[0]
            ch = self.db.execute("SELECT COUNT(*) FROM scan_history WHERE kind='changed'").fetchone()[0]
            high = self.db.execute("SELECT COUNT(*) FROM scan_servers WHERE hidden=0 AND findings LIKE '%\"severity\":\"high\"%'").fetchone()[0]
            m = self.db.execute("SELECT v FROM scan_meta WHERE k='registry_synced'").fetchone()
        return {"servers": sum(by_status.values()), "by_status": by_status, "by_grade": by_grade,
                "tools_indexed": tools, "tool_changes_recorded": ch, "servers_with_high_risk_findings": high,
                "registry_synced_at": m["v"] if m else None, "source": f"{REGISTRY_URL} plus servers submitted via mcp_server_check",
                "evidence_stream": {"org_id": SCAN_ORG_ID, "stream_id": SCAN_STREAM}}

    # ---- organization features ----------------------------------------------

    def _plan(self, org_id: str) -> str:
        try:
            return self.live.plan_of(org_id) if self.live else "free"
        except Exception:
            return "free"

    def resolve(self, server: str) -> str:
        s = (server or "").strip()
        if s.startswith("mcp_"):
            if not self._row(s):
                raise ScanError("no such server in Privi Scan")
            return s
        sid = server_id_for(normalize_url(s))
        if not self._row(sid):
            raise ScanError("that server is not in Privi Scan yet; run mcp_server_check on its URL first")
        return sid

    def watch(self, org_id: str, server: str, repin: bool = True) -> dict:
        sid = self.resolve(server)
        row = self.get(sid)
        plan = self._plan(org_id)
        with self.lock:
            n = self.db.execute("SELECT COUNT(*) FROM scan_watch WHERE org_id=?", (org_id,)).fetchone()[0]
            exists = self.db.execute("SELECT 1 FROM scan_watch WHERE org_id=? AND server_id=?", (org_id, sid)).fetchone()
        if not exists and n >= MAX_WATCH[plan]:
            raise ScanError(f"the {plan} plan watches up to {MAX_WATCH[plan]} servers; call ledger_upgrade_pro for 500")
        with self.lock:
            if exists and not repin:
                pass
            else:
                self.db.execute("INSERT INTO scan_watch (org_id, server_id, pinned_hash, created_at) VALUES (?,?,?,?) "
                                "ON CONFLICT(org_id, server_id) DO UPDATE SET pinned_hash=excluded.pinned_hash",
                                (org_id, sid, row.get("tools_hash"), _iso()))
            self.db.commit()
        return {"server_id": sid, "pinned_tools_hash": row.get("tools_hash"), "watching": True,
                "events": "scan.tools_changed / scan.risk_found / scan.server_down arrive on your private 'org' Live channel in real time"}

    def unwatch(self, org_id: str, server: str) -> dict:
        sid = self.resolve(server)
        with self.lock:
            n = self.db.execute("DELETE FROM scan_watch WHERE org_id=? AND server_id=?", (org_id, sid)).rowcount
            self.db.commit()
        if not n:
            raise ScanError("you are not watching that server")
        return {"server_id": sid, "watching": False}

    def watchlist(self, org_id: str) -> dict:
        with self.lock:
            rows = self.db.execute("SELECT * FROM scan_watch WHERE org_id=? ORDER BY created_at", (org_id,)).fetchall()
        items = []
        for w in rows:
            row = self._row(w["server_id"])
            if not row:
                continue
            p = self.public(row, full=False)
            p.update(pinned_tools_hash=w["pinned_hash"], drifted=bool(w["pinned_hash"]) and w["pinned_hash"] != row.get("tools_hash"))
            items.append(p)
        plan = self._plan(org_id)
        return {"plan": plan, "limit": MAX_WATCH[plan], "watching": len(items), "items": items,
                "drifted": [i["server_id"] for i in items if i["drifted"]]}

    def claim_start(self, org_id: str, server: str) -> dict:
        sid = self.resolve(server)
        row = self.get(sid)
        if row.get("claimed_org") and row["claimed_org"] != org_id:
            raise ScanError("another organization already verified ownership of this server")
        tok = row.get("claim_token") if row.get("claim_token", "") and row["claim_token"].startswith(org_id + ":") else None
        if not tok:
            tok = f"{org_id}:{secrets.token_hex(16)}"
            with self.lock:
                self.db.execute("UPDATE scan_servers SET claim_token=? WHERE server_id=?", (tok, sid))
                self.db.commit()
        u = urlsplit(row["url"])
        return {"server_id": sid, "token": "privi-scan-verification=" + tok.split(":", 1)[1],
                "publish_at": f"{u.scheme}://{u.netloc}/.well-known/privi-scan.txt",
                "then": "call scan_claim_verify with the same server; the file must contain the token line exactly"}

    def claim_verify(self, org_id: str, server: str) -> dict:
        sid = self.resolve(server)
        row = self.get(sid)
        tok = row.get("claim_token") or ""
        if not tok.startswith(org_id + ":"):
            raise ScanError("start with scan_claim_start")
        u = urlsplit(row["url"])
        wk = self.check_url(f"{u.scheme}://{u.netloc}/.well-known/privi-scan.txt")
        try:
            r = self.client.get(wk)
            body = r.text[:4000] if r.status_code == 200 else ""
        except httpx2.HTTPError:
            body = ""
        if ("privi-scan-verification=" + tok.split(":", 1)[1]) not in body:
            raise ScanError(f"token not found at {wk}")
        with self.lock:
            self.db.execute("UPDATE scan_servers SET claimed_org=? WHERE server_id=?", (org_id, sid))
            self.db.commit()
        try:
            self.ledger.record(org_id, "privi-scan", "Privi Scan", "approval", f"Verified ownership of MCP server {row['url']}",
                               row["url"][:500], "success", {"server_id": sid})
        except ValueError:
            pass
        return {"server_id": sid, "owner_verified": True, "badge": f"{self.public_url}/scan/badge/{sid}.svg",
                "you_can_now": ["scan_rescan any time", "scan_owner_listing to hide or show the listing",
                                "change events on your org Live channel"]}

    def owner_listing(self, org_id: str, server: str, listed: bool) -> dict:
        sid = self.resolve(server)
        row = self._row(sid)
        if not row or row.get("claimed_org") != org_id:
            raise ScanError("only the verified owner can change the listing (scan_claim_start)")
        with self.lock:
            self.db.execute("UPDATE scan_servers SET hidden=? WHERE server_id=?", (0 if listed else 1, sid))
            self.db.commit()
        return {"server_id": sid, "listed": listed,
                "note": "history already written to the transparency log stays there; hiding removes it from the directory"}

    def rescan(self, org_id: str, server: str) -> dict:
        sid = self.resolve(server)
        row = self.get(sid)
        if row.get("claimed_org") != org_id and self._plan(org_id) == "free":
            raise ScanError("on-demand rescans are for the verified owner or Pro organizations (ledger_upgrade_pro)")
        return self.public(self.store(sid, self.probe(row["url"])))


# ---------------------------------------------------------------- badge

def badge(row: dict | None) -> str:
    if not row:
        label, val, color = "privi scan", "unknown", "#8a8f98"
    else:
        v = verdict_of(row)
        g = row.get("grade")
        val = {"danger": "risk found", "unreachable": "offline", "unverified": "auth only", "unknown": "pending"}.get(v) \
            or (f"grade {g}" if g else v)
        color = {"ok": "#1f9d55", "caution": "#c98a0b", "danger": "#d0342c", "changed": "#c98a0b"}.get(v, "#6b7280")
        if row.get("claimed_org") and v == "ok":
            val += " ✓"
        label = "privi scan"
    lw, vw = 70, max(54, 8 + 7 * len(val))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{lw + vw}" height="20" role="img" aria-label="{label}: {val}">'
            f'<title>{label}: {val}</title><rect width="{lw}" height="20" fill="#24292f"/>'
            f'<rect x="{lw}" width="{vw}" height="20" fill="{color}"/>'
            f'<g fill="#fff" font-family="Verdana,DejaVu Sans,sans-serif" font-size="11" text-anchor="middle">'
            f'<text x="{lw / 2}" y="14">{label}</text><text x="{lw + vw / 2}" y="14">{val}</text></g></svg>')


PAGE = Path(__file__).parent / "scan.html"
