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
import os
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

# JSON Schema validating extensions.bazaar.info for MCP tools (x402 specs/extensions/bazaar.md).
BAZAAR_MCP_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "input": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "const": "mcp"},
                "toolName": {"type": "string"},
                "description": {"type": "string"},
                "transport": {"type": "string", "enum": ["streamable-http", "sse"]},
                "inputSchema": {"type": "object"},
                "example": {"type": "object"},
            },
            "required": ["type", "toolName", "inputSchema"],
            "additionalProperties": False,
        },
        "output": {
            "type": "object",
            "properties": {"type": {"type": "string"}, "example": {"type": "object"}},
            "required": ["type"],
        },
    },
    "required": ["input"],
}


def bazaar_extension(tool: str, description: str, spec: dict) -> dict:
    """x402 Bazaar discovery declaration for one paid MCP tool."""
    info: dict[str, Any] = {"input": {"type": "mcp", "toolName": tool, "description": description,
                                      "transport": "streamable-http", "inputSchema": spec["inputSchema"],
                                      "example": spec["example"]}}
    if spec.get("output") is not None:
        info["output"] = {"type": "json", "example": spec["output"]}
    return {"info": info, "schema": BAZAAR_MCP_SCHEMA}


class Facilitator(Protocol):
    async def verify(self, payload: dict, requirements: dict) -> dict: ...
    async def settle(self, payload: dict, requirements: dict) -> dict: ...


CDP_FACILITATOR_URL = "https://api.cdp.coinbase.com/platform/v2/x402"


def _b64url(b: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def cdp_jwt(key_id: str, key_secret_b64: str, method: str, url: str, lifetime_s: int = 120) -> str:
    """Bearer JWT for Coinbase Developer Platform v2 REST calls, signed with an Ed25519 secret API key.

    Header: alg EdDSA, typ JWT, kid=<key id>, random nonce. Claims: sub=<key id>, iss "cdp",
    aud ["cdp_service"], nbf/exp (2 minutes), uri "<METHOD> <host><path>".
    """
    import base64
    import secrets as _secrets
    import time as _time
    from urllib.parse import urlsplit

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    raw = base64.b64decode(key_secret_b64)
    if len(raw) != 64:
        raise ValueError("CDP API key secret must be a base64 Ed25519 key (64 bytes)")
    signer = Ed25519PrivateKey.from_private_bytes(raw[:32])
    parts = urlsplit(url)
    now = int(_time.time())
    header = {"alg": "EdDSA", "typ": "JWT", "kid": key_id, "nonce": _secrets.token_hex(16)}
    claims = {"sub": key_id, "iss": "cdp", "aud": ["cdp_service"], "nbf": now, "exp": now + lifetime_s,
              "uri": f"{method.upper()} {parts.netloc}{parts.path}"}
    signing_input = (_b64url(json.dumps(header, separators=(",", ":")).encode()) + "." +
                     _b64url(json.dumps(claims, separators=(",", ":")).encode()))
    return signing_input + "." + _b64url(signer.sign(signing_input.encode()))


class HttpFacilitator:
    """Calls a facilitator's POST /verify and POST /settle endpoints.

    With cdp_key_id/cdp_key_secret set, each request carries a fresh CDP JWT (Coinbase's facilitator,
    required for Base mainnet). Otherwise an optional static Authorization header is sent.
    """

    def __init__(self, base_url: str, auth_header: str = "", timeout: float = 30.0,
                 cdp_key_id: str = "", cdp_key_secret: str = ""):
        self.base_url = base_url.rstrip("/")
        self.auth_header = auth_header
        self.timeout = timeout
        self.cdp_key_id, self.cdp_key_secret = cdp_key_id, cdp_key_secret

    def _post(self, path: str, body: dict) -> dict:
        req = urllib.request.Request(
            f"{self.base_url}/{path}",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        if self.cdp_key_id and self.cdp_key_secret:
            req.add_header("Authorization", "Bearer " + cdp_jwt(self.cdp_key_id, self.cdp_key_secret, "POST",
                                                                 f"{self.base_url}/{path}"))
        elif self.auth_header:
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
    def __init__(self, settings: Settings, facilitator: Facilitator | None = None,
                 service: dict | None = None, discovery: dict[str, dict] | None = None, privi=None):
        """service: {"url": public MCP endpoint, "serviceName", "tags", "iconUrl"} for x402 resource metadata.
        discovery: {tool: {"inputSchema", "example", "output"}} declared to the x402 Bazaar."""
        self.settings = settings
        self.service = service or {}
        self.discovery = discovery or {}
        # PRIVI token payments: an explicit PriviToken, or opt-in with PRIVI_PAYMENTS=1 (reads Base mainnet).
        if privi is None and os.getenv("PRIVI_PAYMENTS") == "1":
            from .privi_token import PriviToken
            privi = PriviToken.from_env(settings.pay_to, getattr(settings, "db_path", None) or "privi-payments.db")
        self.privi = privi
        self.facilitator = facilitator or HttpFacilitator(
            settings.facilitator_url, settings.facilitator_auth,
            cdp_key_id=getattr(settings, "cdp_key_id", ""), cdp_key_secret=getattr(settings, "cdp_key_secret", ""))

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
        if not self.service.get("url"):
            return {"url": f"mcp://tool/{tool}", "description": description, "mimeType": "application/json"}
        r = {"url": self.service["url"], "description": description, "mimeType": "application/json"}
        for k in ("serviceName", "tags", "iconUrl"):
            if self.service.get(k):
                r[k] = self.service[k]
        return r

    def extensions(self, tool: str, description: str) -> dict:
        spec = self.discovery.get(tool)
        return {"bazaar": bazaar_extension(tool, description, spec)} if spec and self.service.get("url") else {}

    def payment_required(self, tool: str, description: str, error: str) -> CallToolResult:
        body = {
            "x402Version": X402_VERSION,
            "error": error,
            "resource": self.resource(tool, description),
            "accepts": [self.requirements(tool)],
        }
        ext = self.extensions(tool, description)
        if ext:
            body["extensions"] = ext
        alt = self.privi_quote(tool)
        if alt:
            body["privi"] = alt
        return CallToolResult(
            is_error=True,
            structured_content=body,
            content=[TextContent(type="text", text=json.dumps(body, separators=(",", ":")))],
        )

    def privi_quote(self, tool: str) -> dict | None:
        """The PRIVI alternative to the USDC price, or None when PRIVI payments are off or unpriced."""
        if not self.privi or tool not in self.settings.prices_usd:
            return None
        try:
            return self.privi.quote_usd(self.settings.prices_usd[tool])
        except Exception:  # never let a market read break the USDC path
            return None

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

        privi_payment = (meta or {}).get("privi/payment")
        if privi_payment is not None and self.privi:
            ok, info = await anyio.to_thread.run_sync(
                self.privi.verify_payment, privi_payment, tool, self.settings.prices_usd[tool])
            if not ok:
                return self.payment_required(tool, description, f"Invalid PRIVI payment: {info['error']}")
            data = await work()
            return CallToolResult(content=[TextContent(type="text", text=json.dumps(data))], structured_content=data,
                                  meta={"privi/receipt": info})

        payload = (meta or {}).get(PAYMENT_META_KEY)
        if payload is None:
            return self.payment_required(tool, description, "Payment required to access this resource")

        req = self.requirements(tool)
        if isinstance(payload, dict):
            # Clients should echo resource and extensions; fill them in if they did not, so the
            # facilitator can index this tool in the x402 Bazaar on settlement. Not part of the signature.
            payload.setdefault("resource", self.resource(tool, description))
            ext = self.extensions(tool, description)
            if ext:
                payload.setdefault("extensions", {})
                if isinstance(payload["extensions"], dict):
                    for k, v in ext.items():
                        payload["extensions"].setdefault(k, v)
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
