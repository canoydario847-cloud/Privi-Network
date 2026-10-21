# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Risk - https://priviflow.us - dariocanoy@priviflow.us
"""Settings from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

# USDC on Base. Name/version are the token's EIP-712 domain, needed by x402 "exact".
NETWORKS = {
    "base-sepolia": {"network": "eip155:84532", "asset": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
                     "extra": {"name": "USDC", "version": "2"}},
    "base": {"network": "eip155:8453", "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
             "extra": {"name": "USD Coin", "version": "2"}},
}
DEFAULT_PRICES_USD = {"risk_pretrade_report": "0.10"}


def usd_to_atomic(usd: str) -> str:
    """'0.10' -> '100000' (USDC has 6 decimals)."""
    whole, _, frac = usd.strip().partition(".")
    value = int(whole or "0") * 1_000_000 + int(((frac + "000000")[:6]) or "0")
    if value <= 0:
        raise ValueError(f"price must be positive: {usd}")
    return str(value)


@dataclass
class PaySettings:
    payments_enabled: bool = True
    network_key: str = "base"
    pay_to: str = ""
    facilitator_url: str = "https://api.cdp.coinbase.com/platform/v2/x402"
    facilitator_auth: str = ""
    cdp_key_id: str = ""
    cdp_key_secret: str = ""
    prices_usd: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_PRICES_USD))

    @property
    def network(self) -> dict:
        return NETWORKS[self.network_key]

    def problem(self) -> str | None:
        """Why paid tools can't take payments yet, or None when they can."""
        if self.network_key not in NETWORKS:
            return f"RISK_NETWORK must be one of {list(NETWORKS)}"
        if not (self.pay_to.startswith("0x") and len(self.pay_to) == 42):
            return "RISK_PAY_TO is not set to the wallet that receives payments"
        if self.network_key == "base" and "x402.org" in self.facilitator_url:
            return "Base mainnet needs the Coinbase CDP facilitator"
        if "api.cdp.coinbase.com" in self.facilitator_url and not (self.cdp_key_id and self.cdp_key_secret):
            return "CDP_API_KEY_ID / CDP_API_KEY_SECRET are not set"
        for usd in self.prices_usd.values():
            usd_to_atomic(usd)
        return None


@dataclass
class Settings:
    db_path: str = "risk.db"
    public_url: str = "https://privi-risk.onrender.com"
    signing_seed: str = ""
    anchor_url: str = "https://privi-anchor.onrender.com/mcp"
    anchor_api_key: str = ""
    anchor_interval: int = 300
    rate_per_min: int = 30
    pay: PaySettings = field(default_factory=PaySettings)

    @classmethod
    def from_env(cls) -> "Settings":
        pay = PaySettings(
            payments_enabled=os.getenv("RISK_PAYMENTS_ENABLED", "1").strip().lower() in ("1", "true", "yes", "on"),
            network_key=os.getenv("RISK_NETWORK", "base"),
            pay_to=os.getenv("RISK_PAY_TO", "").strip(),
            facilitator_url=os.getenv("RISK_FACILITATOR_URL", PaySettings.facilitator_url).rstrip("/"),
            facilitator_auth=os.getenv("RISK_FACILITATOR_AUTH", ""),
            cdp_key_id=os.getenv("CDP_API_KEY_ID", "").strip().strip("\"'"),
            cdp_key_secret=os.getenv("CDP_API_KEY_SECRET", "").strip().strip("\"'"))
        if os.getenv("RISK_PRICE_PRETRADE_REPORT"):
            pay.prices_usd["risk_pretrade_report"] = os.environ["RISK_PRICE_PRETRADE_REPORT"].strip()
        return cls(
            db_path=os.getenv("RISK_DB_PATH", "risk.db"),
            public_url=os.getenv("RISK_PUBLIC_URL", cls.public_url).rstrip("/"),
            signing_seed=os.getenv("RISK_SIGNING_SEED", ""),
            anchor_url=os.getenv("RISK_ANCHOR_URL", cls.anchor_url),
            anchor_api_key=os.getenv("RISK_ANCHOR_API_KEY", "").split(",")[0].strip(),
            anchor_interval=int(os.getenv("RISK_ANCHOR_INTERVAL", "300")),
            rate_per_min=int(os.getenv("RISK_RATE_PER_MIN", "30")),
            pay=pay)
