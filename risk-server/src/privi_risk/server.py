# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Risk - https://priviflow.us - dariocanoy@priviflow.us
"""Privi Risk MCP server: the pre-trade risk desk for crypto and market traders and AI trading agents.

Free:  risk_position_size, risk_of_ruin, risk_market_check, risk_verify, risk_status
Paid:  risk_pretrade_report ($0.10 USDC on Base via x402): GO / REDUCE / NO-TRADE verdict,
       signed Ed25519 + ML-DSA-87 and anchored on the Privi chain.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import threading
import time
from collections import defaultdict, deque
from typing import Annotated, Any, Literal

import anyio
from mcp.server.mcpserver import Context, MCPServer
from mcp_types import CallToolResult, TextContent, ToolAnnotations
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from . import market, risk
from .anchoring import AnchorError, HttpAnchorClient, anchor_pending
from .attest import PQ_ALG, Attestor
from .config import Settings
from .x402 import Facilitator, Paywall

__version__ = "0.1.0"
SOURCE = "https://github.com/canoydario847-cloud/Privi-Network/tree/main/risk-server"
COPYRIGHT = "Copyright (c) 2026 Privi World Co. All rights reserved."
DISCLAIMER = "Risk analytics for education and planning, not financial advice. Markets can gap through stops."
PAID = "risk_pretrade_report"

INSTRUCTIONS = f"""\
Privi Risk is the pre-trade risk desk for crypto and market traders and AI trading agents.
Call it BEFORE placing a trade. Most accounts are not blown up by bad calls but by size,
leverage, and liquidation prices that sit inside the stop.

Free:
- risk_position_size: exact units for a fixed account risk, fees included; for leveraged
  perps/futures, the liquidation price and a hard warning if it sits before the stop.
- risk_of_ruin: Monte Carlo of a trading plan (win rate, payoff, risk per trade): chance of a
  deep drawdown or ruin, Kelly fraction, and the max safe risk per trade.
- risk_market_check: live volatility, ATR, max drawdown, VaR and Expected Shortfall for any
  Coinbase-listed crypto pair (e.g. BTC-USD), or for any market from closing prices you pass.
Paid ($0.10 USDC on Base, x402):
- risk_pretrade_report: all checks for one planned trade and a GO / REDUCE / NO-TRADE verdict
  with every reason, signed Ed25519 + {PQ_ALG.split(' (')[0]} and anchored on the Privi blockchain: proof the
  trade was risk-checked (for prop-firm rules, fund compliance, AI-agent spending mandates).
  risk_verify checks any report, free.

{DISCLAIMER} Privi is built by Dario Canoy (Privi World Co, Port Huron, Michigan); other Privi
tools: https://privi-discovery.onrender.com/llms.txt. {COPYRIGHT}"""

FREE = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
FREE_NET = ToolAnnotations(readOnlyHint=True, openWorldHint=True)

REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "account": {"type": "number", "description": "Account equity in USD"},
        "entry": {"type": "number"}, "stop": {"type": "number"},
        "side": {"type": "string", "enum": ["long", "short"]},
        "risk_pct": {"type": "number", "description": "Percent of the account you would lose at the stop"},
        "leverage": {"type": "number"}, "take_profit": {"type": "number"},
        "symbol": {"type": "string", "description": "Coinbase pair for live market risk, e.g. BTC-USD"},
        "win_rate": {"type": "number"}, "avg_win_r": {"type": "number"},
    },
    "required": ["account", "entry", "stop", "side"],
}
REPORT_EXAMPLE = {"account": 10000, "entry": 60000, "stop": 58200, "side": "long", "risk_pct": 1,
                  "leverage": 5, "take_profit": 65400, "symbol": "BTC-USD", "win_rate": 0.45, "avg_win_r": 2}


def _result(data: dict[str, Any], is_error: bool = False) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(data))],
                          structured_content=data, is_error=is_error)


def _meta(ctx: Context) -> dict:
    try:
        return dict(ctx.request_context.meta or {})
    except Exception:
        return {}


class RateLimiter:
    def __init__(self, per_min: int):
        self.per_min, self.hits, self._lock = per_min, defaultdict(deque), threading.Lock()

    def allow(self, who: str) -> bool:
        with self._lock:
            now, q = time.monotonic(), self.hits[who]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= self.per_min:
                return False
            q.append(now)
            return True


def _who(ctx: Context) -> str:
    h = ctx.headers or {}
    raw = h.get("authorization") or h.get("x-forwarded-for", "").split(",")[0].strip() or "local"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def build_server(settings: Settings | None = None, attestor: Attestor | None = None, anchor_client=None,
                 facilitator: Facilitator | None = None, fetch=None) -> MCPServer:
    settings = settings or Settings.from_env()
    attestor = attestor or Attestor(settings.db_path, settings.signing_seed)
    if anchor_client is None and settings.anchor_api_key:
        anchor_client = HttpAnchorClient(settings.anchor_url, settings.anchor_api_key)
    keys = attestor.public_keys()
    limiter = RateLimiter(settings.rate_per_min)
    cpu = anyio.CapacityLimiter(2)
    pay_problem = settings.pay.problem() if settings.pay.payments_enabled else None
    paywall = Paywall(settings.pay, facilitator, service={
        "url": f"{settings.public_url}/mcp", "serviceName": "Privi Risk",
        "tags": ["trading", "risk-management", "crypto", "position-sizing", "liquidation", "var", "ai-agents"],
        "iconUrl": "https://privi-discovery.onrender.com/icon.svg"},
        discovery={PAID: {"inputSchema": REPORT_SCHEMA, "example": REPORT_EXAMPLE,
                          "output": {"verdict": {"decision": "REDUCE"}, "report_id": "rr_..."}}})

    mcp = MCPServer(
        name="privi-risk", title="Privi Risk",
        description="Pre-trade risk desk for traders and AI trading agents: position sizing, liquidation check, "
                    "risk of ruin, live VaR, and signed GO/REDUCE/NO-TRADE reports anchored on the Privi chain.",
        instructions=INSTRUCTIONS, website_url=SOURCE, version=__version__,
    )

    def limited(ctx) -> CallToolResult | None:
        if not limiter.allow(_who(ctx)):
            return _result({"error": f"rate limit: {settings.rate_per_min} calls per minute"}, is_error=True)
        return None

    async def get_market(symbol, interval, closes, highs, lows, position_usd, horizon):
        if closes:
            return await anyio.to_thread.run_sync(lambda: risk.market_risk(
                closes, highs, lows, position_usd, horizon, 365)), {"source": "prices supplied by caller"}
        data = await anyio.to_thread.run_sync(lambda: market.fetch_candles(symbol, interval, fetch))
        m = await anyio.to_thread.run_sync(lambda: risk.market_risk(
            data["closes"], data["highs"], data["lows"], position_usd, horizon, data["periods_per_year"]))
        return m, {k: data[k] for k in ("symbol", "interval", "source", "as_of")}

    # ---------------- free ----------------

    @mcp.tool(title="Position size and liquidation check", annotations=FREE)
    def risk_position_size(
        account: Annotated[float, Field(description="Account equity in USD")],
        entry: Annotated[float, Field(description="Planned entry price")],
        stop: Annotated[float, Field(description="Stop-loss price")],
        ctx: Context,
        side: Annotated[Literal["long", "short"], Field(description="long or short")] = "long",
        risk_pct: Annotated[float, Field(description="Percent of the account to lose if the stop hits (default 1)")] = 1.0,
        leverage: Annotated[float | None, Field(description="Leverage for perps/futures/margin, e.g. 10. Omit for spot.")] = None,
        fee_pct: Annotated[float, Field(description="Taker fee per side in percent (default 0.1)")] = 0.1,
        maintenance_margin_pct: Annotated[float, Field(description="Exchange maintenance margin rate in percent (default 0.5)")] = 0.5,
        take_profit: Annotated[float | None, Field(description="Optional take-profit price, for reward-to-risk")] = None,
    ) -> CallToolResult:
        """How many units to trade so a stop-out loses exactly risk_pct of the account (fees included), with
        1R/2R/3R targets. With leverage: margin, liquidation price, and a hard warning when liquidation comes
        before the stop. Free."""
        if (r := limited(ctx)):
            return r
        try:
            out = risk.position_size(account, entry, stop, risk_pct, side, leverage, fee_pct,
                                     maintenance_margin_pct, take_profit)
        except risk.RiskError as e:
            return _result({"error": str(e)}, is_error=True)
        return _result({**out, "disclaimer": DISCLAIMER})

    @mcp.tool(title="Risk of ruin (Monte Carlo)", annotations=FREE)
    async def risk_of_ruin(
        win_rate: Annotated[float, Field(description="Share of winning trades, 0.45 or 45")],
        avg_win_r: Annotated[float, Field(description="Average win in R (multiples of the amount risked), e.g. 2")],
        ctx: Context,
        avg_loss_r: Annotated[float, Field(description="Average loss in R (1 if stops hold; above 1 if they slip)")] = 1.0,
        risk_pct: Annotated[float, Field(description="Percent of equity risked per trade")] = 1.0,
        trades: Annotated[int, Field(description="Number of trades to simulate (1-1000)", ge=1, le=1000)] = 200,
        drawdown_limit_pct: Annotated[float, Field(description="Drawdown you cannot tolerate, e.g. prop-firm limit 10 or 30")] = 30.0,
        ruin_pct: Annotated[float, Field(description="Drawdown that counts as ruin (default 50)")] = 50.0,
    ) -> CallToolResult:
        """Simulate 10,000 futures of a trading plan: chance of hitting your drawdown limit or ruin, ending
        equity range, Kelly fraction, and the max safe risk per trade. Free."""
        if (r := limited(ctx)):
            return r
        try:
            out = await anyio.to_thread.run_sync(lambda: risk.risk_of_ruin(
                win_rate, avg_win_r, avg_loss_r, risk_pct, trades, drawdown_limit_pct, ruin_pct), limiter=cpu)
        except risk.RiskError as e:
            return _result({"error": str(e)}, is_error=True)
        return _result({**out, "disclaimer": DISCLAIMER})

    @mcp.tool(title="Market risk check (volatility, VaR, ES)", annotations=FREE_NET)
    async def risk_market_check(
        ctx: Context,
        symbol: Annotated[str | None, Field(description="Crypto pair on Coinbase, e.g. BTC-USD, ETH-USD, SOL/USD")] = None,
        interval: Annotated[Literal["1m", "5m", "15m", "1h", "6h", "1d"], Field(description="Candle size (default 1d)")] = "1d",
        closes: Annotated[list[float] | None, Field(description="Or: closing prices for any market, oldest first (20-5000)")] = None,
        highs: Annotated[list[float] | None, Field(description="Optional highs matching closes")] = None,
        lows: Annotated[list[float] | None, Field(description="Optional lows matching closes")] = None,
        position_usd: Annotated[float | None, Field(description="Position value in USD for dollar VaR/ES")] = None,
        horizon: Annotated[int, Field(description="Holding period in candles (default 1)", ge=1, le=365)] = 1,
    ) -> CallToolResult:
        """Live realized volatility, ATR (and a 2xATR stop suggestion), max drawdown, Value-at-Risk and
        Expected Shortfall (CVaR) at 95% and 99%. Free."""
        if (r := limited(ctx)):
            return r
        if not symbol and not closes:
            return _result({"error": "give a symbol (e.g. BTC-USD) or a list of closes"}, is_error=True)
        try:
            m, src = await get_market(symbol, interval, closes, highs, lows, position_usd, horizon)
        except (risk.RiskError, market.MarketError) as e:
            return _result({"error": str(e)}, is_error=True)
        return _result({**src, **m, "disclaimer": DISCLAIMER})

    @mcp.tool(title="Verify a Privi Risk report", annotations=FREE_NET)
    async def risk_verify(
        report_id: Annotated[str | None, Field(description="A report id (rr_...) issued by Privi Risk")] = None,
        report: Annotated[dict[str, Any] | None, Field(description="Or a full report attestation to check offline")] = None,
    ) -> CallToolResult:
        """Check a pre-trade report's two signatures (Ed25519 + ML-DSA-87), its hash, and its Privi chain anchor. Free."""
        att = report or (attestor.get(report_id) if report_id else None)
        if not att:
            return _result({"error": "give a report_id issued here or a full report"}, is_error=True)
        v = Attestor.verify(att, keys["ed25519"], keys["ml_dsa_87"])
        out: dict[str, Any] = {"id": att.get("id"), **v, "signing_key_id": keys["key_id"]}
        anc = att.get("anchor") or ((attestor.get(att.get("id", "")) or {}).get("anchor"))
        if not anc:
            out["anchor"] = {"verified": False, "reason": "not anchored yet (batches go out every few minutes)"}
        elif anchor_client is None:
            out["anchor"] = {**anc, "verified": None, "reason": "chain check not configured"}
        else:
            try:
                chk = await anyio.to_thread.run_sync(anchor_client.verify, att["body_sha256"], anc["tx_hash"], anc["proof"])
                out["anchor"] = {"verified": bool(chk.get("verified")), "tx_hash": anc["tx_hash"],
                                 "block_number": chk.get("block_number"), "block_time_utc": chk.get("block_time_utc")}
            except AnchorError as e:
                out["anchor"] = {**anc, "verified": None, "reason": f"could not reach the chain checker: {e}"}
        return _result(out)

    @mcp.tool(title="Privi Risk status", annotations=FREE)
    def risk_status() -> dict[str, Any]:
        """Tools, prices, payment network, signing key and anchoring for this server."""
        return {"service": "privi-risk", "version": __version__, "copyright": COPYRIGHT,
                "free_tools": ["risk_position_size", "risk_of_ruin", "risk_market_check", "risk_verify"],
                "paid_tools": {PAID: {"price_usd": settings.pay.prices_usd[PAID], "currency": "USDC",
                                      "network": settings.pay.network.get("network") if settings.pay.network_key in
                                      ("base", "base-sepolia") else None, "protocol": "x402 v2 over MCP (_meta['x402/payment'])",
                                      "accepting_payments": settings.pay.payments_enabled and pay_problem is None}},
                "market_data": "Coinbase Exchange public candles (crypto); any market via supplied prices",
                "signatures": f"Ed25519 + {PQ_ALG}", "signing_key_id": keys["key_id"],
                "anchoring": {"enabled": anchor_client is not None, "chain": "Privi EVM chain via Privi Anchor"},
                "reports_issued": attestor.count(), "public_keys_url": f"{settings.public_url}/keys"}

    # ---------------- paid ----------------

    @mcp.tool(title="Pre-trade risk report (signed, on-chain)", annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True))
    async def risk_pretrade_report(
        account: Annotated[float, Field(description="Account equity in USD")],
        entry: Annotated[float, Field(description="Planned entry price")],
        stop: Annotated[float, Field(description="Stop-loss price")],
        side: Annotated[Literal["long", "short"], Field(description="long or short")],
        ctx: Context,
        risk_pct: Annotated[float, Field(description="Percent of the account to lose at the stop (default 1)")] = 1.0,
        leverage: Annotated[float | None, Field(description="Leverage for perps/futures; omit for spot")] = None,
        take_profit: Annotated[float | None, Field(description="Take-profit price")] = None,
        fee_pct: Annotated[float, Field(description="Taker fee per side, percent")] = 0.1,
        maintenance_margin_pct: Annotated[float, Field(description="Maintenance margin rate, percent")] = 0.5,
        symbol: Annotated[str | None, Field(description="Coinbase pair for live market risk, e.g. BTC-USD")] = None,
        closes: Annotated[list[float] | None, Field(description="Or closing prices for any market, oldest first")] = None,
        interval: Annotated[Literal["1m", "5m", "15m", "1h", "6h", "1d"], Field(description="Candle size for symbol")] = "1d",
        win_rate: Annotated[float | None, Field(description="Your plan's win rate (0.45 or 45) for the ruin check")] = None,
        avg_win_r: Annotated[float | None, Field(description="Your average win in R for the ruin check")] = None,
        trades: Annotated[int, Field(description="Trades to simulate for the ruin check", ge=1, le=1000)] = 200,
        label: Annotated[str, Field(description="Optional note, e.g. strategy or agent name (kept in the report)")] = "",
    ) -> CallToolResult:
        """Every pre-trade check in one report with a GO / REDUCE / NO-TRADE verdict and each reason. The report is
        signed Ed25519 + ML-DSA-87 and anchored on the Privi blockchain, so you, a prop firm, a fund or an AI
        agent's owner can prove the trade was risk-checked. $0.10 USDC on Base via x402."""
        if (r := limited(ctx)):
            return r
        if settings.pay.payments_enabled and pay_problem:
            return _result({"error": "paid reports are not open yet on this server; the free tools work now",
                            "detail": pay_problem}, is_error=True)
        try:  # validate before asking for payment, so nobody pays for a bad request
            sizing = risk.position_size(account, entry, stop, risk_pct, side, leverage, fee_pct,
                                        maintenance_margin_pct, take_profit)
        except risk.RiskError as e:
            return _result({"error": str(e)}, is_error=True)
        if (win_rate is None) != (avg_win_r is None):
            return _result({"error": "give both win_rate and avg_win_r for the ruin check, or neither"}, is_error=True)

        async def work() -> dict[str, Any]:
            mkt, src, mkt_err = None, None, None
            if symbol or closes:
                try:
                    mkt, src = await get_market(symbol, interval, closes, None, None, sizing["notional_usd"], 1)
                except (risk.RiskError, market.MarketError) as e:
                    mkt_err = str(e)
            ruin = None
            if win_rate is not None:
                try:
                    ruin = await anyio.to_thread.run_sync(lambda: risk.risk_of_ruin(
                        win_rate, avg_win_r, 1.0, sizing["risk_pct_of_account"], trades), limiter=cpu)
                except risk.RiskError as e:
                    ruin = None; mkt_err = (mkt_err + "; " if mkt_err else "") + f"ruin check skipped: {e}"
            v = risk.verdict(float(account), sizing, mkt, ruin)
            body = {"trade": {"side": side, "entry": entry, "stop": stop, "take_profit": take_profit,
                              "leverage": leverage, "account": account, "risk_pct": risk_pct,
                              "market": (src or {}).get("symbol") or ("caller prices" if closes else None)},
                    "verdict": v, "sizing": sizing,
                    "market_risk": mkt and {k: mkt[k] for k in ("last_price", "volatility_annualized_pct", "atr_14_pct",
                                                                 "value_at_risk_usd", "expected_shortfall_usd")},
                    "ruin": ruin and {k: ruin[k] for k in ("expectancy_r_per_trade", "probability_of_ruin",
                                                           "probability_drawdown_at_least_limit", "max_safe_risk_pct",
                                                           "half_kelly_risk_pct")},
                    "label": label[:120], "disclaimer": DISCLAIMER}
            att = await anyio.to_thread.run_sync(attestor.issue, "pretrade_risk_report", body)
            return {"verdict": v, "sizing": sizing, "market_risk": mkt, "market_source": src, "ruin": ruin,
                    "notes": mkt_err, "report_id": att["id"], "report_sha256": att["body_sha256"],
                    "signatures": f"Ed25519 + {PQ_ALG}",
                    "anchoring": "queued for the Privi chain" if anchor_client else "anchoring not configured",
                    "report_url": f"{settings.public_url}/reports/{att['id']}",
                    "disclaimer": DISCLAIMER, "copyright": COPYRIGHT}

        return await paywall.run(PAID, "Signed pre-trade risk report with GO/REDUCE/NO-TRADE verdict", _meta(ctx), work)

    # ---------------- http ----------------

    cors = {"Access-Control-Allow-Origin": "*"}

    @mcp.custom_route("/health", methods=["GET"], include_in_schema=False)
    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"ok": True, "service": "privi-risk", "version": __version__}, headers=cors)

    @mcp.custom_route("/status", methods=["GET"], include_in_schema=False)
    async def status(_: Request) -> JSONResponse:
        return JSONResponse(risk_status(), headers=cors)

    @mcp.custom_route("/keys", methods=["GET"], include_in_schema=False)
    async def public_keys(_: Request) -> JSONResponse:
        return JSONResponse({**keys, "issuer": "Privi Risk (Privi World Co)", "copyright": COPYRIGHT},
                            headers={**cors, "Cache-Control": "public, max-age=3600"})

    @mcp.custom_route("/reports/{rid}", methods=["GET"], include_in_schema=False)
    async def get_report(request: Request) -> JSONResponse:
        att = attestor.get(request.path_params["rid"])
        if not att:
            return JSONResponse({"error": "not found"}, status_code=404, headers=cors)
        return JSONResponse(att, headers=cors)

    @mcp.custom_route("/.well-known/glama.json", methods=["GET"], include_in_schema=False)
    async def glama(_: Request) -> JSONResponse:
        return JSONResponse({"$schema": "https://glama.ai/mcp/schemas/server.json", "maintainers": ["canoydario847-cloud"]})

    @mcp.custom_route("/.well-known/mcp/server-card.json", methods=["GET"], include_in_schema=False)
    async def server_card(_: Request) -> JSONResponse:
        tools = [t.model_dump(by_alias=True, exclude_none=True) for t in await mcp.list_tools()]
        return JSONResponse({"serverInfo": {"name": "privi-risk", "title": "Privi Risk", "version": __version__,
                                            "description": "Pre-trade risk desk: position sizing, liquidation check, risk of ruin, live VaR, signed verdicts.",
                                            "websiteUrl": "https://privi-hub.onrender.com"},
                             "authentication": {"required": False, "schemes": []},
                             "tools": tools, "resources": [], "prompts": []},
                            headers={**cors, "Cache-Control": "public, max-age=3600"})

    @mcp.custom_route("/", methods=["GET"], include_in_schema=False)
    async def root(_: Request) -> Response:
        return Response(LANDING.format(url=settings.public_url, price=settings.pay.prices_usd[PAID],
                                       copyright=COPYRIGHT, disclaimer=DISCLAIMER),
                        media_type="text/html; charset=utf-8")

    mcp._privi_attestor = attestor
    mcp._privi_anchor = anchor_client
    return mcp


LANDING = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Privi Risk</title><meta name="description" content="Free position size calculator with liquidation check, risk of ruin Monte Carlo, live crypto VaR, and signed pre-trade risk reports for traders and AI trading agents.">
<style>body{{font:16px/1.55 system-ui,sans-serif;max-width:680px;margin:48px auto;padding:0 16px;color:#16181d;background:#f7f8fa}}
code,pre{{font:14px ui-monospace,monospace;background:#eef1f6;border-radius:6px}}pre{{padding:12px;overflow-x:auto}}code{{padding:1px 4px}}
a{{color:#3451b2}}@media (prefers-color-scheme:dark){{body{{color:#e8eaee;background:#0f1115}}code,pre{{background:#1d222b}}a{{color:#8ea6ff}}}}</style></head><body>
<h1>Privi Risk</h1>
<p><strong>Don't bet the bank.</strong> The pre-trade risk desk for crypto and market traders and AI trading agents. Most accounts aren't blown up
by bad calls, but by position size, leverage, and liquidation prices that sit inside the stop.</p>
<ul><li><code>risk_position_size</code> (free): exact size for your risk, fees included, liquidation price, and a hard warning if you'd be liquidated before your stop.</li>
<li><code>risk_of_ruin</code> (free): 10,000 simulated futures of your plan: drawdown and ruin odds, Kelly, max safe risk per trade.</li>
<li><code>risk_market_check</code> (free): live volatility, ATR, VaR and Expected Shortfall for any Coinbase crypto pair, or any market from your prices.</li>
<li><code>risk_pretrade_report</code> (${price} USDC on Base, x402): GO / REDUCE / NO-TRADE verdict, signed with post-quantum ML-DSA-87 and anchored on the Privi blockchain.</li></ul>
<p>Connect your AI agent (MCP, streamable HTTP):</p>
<pre>{{ "mcpServers": {{ "privi-risk": {{ "url": "{url}/mcp" }} }} }}</pre>
<p>Public keys: <a href="{url}/keys">/keys</a> · Status: <a href="{url}/status">/status</a> · Built by Privi World Co, Port Huron, Michigan ·
<a href="https://privi-hub.onrender.com">Everything Privi offers</a> · <a href="mailto:dariocanoy@priviflow.us">dariocanoy@priviflow.us</a></p>
<p><small>{disclaimer} {copyright}</small></p></body></html>"""


def _anchor_loop(attestor: Attestor, client, interval: int) -> None:
    while True:
        time.sleep(interval)
        try:
            n = anchor_pending(attestor, client)
            if n:
                print(f"[privi-risk] anchored {n} reports on the Privi chain", flush=True)
        except Exception as e:
            print(f"[privi-risk] anchoring failed, will retry: {e}", flush=True)


def main() -> None:
    p = argparse.ArgumentParser(description="Privi Risk MCP server")
    p.add_argument("--stdio", action="store_true")
    p.add_argument("--host", default=os.getenv("HOST", "0.0.0.0"))
    p.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000")))
    args = p.parse_args()
    settings = Settings.from_env()
    mcp = build_server(settings)
    problem = settings.pay.problem() if settings.pay.payments_enabled else None
    print(f"[privi-risk] paid reports: {'ready' if not problem else 'not accepting payments - ' + problem}", flush=True)
    if mcp._privi_anchor is not None:
        threading.Thread(target=_anchor_loop, args=(mcp._privi_attestor, mcp._privi_anchor, settings.anchor_interval),
                         daemon=True).start()
    if args.stdio:
        mcp.run("stdio")
        return
    import uvicorn
    from .front import QuickGet
    uvicorn.run(QuickGet(mcp.streamable_http_app(host=args.host, stateless_http=True, json_response=True),
                         "Privi Risk", "privi-risk", settings.public_url), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
