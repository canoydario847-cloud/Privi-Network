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
    "privi_verify_lot": "0.01",
    "privi_chain_of_custody": "0.05",
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
    db_path: str = "privi.db"
    payments_enabled: bool = True
    network_key: str = "base-sepolia"
    pay_to: str = ""
    facilitator_url: str = "https://x402.org/facilitator"
    facilitator_auth: str = ""          # optional "Authorization" header value
    prices_usd: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_PRICES_USD))
    write_keys: set[str] = field(default_factory=set)
    public_url: str = ""

    @classmethod
    def from_env(cls) -> "Settings":
        s = cls(
            db_path=os.getenv("PRIVI_DB_PATH", "privi.db"),
            payments_enabled=_bool("PRIVI_PAYMENTS_ENABLED", True),
            network_key=os.getenv("PRIVI_NETWORK", "base-sepolia"),
            pay_to=os.getenv("PRIVI_PAY_TO", "").strip(),
            facilitator_url=os.getenv("PRIVI_FACILITATOR_URL", "https://x402.org/facilitator").rstrip("/"),
            facilitator_auth=os.getenv("PRIVI_FACILITATOR_AUTH", ""),
            write_keys={k.strip() for k in os.getenv("PRIVI_WRITE_KEYS", "").split(",") if k.strip()},
            public_url=os.getenv("PRIVI_PUBLIC_URL", "").rstrip("/"),
        )
        for tool in DEFAULT_PRICES_USD:
            env = f"PRIVI_PRICE_{tool.removeprefix('privi_').upper()}"
            if os.getenv(env):
                s.prices_usd[tool] = os.environ[env]
        s.validate()
        return s

    def validate(self) -> None:
        if self.network_key not in NETWORKS:
            raise ValueError(f"PRIVI_NETWORK must be one of {list(NETWORKS)}")
        for usd in self.prices_usd.values():
            usd_to_atomic(usd)
        if self.payments_enabled:
            p = self.pay_to
            if not (p.startswith("0x") and len(p) == 42):
                raise ValueError("PRIVI_PAY_TO must be the 0x wallet address that receives payments")

    @property
    def network(self) -> dict:
        return NETWORKS[self.network_key]
