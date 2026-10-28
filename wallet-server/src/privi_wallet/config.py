"""Settings for Privi Wallet, read from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal

# PRIVI on Base (same contract the Privi services accept; see mcp-server/src/privi_verify/privi_token.py).
PRIVI_TOKEN = "0xa11626baf87524e61b5697634c7ec48d26279d6c"
USDC_TOKEN = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"


def _flag(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def _dec(name: str, default: str) -> Decimal:
    return Decimal(os.getenv(name, default).strip() or default)


@dataclass
class Settings:
    db_path: str = field(default_factory=lambda: os.getenv("WALLET_DB_PATH", "wallet.db"))
    public_url: str = field(default_factory=lambda: os.getenv("WALLET_PUBLIC_URL", "https://privi-wallet.onrender.com"))
    # Custodial wallets (Privi holds the keys) stay OFF until this is set to 1 on purpose.
    custody: bool = field(default_factory=lambda: _flag("WALLET_CUSTODY"))
    # Secret that encrypts every stored private key. Losing it means losing every custodial wallet: back it up.
    master_key: str = field(default_factory=lambda: os.getenv("WALLET_MASTER_KEY", ""))
    rpc_url: str = field(default_factory=lambda: os.getenv("WALLET_RPC_URL", "https://mainnet.base.org"))
    chain_id: int = field(default_factory=lambda: int(os.getenv("WALLET_CHAIN_ID", "8453")))
    explorer: str = field(default_factory=lambda: os.getenv("WALLET_EXPLORER", "https://basescan.org"))
    ledger_url: str = field(default_factory=lambda: os.getenv("WALLET_LEDGER_URL", "https://privi-ledger.onrender.com"))
    # Per-account limits on what can leave a custodial wallet in any rolling 24 hours.
    max_send_privi: Decimal = field(default_factory=lambda: _dec("WALLET_MAX_SEND_PRIVI_24H", "100000"))
    max_send_usdc: Decimal = field(default_factory=lambda: _dec("WALLET_MAX_SEND_USDC_24H", "500"))
    max_send_eth: Decimal = field(default_factory=lambda: _dec("WALLET_MAX_SEND_ETH_24H", "0.1"))
    max_wallets: int = field(default_factory=lambda: int(os.getenv("WALLET_MAX_PER_ACCOUNT", "3")))
    secure_cookies: bool = field(default_factory=lambda: _flag("WALLET_SECURE_COOKIES", "1"))

    def custody_ready(self) -> bool:
        return self.custody and len(self.master_key) >= 32

    def limit(self, asset: str) -> Decimal:
        return {"PRIVI": self.max_send_privi, "USDC": self.max_send_usdc, "ETH": self.max_send_eth}[asset]
