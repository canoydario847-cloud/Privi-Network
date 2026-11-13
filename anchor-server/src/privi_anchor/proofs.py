"""Privi Anchor proofs people can hand to someone else.

- Folder Manifest   anchor a whole folder or dataset (up to 2,000 files) with one transaction, then prove any
                    single file was part of it without revealing the others
- Certificate       a readable proof-of-existence certificate for an anchored hash, with a public page

File paths and certificate text are kept in this server's index, never on chain. Only hashes go on chain.
"""
from __future__ import annotations

import hashlib
import html
import json
import secrets
import time
from typing import Annotated, Any, Callable

from mcp.server.mcpserver import Context
from mcp_types import CallToolResult, TextContent, ToolAnnotations
from pydantic import Field
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse

from . import merkle
from .store import AnchorStore

SCHEMA = """
CREATE TABLE IF NOT EXISTS manifests (
    manifest_root TEXT PRIMARY KEY, name TEXT NOT NULL, file_count INTEGER NOT NULL, client TEXT NOT NULL,
    created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS manifest_files (
    manifest_root TEXT NOT NULL, path TEXT NOT NULL, sha256 TEXT NOT NULL, leaf TEXT NOT NULL, proof TEXT NOT NULL,
    PRIMARY KEY (manifest_root, path));
CREATE TABLE IF NOT EXISTS certificates (
    certificate_id TEXT PRIMARY KEY, body TEXT NOT NULL, body_sha256 TEXT NOT NULL, created_at INTEGER NOT NULL);
"""
MAX_FILES = 2000
READ = ToolAnnotations(readOnlyHint=True, openWorldHint=True)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)


def file_leaf(path: str, sha256: str) -> str:
    """Leaf for one file: SHA-256 of 'path' + newline + the file's SHA-256, so a file cannot be renamed unnoticed."""
    return hashlib.sha256(f"{path}\n{sha256}".encode("utf-8")).hexdigest()


def clean_files(files: Any) -> list[tuple[str, str]]:
    if not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES:
        raise ValueError(f"files must list 1-{MAX_FILES} files")
    out, seen = [], set()
    for f in files:
        if not isinstance(f, dict):
            raise ValueError('each file must be like {"path": "reports/q3.pdf", "sha256": "<64 hex>"}')
        path = str(f.get("path", "")).strip().replace("\\", "/")
        if not path or len(path) > 400 or "\n" in path:
            raise ValueError("each path must be 1-400 characters on one line")
        if path in seen:
            raise ValueError(f"path '{path}' is listed twice")
        seen.add(path)
        out.append((path, merkle.norm_hash(str(f.get("sha256", "")))))
    return out


def _result(data: dict[str, Any], is_error: bool = False) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(data))], structured_content=data, is_error=is_error)


def certificate_html(c: dict) -> str:
    e = html.escape
    rows = "".join(f"<tr><th>{e(k)}</th><td>{v}</td></tr>" for k, v in (
        ("Owner", e(c["owner"])), ("Fingerprint (SHA-256)", f"<code>{e(c['hash'])}</code>"),
        ("Existed no later than", e(c["block_time_utc"] or "")), ("Network", e(c["network"])),
        ("Block", e(str(c["block_number"]))),
        ("Transaction", f"<a href='{e(c['tx_link'])}'>{e(c['tx_hash'])}</a>" if c.get("tx_link") else f"<code>{e(c['tx_hash'])}</code>"),
        ("Certificate", e(c["certificate_id"]))))
    return (f"<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>{e(c['title'])} - proof of existence</title><style>body{{font:16px/1.5 system-ui,sans-serif;max-width:720px;"
            f"margin:40px auto;padding:0 16px;color:#111}}table{{border-collapse:collapse;width:100%}}th,td{{text-align:left;"
            f"padding:8px 6px;border-top:1px solid #ddd;vertical-align:top}}th{{width:34%;color:#555;font-weight:500}}"
            f"code,a{{word-break:break-all;font-size:13px}}footer{{margin-top:28px;color:#666;font-size:13px}}</style>"
            f"<p>Privi Anchor &middot; proof of existence</p><h1>{e(c['title'])}</h1><p>{e(c['description'])}</p><table>{rows}</table>"
            f"<footer>This shows that a file with this fingerprint existed when the block was mined. It does not show who "
            f"wrote the file or what it says. To check: hash your copy with SHA-256 and compare, then look up the "
            f"transaction on the block explorer.</footer></html>")


def register(mcp, store: AnchorStore, *, anchor: Callable, verify_hash: Callable, client_key: Callable,
             tx_link: Callable, network_name: str, public_url: str) -> None:
    with store._lock:
        store._db.executescript(SCHEMA)
        store._db.commit()
    db, lock = store._db, store._lock

    @mcp.tool(title="Anchor a folder manifest", annotations=WRITE)
    async def anchor_manifest(
        files: Annotated[list[dict[str, str]], Field(description=f'1-{MAX_FILES} files, each {{"path": "reports/q3.pdf", "sha256": "<64 hex>"}}')],
        ctx: Context,
        name: Annotated[str, Field(description="Name for this set, e.g. 'Audit evidence 2026-Q3' (kept in the index, not on chain)")] = "",
    ) -> CallToolResult:
        """Anchor a whole folder, dataset or evidence bundle with one on-chain transaction. Later, prove that any
        one file (by path and fingerprint) was part of it with anchor_manifest_check, without showing the other
        files. Requires an API key (Authorization: Bearer)."""
        try:
            pairs = clean_files(files)
            leaves = {file_leaf(p, s): (p, s) for p, s in pairs}
            root, proofs = merkle.build(list(leaves))
        except ValueError as e:
            return _result({"error": str(e)}, is_error=True)
        r = await anchor(hashes=[root], ctx=ctx, label=f"manifest: {name}"[:200])
        data = r.structured_content or {}
        if r.is_error:
            return _result(data, is_error=True)
        with lock:
            db.execute("INSERT OR REPLACE INTO manifests VALUES (?,?,?,?,?)",
                       (root, name.strip()[:200], len(pairs), client_key(ctx) or "", int(time.time())))
            db.executemany("INSERT OR REPLACE INTO manifest_files VALUES (?,?,?,?,?)",
                           [(root, p, s, leaf, json.dumps(proofs[leaf])) for leaf, (p, s) in leaves.items()])
            db.commit()
        return _result({"manifest_root": root, "files": len(pairs), "name": name.strip()[:200], "status": data.get("status"),
                        "tx_hash": data.get("tx_hash"), "tx_link": data.get("tx_link"), "block_number": data.get("block_number"),
                        "block_time": data.get("block_time"), "network": data.get("network"),
                        "leaf_rule": "sha256(path + '\\n' + file_sha256); tree: sha256(min(a,b)||max(a,b))",
                        "next": "Keep manifest_root. Anyone checks a file with anchor_manifest_check(manifest_root, path, sha256)."})

    @mcp.tool(title="Check a file against a manifest", annotations=READ)
    async def anchor_manifest_check(
        manifest_root: Annotated[str, Field(description="The manifest_root returned by anchor_manifest")],
        path: Annotated[str, Field(description="The file's path exactly as listed")],
        sha256: Annotated[str, Field(description="SHA-256 of the file you hold")],
        proof: Annotated[list[str] | None, Field(description="Optional Merkle proof, to check without this server's index")] = None,
    ) -> CallToolResult:
        """Check that a file (path and fingerprint) was part of an anchored manifest, and that the manifest is on
        chain. A changed file, or a renamed one, fails."""
        try:
            root, sha = merkle.norm_hash(manifest_root), merkle.norm_hash(sha256)
        except ValueError as e:
            return _result({"error": str(e)}, is_error=True)
        path = str(path or "").strip().replace("\\", "/")
        leaf = file_leaf(path, sha)
        m = db.execute("SELECT name, file_count FROM manifests WHERE manifest_root=?", (root,)).fetchone()
        if proof is None:
            row = db.execute("SELECT sha256, proof FROM manifest_files WHERE manifest_root=? AND path=?", (root, path)).fetchone()
            if not row:
                return _result({"in_manifest": False, "manifest_root": root, "path": path,
                                "reason": "no file with this path in that manifest" if m else "no such manifest on this server"})
            if row["sha256"] != sha:
                return _result({"in_manifest": False, "manifest_root": root, "path": path,
                                "reason": "the file's fingerprint differs from the one anchored; the file was changed"})
            proof = json.loads(row["proof"])
        try:
            ok = merkle.root_from_proof(leaf, proof) == root
        except ValueError as e:
            return _result({"error": f"bad proof: {e}"}, is_error=True)
        if not ok:
            return _result({"in_manifest": False, "manifest_root": root, "path": path,
                            "reason": "this path and fingerprint are not part of that manifest"})
        chain_check, err = await verify_hash(root)
        return _result({"in_manifest": True, "manifest_root": root, "path": path, "sha256": sha, "proof": proof,
                        "manifest": {"name": m["name"], "files": m["file_count"]} if m else None,
                        "anchored": bool(chain_check.get("verified")), "onchain": chain_check}, is_error=False)

    @mcp.tool(title="Proof-of-existence certificate", annotations=WRITE)
    async def anchor_certificate(
        hash: Annotated[str, Field(description="An anchored 64-character hex SHA-256")],
        title: Annotated[str, Field(description="What the file is, e.g. 'Bracket A-12 drawing rev C'")],
        owner: Annotated[str, Field(description="Person or company the certificate is made out to")],
        description: Annotated[str, Field(description="Optional sentence shown on the certificate")] = "",
    ) -> CallToolResult:
        """Turn an anchored hash into a readable certificate with a public page: title, owner, fingerprint, block
        and time. Useful as dated evidence for designs, drafts, contracts and research notes. The hash must already
        be anchored and confirmed (anchor_hashes)."""
        title, owner = str(title or "").strip(), str(owner or "").strip()
        if not 3 <= len(title) <= 160 or not 2 <= len(owner) <= 160:
            return _result({"error": "title must be 3-160 characters and owner 2-160"}, is_error=True)
        v, err = await verify_hash(hash)
        if err:
            return _result(v, is_error=True)
        if not v.get("verified"):
            return _result({"error": "this hash is not confirmed on chain yet; anchor it with anchor_hashes first",
                            "check": v}, is_error=True)
        cid = "cert_" + secrets.token_hex(8)
        body = {"certificate_id": cid, "title": title, "owner": owner, "description": str(description or "").strip()[:500],
                "hash": v["hash"], "tx_hash": v["tx_hash"], "tx_link": tx_link(v["tx_hash"]), "proof": v["proof"],
                "merkle_root": v["merkle_root"], "chain_id": v["chain_id"], "network": network_name,
                "block_number": v["block_number"], "block_time": v["block_time"], "block_time_utc": v["block_time_utc"],
                "issuer": "Privi Anchor (Privi World Co)",
                "meaning": "A file with this SHA-256 fingerprint existed no later than the block time."}
        text = json.dumps(body, sort_keys=True, separators=(",", ":"))
        with lock:
            db.execute("INSERT INTO certificates VALUES (?,?,?,?)",
                       (cid, text, hashlib.sha256(text.encode()).hexdigest(), int(time.time())))
            db.commit()
        return _result({**body, "certificate_url": f"{public_url}/certificates/{cid}"})

    def cert(cid: str) -> dict | None:
        r = db.execute("SELECT body FROM certificates WHERE certificate_id=?", (cid,)).fetchone()
        return json.loads(r["body"]) if r else None

    @mcp.tool(title="Read a certificate", annotations=READ)
    def anchor_certificate_get(certificate_id: Annotated[str, Field(description="cert_... id")]) -> CallToolResult:
        """Read a proof-of-existence certificate by its ID, with the receipt needed to re-check it on chain."""
        c = cert(str(certificate_id or "").strip())
        return _result({**c, "certificate_url": f"{public_url}/certificates/{c['certificate_id']}"}) if c else \
            _result({"error": "no such certificate"}, is_error=True)

    @mcp.custom_route("/certificates/{cid}", methods=["GET"], include_in_schema=False)
    async def cert_page(request: Request):
        c = cert(request.path_params["cid"][:40])
        if not c:
            return JSONResponse({"error": "not found"}, status_code=404)
        if request.query_params.get("format") == "json":
            return JSONResponse(c, headers={"Access-Control-Allow-Origin": "*"})
        return HTMLResponse(certificate_html(c))
