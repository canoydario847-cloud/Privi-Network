# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Quantum - https://priviflow.us - dariocanoy@priviflow.us
"""Privi Bridge: let an AI agent drive a company's existing software, safely.

An agent registers a bridge to the company's own system (an ERP, MES, scheduling tool or any HTTPS JSON API):
the base URL and a short list of operations, each marked READ (pull data into Privi) or WRITE (push a signed
result back). The person who approved the agent signs that exact scope with their passkey; until then the
bridge does nothing, and it can never call an operation outside the signed scope.

A workflow then runs end to end: pull the data with a READ operation, map it into a Privi Quantum problem,
run it on any backend (paid hardware still needs a Quantum Mandate), push the answer with a WRITE operation,
and seal the whole run (hashes of every request and response) as a post-quantum signed attestation.

Safety: HTTPS only and public internet addresses only (no localhost or private networks) unless the operator
allows it; no redirects; 20 s timeout; 2 MB response cap. Every request Privi sends carries an HMAC signature
the company's software can check (X-Privi-Signature), so it knows the call came from Privi for this bridge.
Any auth header the company gives Privi is stored encrypted (AES-256-GCM) and never shown again.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import re
import secrets
import socket
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import quote, urlencode, urlsplit

import httpx2
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAX_OPERATIONS = 12
MAX_RESPONSE = 2_000_000
MAX_ITEMS = 64
TIMEOUT_S = 20.0
DRAFT_TTL_HOURS = 72
MAX_DAYS = 365

SCHEMA = """
CREATE TABLE IF NOT EXISTS bridges (
    bridge_id     TEXT PRIMARY KEY,
    agent_id      TEXT NOT NULL,
    human_id      TEXT NOT NULL,
    name          TEXT NOT NULL,
    base_url      TEXT NOT NULL,
    operations    TEXT NOT NULL,
    auth_header   TEXT NOT NULL DEFAULT '',
    auth_enc      TEXT NOT NULL DEFAULT '',
    secret_enc    TEXT NOT NULL,
    scope_text    TEXT NOT NULL,
    scope_hash    TEXT NOT NULL,
    status        TEXT NOT NULL,           -- draft | active | revoked
    expires_at    TEXT NOT NULL,
    credential_id TEXT,
    attestation_id TEXT,
    created_at    TEXT NOT NULL,
    activated_at  TEXT,
    revoked_at    TEXT,
    revoked_by    TEXT,
    revocation_attestation_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_bridges_agent ON bridges (agent_id, created_at);
CREATE TABLE IF NOT EXISTS bridge_workflows (
    workflow_id   TEXT PRIMARY KEY,
    bridge_id     TEXT NOT NULL,
    agent_id      TEXT NOT NULL,
    status        TEXT NOT NULL,           -- running | waiting_hardware | done | failed
    problem       TEXT NOT NULL,
    push_op       TEXT NOT NULL DEFAULT '',
    push_params   TEXT NOT NULL DEFAULT '{}',
    job_id        TEXT,
    log           TEXT NOT NULL DEFAULT '[]',
    error         TEXT NOT NULL DEFAULT '',
    attestation_id TEXT,
    created_at    TEXT NOT NULL,
    finished_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_workflows_job ON bridge_workflows (job_id);
"""

_OP_NAME = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_PATH = re.compile(r"^/[A-Za-z0-9_\-./{}~%]*$")
_PARAM = re.compile(r"\{([a-z][a-z0-9_]{0,30})\}")


class BridgeError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime | None = None) -> str:
    return (d or _now()).isoformat(timespec="seconds")


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# ---------------------------------------------------------------- data mapping

def get_path(doc: Any, path: str) -> Any:
    """Dotted path into JSON: 'data.orders', 'items.0.qty'. Empty path = the whole document."""
    cur = doc
    for part in [p for p in str(path or "").split(".") if p != ""]:
        if isinstance(cur, list) and part.lstrip("-").isdigit():
            i = int(part)
            if not -len(cur) <= i < len(cur):
                raise BridgeError(f"path {path!r}: index {i} is out of range")
            cur = cur[i]
        elif isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            raise BridgeError(f"path {path!r}: no field {part!r} in the software's response")
    return cur


def apply_transform(doc: Any, transform: dict) -> dict:
    """Build Privi problem data from the software's JSON.

    transform = {"jobs": {"from": "data.orders", "fields": {"name": "sku", "minutes": "cycle_min"}},
                 "k": {"path": "settings.inspect_count"}, "line_a": {"value": "Press 1"}}
    """
    if not isinstance(transform, dict) or not transform:
        raise BridgeError("transform must map problem fields to the software's data (see quantum_problems)")
    out: dict[str, Any] = {}
    for key, rule in transform.items():
        if not isinstance(rule, dict):
            raise BridgeError(f"transform.{key} must be an object: {{from, fields}} | {{path}} | {{value}}")
        if "value" in rule:
            out[key] = rule["value"]
        elif "path" in rule:
            out[key] = get_path(doc, rule["path"])
        elif "from" in rule:
            rows = get_path(doc, rule["from"])
            if not isinstance(rows, list):
                raise BridgeError(f"transform.{key}: {rule['from']!r} is not a list in the software's response")
            if len(rows) > MAX_ITEMS:
                raise BridgeError(f"transform.{key}: {len(rows)} items; Privi Quantum takes at most {MAX_ITEMS}")
            fields = rule.get("fields")
            if fields is None:
                out[key] = rows
            else:
                if not isinstance(fields, dict) or not fields:
                    raise BridgeError(f"transform.{key}.fields must map target fields to source fields")
                out[key] = [{t: get_path(r, s) for t, s in fields.items()} for r in rows]
        else:
            raise BridgeError(f"transform.{key} needs from, path or value")
    return out


# ---------------------------------------------------------------- network safety

def check_url(url: str, allow_private: bool = False, allow_http: bool = False,
              resolver: Callable[[str], list[str]] | None = None) -> str:
    """Refuse anything but HTTPS to public internet addresses (unless the operator allows private/HTTP for testing)."""
    u = urlsplit(url)
    if u.scheme not in (("https", "http") if allow_http else ("https",)):
        raise BridgeError("the software's address must start with https://")
    if not u.hostname or u.username or u.password:
        raise BridgeError("give a plain https://host/path address (no credentials in the URL)")
    if allow_private:
        return u.hostname
    resolve = resolver or (lambda h: sorted({i[4][0] for i in socket.getaddrinfo(h, u.port or 443, proto=socket.IPPROTO_TCP)}))
    try:
        addrs = resolve(u.hostname)
    except (socket.gaierror, UnicodeError) as e:
        raise BridgeError(f"cannot find {u.hostname}: {e}")
    if not addrs:
        raise BridgeError(f"cannot find {u.hostname}")
    for a in addrs:
        ip = ipaddress.ip_address(a.split("%")[0])
        if not ip.is_global or ip.is_multicast:
            raise BridgeError(f"{u.hostname} points to a private or reserved address ({a}); Privi Bridge only calls "
                              "public internet services")
    return u.hostname


def signature(secret: bytes, ts: int, method: str, path: str, body: bytes) -> str:
    msg = f"{ts}.{method.upper()}.{path}.{sha256(body)}".encode()
    return "v1=" + hmac.new(secret, msg, hashlib.sha256).hexdigest()


VERIFY_SNIPPET = """# In your software: check that a request really came from Privi Bridge
import hashlib, hmac, time
def from_privi(secret: bytes, headers, method: str, path_with_query: str, body: bytes) -> bool:
    ts = int(headers["X-Privi-Timestamp"])
    if abs(time.time() - ts) > 300:
        return False
    msg = f"{ts}.{method.upper()}.{path_with_query}.{hashlib.sha256(body).hexdigest()}".encode()
    good = "v1=" + hmac.new(secret, msg, hashlib.sha256).hexdigest()
    return hmac.compare_digest(good, headers["X-Privi-Signature"])"""


# ---------------------------------------------------------------- store

class Bridges:
    def __init__(self, db_path: str, key: bytes, allow_private: bool = False, allow_http: bool = False,
                 http: httpx2.Client | None = None, resolver: Callable[[str], list[str]] | None = None):
        if len(key) != 32:
            raise ValueError("bridge key must be 32 bytes")
        self._aead = AESGCM(key)
        self.allow_private, self.allow_http = allow_private, allow_http
        self._http, self._resolver = http, resolver
        self._lock = threading.Lock()
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.commit()

    @property
    def http(self) -> httpx2.Client:
        if self._http is None:
            self._http = httpx2.Client(timeout=TIMEOUT_S, follow_redirects=False)
        return self._http

    # -- secrets at rest
    def _enc(self, b: bytes, aad: str) -> str:
        n = secrets.token_bytes(12)
        return base64.b64encode(n + self._aead.encrypt(n, b, aad.encode())).decode()

    def _dec(self, s: str, aad: str) -> bytes:
        raw = base64.b64decode(s)
        return self._aead.decrypt(raw[:12], raw[12:], aad.encode())

    # -- registration
    def draft(self, agent: dict, human_id: str, name: str, base_url: str, operations: list[dict],
              auth_header: str = "", auth_value: str = "", days: int = 90) -> dict:
        name = " ".join(str(name or "").split())[:80]
        if len(name) < 2:
            raise BridgeError("give the software a name (e.g. 'Acme ERP')")
        base_url = str(base_url or "").strip().rstrip("/")
        host = check_url(base_url + "/", self.allow_private, self.allow_http, self._resolver)
        if not isinstance(operations, list) or not 1 <= len(operations) <= MAX_OPERATIONS:
            raise BridgeError(f"give 1-{MAX_OPERATIONS} operations")
        ops, seen = [], set()
        for o in operations:
            if not isinstance(o, dict):
                raise BridgeError("each operation is {name, method, path, kind, description}")
            n = str(o.get("name", "")).strip()
            m = str(o.get("method", "GET")).upper()
            p = str(o.get("path", "")).strip()
            k = str(o.get("kind", "read" if m == "GET" else "write")).lower()
            if not _OP_NAME.match(n) or n in seen:
                raise BridgeError(f"operation name {n!r} must be unique, lowercase letters, digits or _")
            if m not in ("GET", "POST", "PUT", "PATCH"):
                raise BridgeError(f"{n}: method must be GET, POST, PUT or PATCH")
            if not _PATH.match(p) or ".." in p:
                raise BridgeError(f"{n}: path must start with / and use only letters, digits and - _ . / {{param}}")
            if k not in ("read", "write"):
                raise BridgeError(f"{n}: kind must be read or write")
            if k == "read" and m != "GET":
                raise BridgeError(f"{n}: read operations use GET")
            if k == "write" and m == "GET":
                raise BridgeError(f"{n}: write operations use POST, PUT or PATCH")
            seen.add(n)
            ops.append({"name": n, "method": m, "path": p, "kind": k,
                        "description": " ".join(str(o.get("description", "")).split())[:160]})
        auth_header = str(auth_header or "").strip()
        if auth_header and not re.fullmatch(r"[A-Za-z0-9-]{1,60}", auth_header):
            raise BridgeError("auth_header must be a header name like Authorization or X-Api-Key")
        if auth_value and not auth_header:
            raise BridgeError("say which header the credential goes in (auth_header)")
        if not 1 <= int(days) <= MAX_DAYS:
            raise BridgeError(f"days must be 1-{MAX_DAYS}")
        bid = "br_" + secrets.token_hex(8)
        secret = secrets.token_bytes(32)
        expires = _now() + timedelta(days=int(days))
        lines = ["Privi Bridge", f"Bridge: {bid}",
                 f"I allow the AI agent {agent['name']} ({agent['agent_id']}), operated by {agent['operator']},",
                 f"to connect to my software \"{name}\" at {base_url} and to use only these operations:"]
        for o in ops:
            lines.append(f"- {o['kind'].upper()} {o['method']} {o['path']}" + (f": {o['description']}" if o["description"] else ""))
        if any(o["kind"] == "write" for o in ops):
            lines.append("WRITE operations send Privi Quantum's signed results into my software.")
        lines += [f"Credential stored by Privi: {'yes, in the ' + auth_header + ' header (encrypted)' if auth_value else 'none'}",
                  f"Expires: {_iso(expires)}", "Every call is signed and logged. I can revoke this bridge at any time."]
        scope = "\n".join(lines)
        with self._lock:
            self._db.execute(
                "INSERT INTO bridges (bridge_id, agent_id, human_id, name, base_url, operations, auth_header, auth_enc, "
                "secret_enc, scope_text, scope_hash, status, expires_at, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,'draft',?,?)",
                (bid, agent["agent_id"], human_id, name, base_url, json.dumps(ops), auth_header,
                 self._enc(auth_value.encode(), bid + ":auth") if auth_value else "", self._enc(secret, bid + ":secret"),
                 scope, sha256(scope.encode()), _iso(expires), _iso()))
            self._db.commit()
        return {**self.public(bid), "host": host, "signing_secret": base64.b64encode(secret).decode(),
                "signing_secret_note": "Give this to your software to verify X-Privi-Signature. It is shown only once.",
                "verify_snippet": VERIFY_SNIPPET}

    def challenge(self, bid: str, action: str) -> bytes:
        b = self._row(bid)
        if not b:
            raise BridgeError("unknown bridge")
        if action not in ("sign", "revoke"):
            raise BridgeError("action must be sign or revoke")
        return hashlib.sha256(f"privi-bridge:v1:{action}:{bid}:{b['scope_hash']}".encode()).digest()

    def activate(self, bid: str, human_id: str, credential_id: str) -> dict:
        b = self._row(bid)
        if not b:
            raise BridgeError("unknown bridge")
        if b["status"] != "draft":
            raise BridgeError(f"bridge is already {b['status']}")
        if datetime.fromisoformat(b["created_at"]) + timedelta(hours=DRAFT_TTL_HOURS) < _now():
            raise BridgeError("this draft expired; ask the agent for a new one")
        if human_id != b["human_id"]:
            raise BridgeError("only the person who approved this agent can sign its bridge")
        with self._lock:
            self._db.execute("UPDATE bridges SET status='active', credential_id=?, activated_at=? WHERE bridge_id=? AND status='draft'",
                             (credential_id, _iso(), bid))
            self._db.commit()
        return self._row(bid)

    def revoke(self, bid: str, by: str) -> dict:
        b = self._row(bid)
        if not b:
            raise BridgeError("unknown bridge")
        if b["status"] == "revoked":
            raise BridgeError("bridge is already revoked")
        with self._lock:
            self._db.execute("UPDATE bridges SET status='revoked', revoked_at=?, revoked_by=? WHERE bridge_id=?", (_iso(), by, bid))
            self._db.commit()
        return self._row(bid)

    def set_attestation(self, bid: str, aid: str, field: str = "attestation_id") -> None:
        assert field in ("attestation_id", "revocation_attestation_id")
        with self._lock:
            self._db.execute(f"UPDATE bridges SET {field}=? WHERE bridge_id=?", (aid, bid))
            self._db.commit()

    # -- calling the software
    def usable(self, bid: str, agent_id: str, op_name: str, kind: str) -> tuple[dict, dict]:
        b = self._row(bid)
        if not b:
            raise BridgeError("unknown bridge")
        st = self._status(b)
        if st != "active":
            raise BridgeError({"draft": "the bridge is not signed yet: the person must sign it at the bridge page",
                               "revoked": "the bridge was revoked", "expired": "the bridge expired"}[st])
        if agent_id != b["agent_id"]:
            raise BridgeError("this bridge belongs to a different agent")
        op = next((o for o in json.loads(b["operations"]) if o["name"] == op_name), None)
        if not op:
            raise BridgeError(f"operation {op_name!r} is not in the signed scope of this bridge")
        if op["kind"] != kind:
            raise BridgeError(f"operation {op_name!r} is a {op['kind'].upper()} operation, not {kind.upper()}")
        return b, op

    def call(self, b: dict, op: dict, params: dict | None = None, body: Any = None, workflow_id: str = "") -> dict:
        """Call one signed-scope operation. Returns {status, url, request_sha256, response_sha256, bytes, json?}."""
        params = dict(params or {})
        path = op["path"]
        for p in _PARAM.findall(path):
            if p not in params:
                raise BridgeError(f"operation {op['name']} needs parameter {p!r}")
            v = str(params.pop(p))
            if not v or len(v) > 120:
                raise BridgeError(f"parameter {p!r} must be 1-120 characters")
            path = path.replace("{" + p + "}", quote(v, safe=""))
        if params and op["kind"] == "write":
            raise BridgeError("write operations take path parameters only; the body is Privi's signed result")
        if len(params) > 20 or any(not re.fullmatch(r"[A-Za-z0-9_.\-]{1,40}", str(k)) for k in params):
            raise BridgeError("query parameter names must be simple (letters, digits, _ . -)")
        query = urlencode({k: str(v)[:200] for k, v in params.items()})
        path_q = path + (("?" + query) if query else "")
        url = b["base_url"] + path_q
        check_url(url, self.allow_private, self.allow_http, self._resolver)
        data = json.dumps(body, sort_keys=True, separators=(",", ":")).encode() if body is not None else b""
        ts = int(time.time())
        secret = self._dec(b["secret_enc"], b["bridge_id"] + ":secret")
        headers = {"User-Agent": "PriviBridge/1.0 (+https://privi-quantum.onrender.com)", "Accept": "application/json",
                   "X-Privi-Bridge": b["bridge_id"], "X-Privi-Workflow": workflow_id, "X-Privi-Timestamp": str(ts),
                   "X-Privi-Signature": signature(secret, ts, op["method"], urlsplit(b["base_url"]).path + path_q, data)}
        if data:
            headers["Content-Type"] = "application/json"
        if b["auth_enc"]:
            headers[b["auth_header"]] = self._dec(b["auth_enc"], b["bridge_id"] + ":auth").decode()
        try:
            r = self.http.request(op["method"], url, content=data or None, headers=headers)
        except httpx2.HTTPError as e:
            raise BridgeError(f"could not reach {urlsplit(url).hostname}: {type(e).__name__}")
        raw = r.content[:MAX_RESPONSE + 1]
        if len(raw) > MAX_RESPONSE:
            raise BridgeError("the software's response is over 2 MB")
        out: dict[str, Any] = {"operation": op["name"], "method": op["method"], "url": url, "status": r.status_code,
                               "request_sha256": sha256(data), "response_sha256": sha256(raw), "bytes": len(raw)}
        if 300 <= r.status_code < 400:
            raise BridgeError(f"the software answered with a redirect ({r.status_code}); Privi Bridge does not follow redirects")
        if r.status_code >= 400:
            raise BridgeError(f"the software answered {r.status_code} to {op['name']}")
        if op["kind"] == "read":
            try:
                out["json"] = json.loads(raw.decode() or "null")
            except (ValueError, UnicodeDecodeError):
                raise BridgeError(f"{op['name']} did not return JSON")
        return out

    # -- workflows
    def new_workflow(self, b: dict, agent_id: str, problem: str, push_op: str, push_params: dict | None) -> str:
        wid = "wf_" + secrets.token_hex(8)
        with self._lock:
            self._db.execute("INSERT INTO bridge_workflows (workflow_id, bridge_id, agent_id, status, problem, push_op, push_params, "
                             "created_at) VALUES (?,?,?,'running',?,?,?,?)",
                             (wid, b["bridge_id"], agent_id, problem, push_op or "", json.dumps(push_params or {}), _iso()))
            self._db.commit()
        return wid

    def log(self, wid: str, entry: dict) -> None:
        with self._lock:
            r = self._db.execute("SELECT log FROM bridge_workflows WHERE workflow_id=?", (wid,)).fetchone()
            lg = json.loads(r["log"]) if r else []
            lg.append({"at": _iso(), **{k: v for k, v in entry.items() if k != "json"}})
            self._db.execute("UPDATE bridge_workflows SET log=? WHERE workflow_id=?", (json.dumps(lg), wid))
            self._db.commit()

    def update_workflow(self, wid: str, **fields) -> None:
        allowed = {"status", "job_id", "error", "attestation_id", "finished_at"}
        assert set(fields) <= allowed
        cols = ", ".join(f"{k}=?" for k in fields)
        with self._lock:
            self._db.execute(f"UPDATE bridge_workflows SET {cols} WHERE workflow_id=?", (*fields.values(), wid))
            self._db.commit()

    def workflow(self, wid: str) -> dict | None:
        r = self._db.execute("SELECT * FROM bridge_workflows WHERE workflow_id=?", (str(wid)[:40],)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["log"], d["push_params"] = json.loads(d["log"]), json.loads(d["push_params"])
        return d

    def workflows_for_job(self, job_id: str) -> list[str]:
        return [r["workflow_id"] for r in self._db.execute(
            "SELECT workflow_id FROM bridge_workflows WHERE job_id=? AND status='waiting_hardware'", (job_id,))]

    # -- views
    def _row(self, bid: str) -> dict | None:
        r = self._db.execute("SELECT * FROM bridges WHERE bridge_id=?", (str(bid)[:40],)).fetchone()
        return dict(r) if r else None

    def get(self, bid: str) -> dict | None:
        return self._row(bid)

    @staticmethod
    def _status(b: dict) -> str:
        if b["status"] == "active" and datetime.fromisoformat(b["expires_at"]) <= _now():
            return "expired"
        return b["status"]

    def public(self, bid: str) -> dict:
        b = self._row(bid)
        if not b:
            raise BridgeError("unknown bridge")
        return {"bridge_id": b["bridge_id"], "status": self._status(b), "agent_id": b["agent_id"], "name": b["name"],
                "base_url": b["base_url"], "operations": json.loads(b["operations"]),
                "stores_credential": bool(b["auth_enc"]), "expires_at": b["expires_at"], "scope_text": b["scope_text"],
                "scope_sha256": b["scope_hash"], "signed_with": "passkey, user verified" if b["activated_at"] else None,
                "created_at": b["created_at"], "activated_at": b["activated_at"], "attestation_id": b["attestation_id"],
                "revoked_at": b["revoked_at"], "revoked_by": b["revoked_by"],
                "revocation_attestation_id": b["revocation_attestation_id"]}

    def recent_workflows(self, bid: str, limit: int = 20) -> list[dict]:
        return [{"workflow_id": r["workflow_id"], "status": r["status"], "problem": r["problem"], "job_id": r["job_id"],
                 "created_at": r["created_at"], "finished_at": r["finished_at"], "attestation_id": r["attestation_id"]}
                for r in self._db.execute("SELECT * FROM bridge_workflows WHERE bridge_id=? ORDER BY created_at DESC LIMIT ?",
                                          (bid, limit))]
