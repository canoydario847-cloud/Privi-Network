"""Settings, read from environment variables (see .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

# USDC on Base. Name/version are the token's EIP-712 domain, needed by x402 "exact".
NETWORKS = {
    "base-sepolia": {
        "network": "eip155:84532",
        "asset": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
        "extra": {"name": "USDC", "version": "2"},
    },
    "base": {
        "network": "eip155:8453",
        "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        "extra": {"name": "USD Coin", "version": "2"},
    },
}

DEFAULT_PRICES_USD = {
    "ledger_audit_stream": "0.02",
    "ledger_upgrade_pro": "29",
    "passport_issue": "1",       # free-plan organizations; Pro and enterprise issue for free
}


def _bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "on")


def usd_to_atomic(usd: str) -> str:
    """'0.01' -> '10000' (USDC has 6 decimals)."""
    whole, _, frac = usd.strip().partition(".")
    frac = (frac + "000000")[:6]
    value = int(whole or "0") * 1_000_000 + int(frac or "0")
    if value <= 0:
        raise ValueError(f"price must be positive: {usd}")
    return str(value)


@dataclass
class Settings:
    db_path: str = "ledger.db"
    payments_enabled: bool = True
    network_key: str = "base-sepolia"
    pay_to: str = ""
    facilitator_url: str = "https://x402.org/facilitator"
    facilitator_auth: str = ""
    cdp_key_id: str = ""
    cdp_key_secret: str = ""
    prices_usd: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_PRICES_USD))
    admin_key: str = ""

    @classmethod
    def from_env(cls) -> "Settings":
        s = cls(
            db_path=os.getenv("LEDGER_DB_PATH", "ledger.db"),
            payments_enabled=_bool("LEDGER_PAYMENTS_ENABLED", True),
            network_key=os.getenv("LEDGER_NETWORK", "base-sepolia"),
            pay_to=os.getenv("LEDGER_PAY_TO", "").strip(),
            facilitator_url=os.getenv("LEDGER_FACILITATOR_URL", "https://x402.org/facilitator").rstrip("/"),
            facilitator_auth=os.getenv("LEDGER_FACILITATOR_AUTH", ""),
            cdp_key_id=os.getenv("CDP_API_KEY_ID", "").strip().strip("\"'"),
            cdp_key_secret=os.getenv("CDP_API_KEY_SECRET", "").strip().strip("\"'"),
            admin_key=os.getenv("LEDGER_ADMIN_KEY", ""),
        )
        if os.getenv("LEDGER_PRICE_PRO_MONTH"):
            s.prices_usd["ledger_upgrade_pro"] = os.environ["LEDGER_PRICE_PRO_MONTH"]
        if os.getenv("LEDGER_PRICE_PASSPORT"):
            s.prices_usd["passport_issue"] = os.environ["LEDGER_PRICE_PASSPORT"]
        if os.getenv("LEDGER_PRICE_AUDIT_STREAM"):
            s.prices_usd["ledger_audit_stream"] = os.environ["LEDGER_PRICE_AUDIT_STREAM"]
        s.validate()
        return s

    def validate(self) -> None:
        if self.network_key not in NETWORKS:
            raise ValueError(f"LEDGER_NETWORK must be one of {list(NETWORKS)}")
        for usd in self.prices_usd.values():
            usd_to_atomic(usd)
        if self.payments_enabled and self.network_key == "base" and "x402.org" in self.facilitator_url:
            raise ValueError("Base mainnet needs a production facilitator: set LEDGER_FACILITATOR_URL to "
                             "https://api.cdp.coinbase.com/platform/v2/x402 and CDP_API_KEY_ID / CDP_API_KEY_SECRET")
        if self.payments_enabled and "api.cdp.coinbase.com" in self.facilitator_url and not (self.cdp_key_id and self.cdp_key_secret):
            raise ValueError("The Coinbase facilitator needs CDP_API_KEY_ID and CDP_API_KEY_SECRET")
        if self.payments_enabled:
            p = self.pay_to
            if not (p.startswith("0x") and len(p) == 42):
                raise ValueError("LEDGER_PAY_TO must be the 0x wallet address that receives payments")

    @property
    def network(self) -> dict:
        return NETWORKS[self.network_key]
