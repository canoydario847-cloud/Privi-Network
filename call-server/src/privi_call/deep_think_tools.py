# Copyright (c) 2026 Privi World Corp. All rights reserved.
"""MCP registration for Deep Think. First pass free; changed snapshots require x402."""
from __future__ import annotations

import asyncio
import os
import json
import sqlite3
from typing import Any

from mcp.server.mcpserver import Context
from mcp_types import CallToolResult, TextContent, ToolAnnotations

from .deep_think import DeepThinkError, DeepThinkLedger, PRICE_USDC


def register(mcp: Any, settings: Any, paywall: Any) -> None:
    ledger = DeepThinkLedger(settings.db_path)
    settings.per_call_prices["deep_think_redo"] = PRICE_USDC
    # Protect against two simultaneous payments for the same task in a single worker.
    # Do not scale this handler to multiple workers until cross-worker locks exist.
    payment_gate = asyncio.Lock()
    write = ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                            idempotentHint=False, openWorldHint=False)

    def failure(message: str) -> CallToolResult:
        data = {"error": message, "charged": False}
        return CallToolResult(is_error=True, structured_content=data,
                              content=[TextContent(type="text", text=json.dumps(data))])

    @mcp.tool(title="Deep Think: plan before coding (free)", annotations=write)
    def deep_think_plan(goal: str, language: str, acceptance_criteria: list[str]) -> dict[str, Any]:
        """Plan requirements, testing, risks and edge cases before agent writes code."""
        try:
            return ledger.start(goal, language, acceptance_criteria)
        except DeepThinkError as exc:
            return {"error": str(exc)}

    @mcp.tool(title="Deep Think: verify first attempt (free)", annotations=write)
    def deep_think_review(task_id: str, task_token: str, source_sha256: str,
                          checks: dict[str, bool]) -> dict[str, Any]:
        """Log a source hash and five self-reported checks; first submission is free."""
        try:
            return ledger.review(task_id, task_token, source_sha256, checks)
        except DeepThinkError as exc:
            return {"error": str(exc)}

    @mcp.tool(title="Deep Think: approved code redo ($0.01 Base USDC)", annotations=write)
    async def deep_think_redo(task_id: str, task_token: str, prior_sha256: str,
                              new_sha256: str, approve_usdc_charge: bool, ctx: Context) -> CallToolResult:
        """Charge $0.01 only for a genuine, explicitly approved changed code snapshot.

        A signed x402 wallet payload in MCP _meta['x402/payment'] is still required.
        No permission to spend customer funds is inferred from the agent's claims.
        """
        if approve_usdc_charge is not True:
            return failure("operator approval required for a $0.01 USDC redo")
        # Production billing is explicitly opt-in until plan entitlements and settlement are verified.
        if os.getenv("DEEP_THINK_PAID_REDOS_ENABLED", "0") != "1":
            return failure("paid redos are disabled pending production billing verification")
        if not (settings.payments_ready and settings.network_key == "base"):
            return failure("production Base USDC settlement is unavailable; no payment attempted")
        async with payment_gate:
            try:
                q = ledger.inspect_redo(task_id, task_token, prior_sha256, new_sha256)
            except DeepThinkError as exc:
                return failure(str(exc))
            if q["status"] == "already_recorded":
                return CallToolResult(structured_content=q,
                                      content=[TextContent(type="text", text=json.dumps(q))])

            async def work() -> dict[str, Any]:
                # No state changes until successful facilitator settlement.
                return {"task_id": task_id, "redo_validated": True,
                        "previous_code_sha256": prior_sha256, "new_code_sha256": new_sha256}

            try:
                meta = dict(ctx.request_context.meta or {})
            except Exception:
                meta = {}
            if meta.get("privi/payment"):
                return failure("Deep Think redo fees accept USDC on Base only")
            res = await paywall.run("deep_think_redo", "Operator-approved code redo", meta, work)
            if res.is_error:
                return res  # PaymentRequired or failure: no revision recorded.
            settled = dict(getattr(res, "meta", None) or {}).get("x402/payment-response") or {}
            tx = settled.get("transaction") or settled.get("txHash") or ""
            if not tx:
                return failure("Payment may have settled without a transaction reference; contact support before retrying")
            try:
                receipt = ledger.record_paid_redo(task_id, task_token, prior_sha256, new_sha256, str(tx))
            except (DeepThinkError, sqlite3.Error):
                return failure("Payment may have settled, but receipt saving failed; contact support before retrying")
            return CallToolResult(structured_content=receipt,
                                  content=[TextContent(type="text", text=json.dumps(receipt))],
                                  meta=getattr(res, "meta", None))
