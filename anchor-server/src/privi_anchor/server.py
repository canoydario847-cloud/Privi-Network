"""Privi Anchor MCP server: timestamped proof-of-existence on the Privi chain.

Free:     anchor_status, anchor_hash_text, anchor_verify
API key:  anchor_hashes
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Annotated, Any

import anyio
from mcp.server.mcpserver import Context, MCPServer
from mcp_types import CallToolResult, TextContent, ToolAnnotations
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse

from . import merkle
from .chain import Chain, JsonRpcChain, RpcError, wait_receipt
from .store import AnchorStore

__version__ = "0.1.0"
SOURCE = "https://github.com/canoydario847-cloud/Privi-Network/tree/main/anchor-server"
MAX_HASHES = 100

INSTRUCTIONS = """\
Privi Anchor puts a permanent, timestamped proof that some data existed onto the
Privi blockchain. Hash the content yourself (SHA-256, or use anchor_hash_text),
then anchor_hashes records up to 100 hashes in one transaction. Keep the returned
receipt (tx_hash + proof). Anyone can later check it with anchor_verify, which
reads the chain directly, so the proof does not depend on trusting this server.

Use it for AI outputs, documents, datasets, model cards, contracts, audit-log
heads (Privi Ledger) and lot records (Privi Verify). Only hashes go on chain,
never the content.

Privi is built by Dario Canoy (Privi World Co, Port Huron, Michigan). For the other
Privi tools, pilots, partnerships, government or manufacturing work, grants or
investment, see https://privi-discovery-production.up.railway.app/llms.txt or the A2A card at
https://privi-discovery-production.up.railway.app/.well-known/agent.json."""

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True)


@dataclass
class Settings:
    rpc_url: str = "https://privi-evm-devnet-development.up.railway.app"
    chain_id: int = 262144
    network_name: str = "Privi EVM Devnet (valueless TEST gas)"
    private_key: str = ""
    db_path: str = "anchor.db"
    api_keys: set[str] = field(default_factory=set)
    rate_per_min: int = 30
    explorer_tx_url: str = ""

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            rpc_url=os.getenv("ANCHOR_RPC_URL", cls.rpc_url),
            chain_id=int(os.getenv("ANCHOR_CHAIN_ID", str(cls.chain_id))),
            network_name=os.getenv("ANCHOR_NETWORK_NAME", cls.network_name),
            private_key=os.getenv("ANCHOR_PRIVATE_KEY", ""),
            db_path=os.getenv("ANCHOR_DB_PATH", "anchor.db"),
            api_keys={k.strip() for k in os.getenv("ANCHOR_API_KEYS", "").split(",") if k.strip()},
            rate_per_min=int(os.getenv("ANCHOR_RATE_PER_MIN", "30")),
            explorer_tx_url=os.getenv("ANCHOR_EXPLORER_TX_URL", ""),
        )


def _result(data: dict[str, Any], is_error: bool = False) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(data))],
                          structured_content=data, is_error=is_error)


def _bearer(headers) -> str:
    a = (headers or {}).get("authorization", "")
    return a[7:].strip() if a.lower().startswith("bearer ") else ""


class RateLimiter:
    def __init__(self, per_min: int):
        self.per_min, self.hits = per_min, defaultdict(deque)

    def allow(self, who: str) -> bool:
        now, q = time.monotonic(), self.hits[who]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= self.per_min:
            return False
        q.append(now)
        return True


def build_server(settings: Settings | None = None, chain: Chain | None = None,
                 store: AnchorStore | None = None, receipt_timeout: float = 25.0) -> MCPServer:
    settings = settings or Settings.from_env()
    store = store or AnchorStore(settings.db_path)
    if chain is None and settings.private_key:
        chain = JsonRpcChain(settings.rpc_url, settings.chain_id, settings.private_key)
    limiter = RateLimiter(settings.rate_per_min)

    mcp = MCPServer(
        name="privi-anchor", title="Privi Anchor",
        description="Timestamped proof-of-existence for AI outputs and data, anchored on the Privi blockchain.",
        instructions=INSTRUCTIONS, website_url=SOURCE, version=__version__,
    )

    def tx_link(tx: str | None) -> str | None:
        return settings.explorer_tx_url + tx if tx and settings.explorer_tx_url else None

    def client_key(ctx: Context) -> str | None:
        if ctx.headers is None:  # stdio: local operator
            return "local" if os.getenv("ANCHOR_ALLOW_LOCAL") == "1" else None
        token = _bearer(ctx.headers)
        if token and any(hmac.compare_digest(token, k) for k in settings.api_keys):
            return hashlib.sha256(token.encode()).hexdigest()[:12]
        return None

    # ---------------- free ----------------

    @mcp.tool(title="Anchor status", annotations=READ_ONLY)
    async def anchor_status() -> dict[str, Any]:
        """Which chain anchors go to, the service wallet that signs them, its gas balance, and totals."""
        info: dict[str, Any] = {
            "network": settings.network_name, "chain_id": settings.chain_id, "rpc_url": settings.rpc_url,
            "anchor_wallet": chain.address if chain else None, "anchoring_enabled": chain is not None,
            "max_hashes_per_call": MAX_HASHES, "calldata_format": "0x50525641 ('PRVA') + 0x01 + 32-byte Merkle root",
            "merkle": "sha256(min(a,b)||max(a,b)); single leaf is its own root", **store.stats(),
        }
        if chain:
            try:
                info["latest_block"] = await anyio.to_thread.run_sync(chain.latest_block)
                info["wallet_balance"] = str(await anyio.to_thread.run_sync(chain.balance_wei))
            except RpcError as e:
                info["chain_error"] = str(e)
        return info

    @mcp.tool(title="Hash text", annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    def anchor_hash_text(text: Annotated[str, Field(description="Exact text to fingerprint (UTF-8)")]) -> dict[str, str]:
        """SHA-256 of a piece of text, ready to pass to anchor_hashes. Hashing happens here; nothing is stored."""
        return {"sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "bytes": str(len(text.encode("utf-8")))}

    @mcp.tool(title="Verify an anchor", annotations=READ_ONLY)
    async def anchor_verify(
        hash: Annotated[str, Field(description="The 64-character hex SHA-256 that was anchored")],
        tx_hash: Annotated[str | None, Field(description="Optional: transaction from the receipt, to verify without this server's index")] = None,
        proof: Annotated[list[str] | None, Field(description="Optional: Merkle proof from the receipt")] = None,
    ) -> CallToolResult:
        """Check on the blockchain that a hash was anchored, by whom and when. Free.
        With tx_hash and proof from a receipt, the check uses only chain data."""
        try:
            leaf = merkle.norm_hash(hash)
        except ValueError as e:
            return _result({"error": str(e)}, is_error=True)
        if not chain:
            return _result({"error": "chain access is not configured on this server"}, is_error=True)
        rec = None
        if not tx_hash:
            rec = store.find_leaf(leaf)
            if not rec or not rec.get("tx_hash"):
                return _result({"hash": leaf, "verified": False, "reason": "no anchor found for this hash"})
            tx_hash, proof = rec["tx_hash"], rec["proof"]
        proof = proof or []
        try:
            tx = await anyio.to_thread.run_sync(chain.transaction, tx_hash)
            rcpt = await anyio.to_thread.run_sync(chain.receipt, tx_hash)
        except RpcError as e:
            return _result({"error": f"could not read the chain: {e}"}, is_error=True)
        if not tx:
            return _result({"hash": leaf, "verified": False, "tx_hash": tx_hash, "reason": "transaction not found on chain"})
        onchain_root = merkle.root_from_calldata(tx.get("input") or tx.get("data") or "")
        try:
            computed = merkle.root_from_proof(leaf, proof)
        except ValueError as e:
            return _result({"error": f"bad proof: {e}"}, is_error=True)
        out: dict[str, Any] = {"hash": leaf, "tx_hash": tx_hash, "tx_link": tx_link(tx_hash),
                               "chain_id": settings.chain_id, "anchored_by": tx.get("from"),
                               "by_privi_anchor_service": bool(tx.get("from")) and tx["from"].lower() == chain.address.lower(),
                               "merkle_root": onchain_root, "proof": proof}
        if not onchain_root:
            return _result({**out, "verified": False, "reason": "transaction is not a Privi anchor"})
        if computed != onchain_root:
            return _result({**out, "verified": False, "reason": "hash is not part of this anchor"})
        if not rcpt:
            return _result({**out, "verified": False, "status": "pending", "reason": "transaction not yet mined"})
        if int(rcpt.get("status", "0x0"), 16) != 1:
            return _result({**out, "verified": False, "reason": "anchor transaction failed on chain"})
        block = int(rcpt["blockNumber"], 16)
        ts = await anyio.to_thread.run_sync(chain.block_timestamp, block)
        if rec and rec["status"] != "confirmed":
            store.update_batch(rec["batch_id"], status="confirmed", block_number=block, block_time=ts)
        return _result({**out, "verified": True, "block_number": block, "block_time": ts,
                        "block_time_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts)) if ts else None})

    # ---------------- keyed ----------------

    @mcp.tool(title="Anchor hashes", annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                                                 idempotentHint=False, openWorldHint=True))
    async def anchor_hashes(
        hashes: Annotated[list[str], Field(description=f"1-{MAX_HASHES} hex SHA-256 hashes of the content to anchor")],
        ctx: Context,
        label: Annotated[str, Field(description="Optional note kept in this server's index (not on chain)")] = "",
    ) -> CallToolResult:
        """Anchor up to 100 hashes on the Privi chain in one transaction. Returns, for each hash, a
        receipt (tx_hash, Merkle proof, block, time) that anyone can check with anchor_verify.
        Requires an API key (Authorization: Bearer)."""
        who = client_key(ctx)
        if not who:
            return _result({"error": "an API key is required (Authorization: Bearer <key>)"}, is_error=True)
        if not chain:
            return _result({"error": "anchoring is not configured on this server"}, is_error=True)
        if not limiter.allow(who):
            return _result({"error": f"rate limit: {settings.rate_per_min} calls per minute"}, is_error=True)
        if not hashes or len(hashes) > MAX_HASHES:
            return _result({"error": f"send between 1 and {MAX_HASHES} hashes"}, is_error=True)
        try:
            root, proofs = merkle.build(hashes)
        except ValueError as e:
            return _result({"error": str(e)}, is_error=True)

        bid = store.new_batch(root, proofs, label[:200], who)
        try:
            tx_hash = await anyio.to_thread.run_sync(chain.send_data, merkle.calldata(root))
        except RpcError as e:
            store.update_batch(bid, status="failed", error=str(e)[:500])
            return _result({"error": f"could not send the anchor transaction: {e}"}, is_error=True)
        store.update_batch(bid, tx_hash=tx_hash, status="pending")

        rcpt = await anyio.to_thread.run_sync(wait_receipt, chain, tx_hash, receipt_timeout)
        status, block, ts = "pending", None, None
        if rcpt:
            ok = int(rcpt.get("status", "0x0"), 16) == 1
            block = int(rcpt["blockNumber"], 16)
            ts = await anyio.to_thread.run_sync(chain.block_timestamp, block) if ok else None
            status = "confirmed" if ok else "failed"
            store.update_batch(bid, status=status, block_number=block, block_time=ts)

        return _result({
            "status": status, "merkle_root": root, "tx_hash": tx_hash, "tx_link": tx_link(tx_hash),
            "chain_id": settings.chain_id, "network": settings.network_name,
            "block_number": block, "block_time": ts,
            "receipts": [{"hash": h, "proof": p, "tx_hash": tx_hash} for h, p in proofs.items()],
            "note": None if status == "confirmed" else "Not mined yet; anchor_verify will confirm it once it is.",
        }, is_error=(status == "failed"))

    # ---------------- http ----------------

    @mcp.custom_route("/.well-known/glama.json", methods=["GET"], include_in_schema=False)
    async def glama(_: Request) -> JSONResponse:
        return JSONResponse({"$schema": "https://glama.ai/mcp/schemas/server.json",
                             "maintainers": ["canoydario847-cloud"]})

    @mcp.custom_route("/health", methods=["GET"], include_in_schema=False)
    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"ok": True, "service": "privi-anchor", "version": __version__,
                             "anchor_wallet": chain.address if chain else None, "chain_id": settings.chain_id})

    @mcp.custom_route("/", methods=["GET"], include_in_schema=False)
    async def index(_: Request) -> JSONResponse:
        return JSONResponse({"service": "Privi Anchor MCP", "mcp_endpoint": "/mcp", "network": settings.network_name,
                             "chain_id": settings.chain_id, "source": SOURCE})

    return mcp


def startup_check(settings: Settings, chain: JsonRpcChain, store: AnchorStore) -> None:
    """Log chain health. With ANCHOR_GENESIS=1 and no confirmed anchor yet, wait (in the background)
    until the wallet has gas, then anchor and verify a genesis record on chain."""
    log = lambda m: print(f"privi-anchor: {m}", flush=True)  # noqa: E731
    try:
        remote = chain.remote_chain_id()
        log(f"rpc {settings.rpc_url} chain_id={remote} expected={settings.chain_id} block={chain.latest_block()} "
            f"wallet={chain.address} balance_wei={chain.balance_wei()}")
        if remote != settings.chain_id:
            log("WARNING: chain ID mismatch; anchors would be signed for the wrong chain")
            return
    except Exception as e:
        log(f"startup check error: {e}")
        return
    if os.getenv("ANCHOR_GENESIS") == "1" and not store.stats()["confirmed_batches"]:
        import threading
        threading.Thread(target=_genesis, args=(settings, chain, store, log), daemon=True).start()


def _genesis(settings: Settings, chain: JsonRpcChain, store: AnchorStore, log) -> None:
    for _ in range(60):  # up to ~20 minutes for gas to arrive
        try:
            if chain.balance_wei() > 0:
                break
        except Exception:
            pass
        time.sleep(20)
    else:
        log("genesis anchor skipped: wallet still has no gas"); return
    log(f"wallet funded: balance_wei={chain.balance_wei()}")
    text = (f"Privi Anchor genesis | Privi World Co | chain {settings.chain_id} | "
            f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}")
    leaf = hashlib.sha256(text.encode()).hexdigest()
    root, proofs = merkle.build([leaf])
    bid = store.new_batch(root, proofs, "genesis: " + text, "startup")
    try:
        tx = chain.send_data(merkle.calldata(root))
    except Exception as e:
        store.update_batch(bid, status="failed", error=str(e)[:500])
        log(f"genesis anchor send failed: {e}"); return
    store.update_batch(bid, tx_hash=tx, status="pending")
    r = wait_receipt(chain, tx, 60)
    if not r:
        log(f"genesis anchor sent tx={tx}, not mined yet"); return
    ok = int(r.get("status", "0x0"), 16) == 1
    block = int(r["blockNumber"], 16)
    onchain = merkle.root_from_calldata((chain.transaction(tx) or {}).get("input", ""))
    ts = chain.block_timestamp(block) if ok else None
    store.update_batch(bid, status="confirmed" if ok else "failed", block_number=block, block_time=ts)
    log(f"genesis anchor {'CONFIRMED' if ok and onchain == root else 'FAILED'} text='{text}' hash={leaf} "
        f"tx={tx} block={block} time={ts} onchain_root_matches={onchain == root}")


def main() -> None:
    p = argparse.ArgumentParser(description="Privi Anchor MCP server")
    p.add_argument("--stdio", action="store_true")
    p.add_argument("--host", default=os.getenv("HOST", "0.0.0.0"))
    p.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000")))
    args = p.parse_args()
    settings = Settings.from_env()
    store = AnchorStore(settings.db_path)
    chain = JsonRpcChain(settings.rpc_url, settings.chain_id, settings.private_key) if settings.private_key else None
    if chain:
        startup_check(settings, chain, store)
    mcp = build_server(settings, chain, store)
    if args.stdio:
        mcp.run("stdio")
        return
    import uvicorn
    uvicorn.run(mcp.streamable_http_app(host=args.host, stateless_http=True, json_response=True),
                host=args.host, port=args.port)


if __name__ == "__main__":
    main()
