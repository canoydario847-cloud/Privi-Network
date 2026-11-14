"""Privi Chem: bounded chemistry provenance, append-only evidence and data receipts.
No synthesis instructions, physical automation, fungible coin minting, or unverified chain claims.
Copyright (c) 2026 Privi World Corp.
"""
from __future__ import annotations
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

MAX_BYTES = 32768
HEX64 = re.compile(r"^[a-f0-9]{64}$")
FORMULA = re.compile(r"^[A-Za-z0-9()\[\]·.+\- ]{1,160}$")
STATUSES = {"simulation", "measurement"}
CANON = lambda o: json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
SHA = lambda x: hashlib.sha256(x.encode("utf-8")).hexdigest()
NOW = lambda: datetime.now(timezone.utc).isoformat()

class ChemError(ValueError):
    pass

def short_text(value, length=250):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= length:
        raise ChemError("required text is missing or too long")
    return value.strip()

def clean_hash(value, required=False):
    if value is None and not required:
        return None
    if not isinstance(value, str) or not HEX64.fullmatch(value.lower()):
        raise ChemError("source/code hash must be a 64-character SHA-256 hex string")
    return value.lower()

def validate_data(data):
    if not isinstance(data, dict) or len(data) > 30:
        raise ChemError("data must be an object of at most 30 simple measurements")
    for name, item in data.items():
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_ -]{0,63}", name):
            raise ChemError("invalid measurement name")
        if not isinstance(item, dict) or set(item) != {"value", "unit"}:
            raise ChemError("each measurement needs value and unit")
        value, unit = item["value"], item["unit"]
        if type(value) not in (float, int) or not -1e20 < value < 1e20:
            raise ChemError("measurement value must be finite and bounded")
        if not isinstance(unit, str) or not re.fullmatch(r"[A-Za-z0-9%°µ/*^(). +-]{1,30}", unit):
            raise ChemError("invalid unit")
    return data

class ChemStore:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.lock = threading.RLock()
        with self.db() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
              id TEXT PRIMARY KEY, owner TEXT NOT NULL, title TEXT NOT NULL,
              formula TEXT NOT NULL, created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS entries (
              id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
              seq INTEGER NOT NULL, source_type TEXT NOT NULL, payload TEXT NOT NULL,
              payload_hash TEXT NOT NULL, previous_hash TEXT NOT NULL,
              chain_hash TEXT NOT NULL, token_id TEXT NOT NULL UNIQUE,
              created TEXT NOT NULL, UNIQUE(project_id,seq));
            """)
    def db(self):
        con=sqlite3.connect(self.path, timeout=10)
        con.row_factory=sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        return con

    def create(self, owner, doc):
        if not isinstance(doc, dict): raise ChemError("JSON object required")
        title = short_text(doc.get("title"), 120)
        formula = short_text(doc.get("formula"), 160)
        if not FORMULA.fullmatch(formula): raise ChemError("invalid formula notation")
        project_id = "chem_" + secrets.token_hex(12)
        with self.lock, self.db() as c:
            c.execute("INSERT INTO projects VALUES (?,?,?,?,?)",(project_id,owner,title,formula,NOW()))
        return {"project_id":project_id,"title":title,"formula":formula,"status":"created"}

    def project(self, owner, pid):
        with self.db() as c:
            p=c.execute("SELECT * FROM projects WHERE id=? AND owner=?",(pid,owner)).fetchone()
            if not p: return None
            count=c.execute("SELECT COUNT(*) FROM entries WHERE project_id=?",(pid,)).fetchone()[0]
        return {"project_id":p["id"],"title":p["title"],"formula":p["formula"],"entry_count":count}

    def add(self, owner, pid, doc):
        if not isinstance(doc,dict): raise ChemError("JSON object required")
        source_type = doc.get("source_type")
        if source_type not in STATUSES: raise ChemError("source_type must be simulation or measurement")
        method = short_text(doc.get("method"), 200)
        notes = doc.get("notes","")
        if not isinstance(notes,str) or len(notes)>2000: raise ChemError("notes too long")
        data = validate_data(doc.get("data"))
        source_hash=clean_hash(doc.get("source_sha256"), required=True)
        code_hash=clean_hash(doc.get("code_sha256"))
        payload={"source_type":source_type,"method":method,"notes":notes,
                 "data":data,"source_sha256":source_hash,"code_sha256":code_hash}
        payload_hash = SHA(CANON(payload))
        with self.lock, self.db() as c:
            c.execute("BEGIN IMMEDIATE")
            p=c.execute("SELECT id,formula FROM projects WHERE id=? AND owner=?",(pid,owner)).fetchone()
            if p is None: return None
            previous=c.execute("SELECT seq,chain_hash FROM entries WHERE project_id=? ORDER BY seq DESC LIMIT 1",(pid,)).fetchone()
            seq=previous["seq"]+1 if previous else 1
            previous_hash=previous["chain_hash"] if previous else "0"*64
            chain_hash=SHA(CANON({"project_id":pid,"sequence":seq,"previous_hash":previous_hash,"payload_hash":payload_hash}))
            eid="evt_" + secrets.token_hex(12)
            token_id="pdt_" + SHA(CANON({"owner":owner,"project_id":pid,"sequence":seq,"chain_hash":chain_hash}))[:40]
            created=NOW()
            c.execute("INSERT INTO entries VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (eid,pid,seq,source_type,CANON(payload),payload_hash,previous_hash,chain_hash,token_id,created))
        return {"entry_id":eid,"sequence":seq,"source_type":source_type,"payload_sha256":payload_hash,
                "chain_sha256":chain_hash,"previous_sha256":previous_hash,"token_id":token_id,
                "token_kind":"Privi Data Token receipt (off-chain, non-transferable)",
                "blockchain_anchor_status":"not_submitted","created":created}

    def report(self, owner, pid):
        p=self.project(owner,pid)
        if not p: return None
        with self.db() as c:
            rows=c.execute("SELECT * FROM entries WHERE project_id=? ORDER BY seq",(pid,)).fetchall()
        entries=[{"sequence":r["seq"],"source_type":r["source_type"],
                  "payload_sha256":r["payload_hash"],"previous_sha256":r["previous_hash"],
                  "chain_sha256":r["chain_hash"],"token_id":r["token_id"],
                  "created":r["created"],"payload":json.loads(r["payload"])} for r in rows]
        prev = "0"*64
        verified = True
        for e in entries:
            digest = SHA(CANON(e["payload"]))
            chain = SHA(CANON({"project_id":pid, "sequence":e["sequence"],
                               "previous_hash":prev, "payload_hash":digest}))
            if e["previous_sha256"] != prev or e["payload_sha256"] != digest or e["chain_sha256"] != chain:
                verified = False
            prev = e["chain_sha256"]
        root=entries[-1]["chain_sha256"] if entries else "0"*64
        body={"project":p,"entries":entries,"last_chain_sha256":root,
              "simulation_count":sum(x["source_type"]=="simulation" for x in entries),
              "measurement_count":sum(x["source_type"]=="measurement" for x in entries)}
        return {"report":body,"report_sha256":SHA(CANON(body)), "hash_chain_valid":verified,
                "blockchain_anchor_status":"not_submitted",
                "verification":"locally hash-chained; no on-chain transaction verified"}

    def token(self, owner, token_id):
        with self.db() as c:
            r=c.execute("""SELECT e.*,p.owner,p.formula,p.title FROM entries e
                           JOIN projects p ON e.project_id=p.id
                           WHERE e.token_id=? AND p.owner=?""",(token_id,owner)).fetchone()
        if not r: return None
        return {"token_id":r["token_id"],"kind":"non-transferable off-chain evidence receipt",
                "minted_on_chain":False,"chain":"none","owner_sha256":r["owner"],
                "project_id":r["project_id"],"formula":r["formula"],"project_title":r["title"],
                "payload_sha256":r["payload_hash"],"chain_sha256":r["chain_hash"],
                "source_sha256":json.loads(r["payload"])["source_sha256"],
                "code_sha256":json.loads(r["payload"])["code_sha256"],
                "formula_sha256":SHA(r["formula"]),
                "source_type":r["source_type"],"blockchain_anchor_status":"not_submitted"}

def bearer_owner(headers):
    raw = os.getenv("PRIVI_CHEM_API_KEYS","")
    keys=[k.strip() for k in raw.split(",") if k.strip()]
    if not keys: return None,503
    auth=headers.get("Authorization","")
    candidate=auth[7:] if auth.startswith("Bearer ") else ""
    if not candidate or not any(hmac.compare_digest(candidate,key) for key in keys):
        return None,401
    return SHA(candidate),200

def make_handler(store):
    class Handler(BaseHTTPRequestHandler):
        def send(self, code, obj):
            data=CANON(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type","application/json; charset=utf-8")
            self.send_header("Cache-Control","no-store")
            self.send_header("Content-Length",str(len(data)))
            self.end_headers();self.wfile.write(data)
        def do_GET(self):
            path=urlparse(self.path).path
            if path=="/health":
                return self.send(200,{"ok":True,"service":"privi-chem","blockchain_anchor":"not_configured","minting":"disabled"})
            owner,status=bearer_owner(self.headers)
            if not owner:return self.send(status,{"error":"unconfigured" if status==503 else "unauthorized"})
            pieces=path.strip("/").split("/")
            if len(pieces)==3 and pieces[:2]==["v1","projects"]:
                p=store.project(owner,pieces[2]);return self.send(200 if p else 404,p or {"error":"not found"})
            if len(pieces)==4 and pieces[:2]==["v1","projects"] and pieces[3]=="report":
                p=store.report(owner,pieces[2]);return self.send(200 if p else 404,p or {"error":"not found"})
            if len(pieces)==3 and pieces[:2]==["v1","tokens"]:
                p=store.token(owner,pieces[2]);return self.send(200 if p else 404,p or {"error":"not found"})
            self.send(404,{"error":"not found"})
        def do_POST(self):
            owner,status=bearer_owner(self.headers)
            if not owner:return self.send(status,{"error":"unconfigured" if status==503 else "unauthorized"})
            try:
                size=int(self.headers.get("Content-Length","-1"))
                if size<0 or size>MAX_BYTES:return self.send(413,{"error":"payload too large or missing content-length"})
                doc=json.loads(self.rfile.read(size))
                parts=urlparse(self.path).path.strip("/").split("/")
                if parts==["v1","projects"]:return self.send(201,store.create(owner,doc))
                if len(parts)==4 and parts[:2]==["v1","projects"] and parts[3]=="entries":
                    result=store.add(owner,parts[2],doc)
                    return self.send(201 if result else 404,result or {"error":"not found"})
                return self.send(404,{"error":"not found"})
            except (ChemError,ValueError,TypeError,json.JSONDecodeError) as e:
                return self.send(400,{"error":str(e)[:180]})
        def log_message(self, fmt, *args):
            pass   # no customer data or bearer tokens in logs
    return Handler

def main():
    port=int(os.getenv("PORT","10000"))
    path=os.getenv("PRIVI_CHEM_DB_PATH","/data/privi-chem.sqlite3")
    store=ChemStore(path)
    ThreadingHTTPServer(("0.0.0.0",port),make_handler(store)).serve_forever()

if __name__=="__main__":
    main()
