# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Call - https://priviflow.us - dariocanoy@priviflow.us
"""Settings for Privi Call, read from environment variables."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

# USDC on Base. Name/version are the token's EIP-712 domain, needed by x402 "exact".
NETWORKS = {
    "base-sepolia": {"network": "eip155:84532", "asset": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
                     "extra": {"name": "USDC", "version": "2"}},
    "base": {"network": "eip155:8453", "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
             "extra": {"name": "USD Coin", "version": "2"}},
}

# Privi's own agents. Calls to these are always free: they earn through their own paid tools.
DEFAULT_OFFICIAL = [
    {"number": "100", "name": "Privi Ledger", "endpoint": "https://privi-ledger.onrender.com/mcp",
     "description": "Tamper-evident audit logs, compliance reports, Passports, KYA, Mandates, Guard and government AI/PQC inventories for AI agents.",
     "tags": ["audit", "compliance", "identity", "payments"]},
    {"number": "101", "name": "Privi Verify", "endpoint": "https://privi-verify.onrender.com/mcp",
     "description": "Manufacturing lot verification and chain of custody, paid per call in USDC.",
     "tags": ["manufacturing", "supply chain", "traceability"]},
    {"number": "102", "name": "Privi Anchor", "endpoint": "https://privi-anchor.onrender.com/mcp",
     "description": "Hash anchoring and proof-of-existence on chain.",
     "tags": ["blockchain", "proof of existence", "timestamp"]},
    {"number": "103", "name": "Privi Quantum", "endpoint": "https://privi-quantum.onrender.com/mcp",
     "description": "Quantum optimization (CVaR-QAOA) for factory decisions with post-quantum signed results; quantum-vulnerable crypto scanner.",
     "tags": ["quantum", "optimization", "post-quantum"]},
]

# Rough per-unit costs Privi pays, used to show margin in the call log (USD).
PHONE_COST_PER_MIN = 0.0085   # Twilio inbound local voice
SPEECH_COST_PER_TURN = 0.02   # Twilio <Gather input="speech">


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
    db_path: str = "call.db"
    public_url: str = "https://privi-call.onrender.com"
    admin_key: str = ""
    # payments (x402, USDC on Base) for call credit packs
    payments_enabled: bool = True
    network_key: str = "base"
    pay_to: str = "0x1990589FD200E043b8C6FD9ec5956c61b3071048"
    facilitator_url: str = "https://api.cdp.coinbase.com/platform/v2/x402"
    facilitator_auth: str = ""
    cdp_key_id: str = ""
    cdp_key_secret: str = ""
    pack_price_usd: str = "1.00"
    pack_credits: int = 1000
    free_calls_per_day: int = 50
    rate_per_min: int = 120
    call_timeout: float = 30.0
    official: list[dict] = field(default_factory=lambda: [dict(a) for a in DEFAULT_OFFICIAL])
    # phone
    twilio_auth_token: str = ""
    voice_insecure: bool = False       # tests only: skip Twilio signature check
    forward_number: str = "+13134138532"
    phone_number: str = ""             # the public Privi line, shown on pages
    phone_trial: bool = False          # Twilio free trial: only verified numbers can call, so keep the number off public pages
    voice: str = "Polly.Matthew-Neural"
    llm_api_key: str = ""
    llm_model: str = "claude-haiku-5-5"
    # anchoring
    anchor_url: str = "https://privi-anchor.onrender.com/mcp"
    anchor_api_key: str = ""
    anchor_interval: int = 300

    @classmethod
    def from_env(cls) -> "Settings":
        s = cls()
        e = os.getenv
        s.db_path = e("CALL_DB_PATH", s.db_path)
        s.public_url = e("CALL_PUBLIC_URL", s.public_url).rstrip("/")
        s.admin_key = e("CALL_ADMIN_KEY", "")
        s.payments_enabled = _bool("CALL_PAYMENTS_ENABLED", True)
        s.network_key = e("CALL_NETWORK", s.network_key)
        s.pay_to = e("CALL_PAY_TO", s.pay_to).strip()
        s.facilitator_url = e("CALL_FACILITATOR_URL", s.facilitator_url).rstrip("/")
        s.facilitator_auth = e("CALL_FACILITATOR_AUTH", "")
        s.cdp_key_id = e("CDP_API_KEY_ID", "").strip().strip("\"'")
        s.cdp_key_secret = e("CDP_API_KEY_SECRET", "").strip().strip("\"'")
        s.pack_price_usd = e("CALL_PACK_PRICE_USD", s.pack_price_usd)
        s.pack_credits = int(e("CALL_PACK_CREDITS", str(s.pack_credits)))
        s.free_calls_per_day = int(e("CALL_FREE_PER_DAY", str(s.free_calls_per_day)))
        s.rate_per_min = int(e("CALL_RATE_PER_MIN", str(s.rate_per_min)))
        if e("CALL_OFFICIAL_AGENTS"):
            s.official = json.loads(e("CALL_OFFICIAL_AGENTS"))
        s.twilio_auth_token = e("TWILIO_AUTH_TOKEN", "").strip()
        s.voice_insecure = _bool("CALL_VOICE_INSECURE", False)
        s.forward_number = e("CALL_FORWARD_NUMBER", s.forward_number).strip()
        s.phone_number = e("CALL_PHONE_NUMBER", "").strip()
        s.phone_trial = _bool("CALL_PHONE_TRIAL", False)
        s.voice = e("CALL_VOICE", s.voice)
        s.llm_api_key = e("ANTHROPIC_API_KEY", "").strip()
        s.llm_model = e("CALL_LLM_MODEL", s.llm_model)
        s.anchor_url = e("CALL_ANCHOR_URL", s.anchor_url)
        s.anchor_api_key = e("CALL_ANCHOR_API_KEY", "").split(",")[0].strip()
        s.anchor_interval = int(e("CALL_ANCHOR_INTERVAL", str(s.anchor_interval)))
        usd_to_atomic(s.pack_price_usd)
        if s.network_key not in NETWORKS:
            raise ValueError(f"CALL_NETWORK must be one of {list(NETWORKS)}")
        return s

    # x402.Paywall reads these
    @property
    def network(self) -> dict:
        return NETWORKS[self.network_key]

    @property
    def prices_usd(self) -> dict[str, str]:
        return {"call_credits_buy": self.pack_price_usd}

    @property
    def payments_ready(self) -> bool:
        """True when credit packs can really be sold (never hands out free credits by mistake)."""
        if not self.payments_enabled:
            return False
        if not (self.pay_to.startswith("0x") and len(self.pay_to) == 42):
            return False
        if "api.cdp.coinbase.com" in self.facilitator_url and not (self.cdp_key_id and self.cdp_key_secret):
            return False
        if self.network_key == "base" and "x402.org" in self.facilitator_url:
            return False
        return True
