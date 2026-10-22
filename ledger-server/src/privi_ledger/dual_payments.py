"""Privi dual-payment *groundwork*, not a second live currency rail.

USDC/x402 payments continue through the existing Paywall unchanged. The
PRVI_TEST lane simulates a quote + one-time receipt for development only.
There is intentionally no PRVI balance, mint, transfer, exchange rate, credit,
paid entitlement, facilitator settlement or chain interaction in this module.
"""

import hashlib
import os
import secrets
import threading
import time
from typing import Annotated, Literal


TEST_ASSET = "PRVI_TEST"  # Never native PRVI, BNB PRIV, TEST or real value.
TEST_NETWORK = "base-sepolia"  # Existing Ledger dev network; no Privi financial mainnet.
ACKNOWLEDGEMENT = "VALUELESS TEST ONLY"
TEST_SKUS = ("ledger_upgrade_pro", "ledger_audit_stream", "guard_check")
QUOTE_TTL_SECONDS = 600
MAX_QUOTES = 256


class PaymentSimulationError(ValueError):
    """A test-payment request failed closed; never fall back to paid access."""


class DualPayments:
    """Thread-safe, volatile, organization-bound *simulated* test receipts."""

    def __init__(self, *, network_key: str, payments_enabled: bool,
                 prices_usd: dict[str, str], enable_test: bool = False, clock=None):
        self.network_key = network_key
        self.payments_enabled = bool(payments_enabled)
        self.prices_usd = dict(prices_usd)
        self.test_enabled = bool(enable_test) and network_key == TEST_NETWORK
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._quotes: dict[str, dict] = {}

    def options(self) -> dict:
        """Machine-readable separation of existing real billing and demo-only path."""
        return {
            "version": 1,
            "payments": [
                {"method": "USDC_X402", "asset": "USDC", "network": self.network_key,
                 "enabled": self.payments_enabled, "existing_tool": "ledger_upgrade_pro",
                 "settlement": "facilitator-verified x402; unchanged by this integration"},
                {"method": "PRVI_TEST_SIMULATION", "asset": TEST_ASSET,
                 "network": "OFF_CHAIN_SIMULATION", "enabled": self.test_enabled,
                 "valueless": True, "on_chain": False, "transfers_tokens": False,
                 "settles_debt": False, "grants_entitlements": False,
                 "mainnet_live": False},
            ],
            "native_prvi_mainnet_payments_enabled": False,
            "native_prvi_reason": "Native financial PRVI mainnet has not passed launch gates",
            "test_flow": ["privi_test_payment_quote", "privi_test_payment_simulate"],
        }

    def _require_test(self):
        if not self.test_enabled:
            raise PaymentSimulationError("valueless PRVI_TEST simulation is disabled; it cannot be used for real payments")

    def _clean(self):
        now = self._clock()
        for qid, value in list(self._quotes.items()):
            if now > value["expires_at"]:
                del self._quotes[qid]
        if len(self._quotes) >= MAX_QUOTES:
            raise PaymentSimulationError("too many outstanding test quotes")

    def quote(self, org_id: str, sku: str) -> dict:
        """Create an in-memory test quote for an existing service SKU, without credit."""
        self._require_test()
        if not isinstance(org_id, str) or not org_id.startswith("org_"):
            raise PaymentSimulationError("a valid Privi organization is required")
        if sku not in TEST_SKUS or sku not in self.prices_usd:
            raise PaymentSimulationError("unsupported test SKU")
        with self._lock:
            self._clean()
            qid = "prvi_test_" + secrets.token_hex(16)
            expires_at = self._clock() + QUOTE_TTL_SECONDS
            self._quotes[qid] = {"org_id": org_id, "sku": sku, "expires_at": expires_at,
                                 "state": "quoted"}
        return {"quote_id": qid, "sku": sku, "asset": TEST_ASSET,
                "mode": "SIMULATION_ONLY", "simulation_units": 1,
                "economic_value": "none", "conversion_rate": None,
                "expires_in_seconds": QUOTE_TTL_SECONDS, "service_unlocked": False,
                "paid": False, "on_chain": False,
                "next": "Call privi_test_payment_simulate with the quote ID and explicit acknowledgement."}

    def simulate(self, org_id: str, quote_id: str, acknowledgement: str) -> dict:
        """Consume one quote; return an unmistakably valueless, non-redeemable receipt."""
        self._require_test()
        if acknowledgement != ACKNOWLEDGEMENT:
            raise PaymentSimulationError("explicit VALUELESS TEST ONLY acknowledgement required")
        if not isinstance(quote_id, str) or not quote_id.startswith("prvi_test_"):
            raise PaymentSimulationError("invalid test quote")
        with self._lock:
            self._clean()
            q = self._quotes.get(quote_id)
            if not q or q["org_id"] != org_id:
                raise PaymentSimulationError("test quote not found for this organization or has expired")
            if q["state"] != "quoted":
                raise PaymentSimulationError("test quote already simulated; replay refused")
            q["state"] = "simulated"
            sku = q["sku"]
        receipt_id = hashlib.sha256(f"privi-test-v1:{org_id}:{quote_id}:{sku}".encode()).hexdigest()
        return {"status": "SIMULATED_NOT_PAID", "receipt_id": "simulation_" + receipt_id,
                "quote_id": quote_id, "sku": sku, "asset": TEST_ASSET,
                "simulation_units": 1, "valueless": True, "on_chain": False,
                "real_transaction_hash": None, "paid": False, "settled": False,
                "grants_entitlements": False, "service_unlocked": False,
                "note": "Test receipt is NOT proof of payment. No Pro plan, Guard credits or paid tools unlocked."}


def register(mcp, settings, *, org_from, result, unauthorized) -> None:
    """Register additive MCP tools. Existing Paywall/USDC handlers stay intact."""
    from mcp.server.mcpserver import Context
    from mcp_types import ToolAnnotations
    from pydantic import Field

    router = DualPayments(
        network_key=settings.network_key,
        payments_enabled=settings.payments_enabled,
        prices_usd=settings.prices_usd,
        enable_test=os.getenv("PRVI_TEST_PAYMENT_MODE", "0") == "1",
    )
    mcp.privi_dual_payments = router

    @mcp.tool(title="Privi: payment methods", annotations=ToolAnnotations(readOnlyHint=True))
    def privi_payment_options() -> dict:
        """See existing USDC/x402 service billing and separately gated valueless PRVI_TEST development mode."""
        return router.options()

    @mcp.tool(title="Privi: create a valueless test-payment quote",
              annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False))
    def privi_test_payment_quote(
        ctx: Context,
        sku: Annotated[Literal["ledger_upgrade_pro", "ledger_audit_stream", "guard_check"],
                       Field(description="Existing priced tool to model; NO service will be unlocked")],
    ):
        """Off-chain PRVI_TEST quote. Requires organization key and explicit test mode. Never takes money."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        try:
            return result(router.quote(org["org_id"], sku))
        except PaymentSimulationError as e:
            return result({"error": str(e)}, is_error=True)

    @mcp.tool(title="Privi: simulate a valueless test payment",
              annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False))
    def privi_test_payment_simulate(
        ctx: Context,
        quote_id: Annotated[str, Field(description="Short-lived PRVI_TEST quote ID")],
        acknowledgement: Annotated[str, Field(description="Must equal VALUELESS TEST ONLY")],
    ):
        """Consume a test quote once. Receipt is NOT payment, on-chain proof or entitlement."""
        org = org_from(ctx)
        if not org:
            return unauthorized
        try:
            return result(router.simulate(org["org_id"], quote_id, acknowledgement))
        except PaymentSimulationError as e:
            return result({"error": str(e)}, is_error=True)
