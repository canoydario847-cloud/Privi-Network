"""x402 payments over MCP (x402 v2, MCP transport spec).

Flow for a paid tool:
  1. Call without payment -> tool result with isError=true and a PaymentRequired
     object in structuredContent (and as JSON text in content[0]).
  2. Client signs a payment and retries with it in _meta["x402/payment"].
  3. Server checks it matches what we asked for, asks the facilitator to /verify,
     runs the tool, asks the facilitator to /settle, and returns the result with
     the settlement in _meta["x402/payment-response"].

Spec: https://github.com/x402-foundation/x402/blob/main/specs/transports-v2/mcp.md
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Awaitable, Callable, Protocol

import anyio
from mcp_types import CallToolResult, TextContent

from .config import Settings, usd_to_atomic

X402_VERSION = 2
PAYMENT_META_KEY = "x402/payment"
RESPONSE_META_KEY = "x402/payment-response"
MATCH_FIELDS = ("scheme", "network", "amount", "asset", "payTo")


class Facilitator(Protocol):
    async def verify(self, payload: dict, requirements: dict) -> dict: ...
    async def settle(self, payload: dict, requirements: dict) -> dict: ...


class HttpFacilitator:
    """Calls a facilitator's POST /verify and POST /settle endpoints."""

    def __init__(self, base_url: str, auth_header: str = "", timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.auth_header = auth_header
        self.timeout = timeout

    def _post(self, path: str, body: dict) -> dict:
        req = urllib.request.Request(
            f"{self.base_url}/{path}",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        if self.auth_header:
            req.add_header("Authorization", self.auth_header)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                return json.loads(e.read() or b"{}")
            except ValueError:
                return {"error": f"facilitator HTTP {e.code}"}

    async def _call(self, path: str, payload: dict, requirements: dict) -> dict:
        body = {"x402Version": X402_VERSION, "paymentPayload": payload, "paymentRequirements": requirements}
        return await anyio.to_thread.run_sync(self._post, path, body)

    async def verify(self, payload: dict, requirements: dict) -> dict:
        return await self._call("verify", payload, requirements)

    async def settle(self, payload: dict, requirements: dict) -> dict:
        return await self._call("settle", payload, requirements)


class Paywall:
    def __init__(self, settings: Settings, facilitator: Facilitator | None = None):
        self.settings = settings
        self.facilitator = facilitator or HttpFacilitator(settings.facilitator_url, settings.facilitator_auth)

    def requirements(self, tool: str) -> dict:
        net = self.settings.network
        return {
            "scheme": "exact",
            "network": net["network"],
            "amount": usd_to_atomic(self.settings.prices_usd[tool]),
            "asset": net["asset"],
            "payTo": self.settings.pay_to,
            "maxTimeoutSeconds": 60,
            "extra": dict(net["extra"]),
        }

    def resource(self, tool: str, description: str) -> dict:
        return {"url": f"mcp://tool/{tool}", "description": description, "mimeType": "application/json"}

    def payment_required(self, tool: str, description: str, error: str) -> CallToolResult:
        body = {
            "x402Version": X402_VERSION,
            "error": error,
            "resource": self.resource(tool, description),
            "accepts": [self.requirements(tool)],
        }
        return CallToolResult(
            is_error=True,
            structured_content=body,
            content=[TextContent(type="text", text=json.dumps(body, separators=(",", ":")))],
        )

    def _matches(self, payload: dict, req: dict) -> str | None:
        if not isinstance(payload, dict):
            return "payment must be an object"
        if payload.get("x402Version") != X402_VERSION:
            return f"unsupported x402Version (expected {X402_VERSION})"
        accepted = payload.get("accepted")
        if not isinstance(accepted, dict):
            return "payment is missing 'accepted'"
        for f in MATCH_FIELDS:
            a, b = str(accepted.get(f, "")), str(req[f])
            if f in ("asset", "payTo"):
                a, b = a.lower(), b.lower()
            if a != b:
                return f"payment '{f}' does not match this tool's price"
        return None

    async def run(
        self,
        tool: str,
        description: str,
        meta: dict | None,
        work: Callable[[], Awaitable[dict[str, Any]]],
    ) -> CallToolResult:
        """Gate `work` behind payment. `work` returns the structured result."""
        if not self.settings.payments_enabled:
            data = await work()
            return CallToolResult(content=[TextContent(type="text", text=json.dumps(data))], structured_content=data)

        payload = (meta or {}).get(PAYMENT_META_KEY)
        if payload is None:
            return self.payment_required(tool, description, "Payment required to access this resource")

        req = self.requirements(tool)
        mismatch = self._matches(payload, req)
        if mismatch:
            return self.payment_required(tool, description, f"Invalid payment: {mismatch}")

        verified = await self.facilitator.verify(payload, req)
        if not verified.get("isValid"):
            reason = verified.get("invalidReason") or verified.get("error") or "verification failed"
            return self.payment_required(tool, description, f"Invalid payment: {reason}")

        data = await work()

        settled = await self.facilitator.settle(payload, req)
        if not settled.get("success"):
            reason = settled.get("errorReason") or settled.get("error") or "unknown"
            return self.payment_required(tool, description, f"Settlement failed: {reason}")

        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(data))],
            structured_content=data,
            meta={RESPONSE_META_KEY: settled},
        )
