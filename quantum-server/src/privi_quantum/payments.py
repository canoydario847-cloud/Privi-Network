"""x402 payment settings for Privi Quantum (USDC on Base, optional PRIVI token).

Payments turn on when QUANTUM_PAY_TO is set (or QUANTUM_PAYMENTS_ENABLED=1). With them off, every
tool stays free, so an unconfigured deployment behaves exactly as before.

Paid tools (default prices, override with env):
  pqc_readiness_package    $5     QUANTUM_PRICE_READINESS
  pqc_crypto_inventory     $5     QUANTUM_PRICE_INVENTORY
  quantum_advantage_receipt $0.25 QUANTUM_PRICE_RECEIPT
  quantum_run_hardware     $1     QUANTUM_PRICE_HARDWARE   (routing fee; QPU cost stays inside the operator budget)
  genius_stablecoin_check  $0.01  QUANTUM_PRICE_GENIUS_CHECK

Every tool is paid (see DEFAULT_PRICES_USD). A person can still revoke a mandate on its web page with their passkey.
"""

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
    "pqc_readiness_package": "5",
    "pqc_crypto_inventory": "5",
    "quantum_advantage_receipt": "0.25",
    "quantum_run_hardware": "1",
    "genius_stablecoin_check": "0.01",
    # Every other tool is paid too (gated centrally in server.py). Reads $0.001, actions $0.01, certification $1.
    **{t: "0.001" for t in (
        "quantum_problems", "quantum_backends", "pqc_federal_deadlines", "quantum_mandate_status", "quantum_mandate_check",
        "qagent_directory", "qagent_status", "qagent_verify", "inspector_check", "inspector_status", "inspector_watchlist",
        "privilege_directory", "dreamscape_jobs", "quantum_benchmarks", "quantum_leaderboard", "inspector_grade",
        "quantum_verify")},
    **{t: "0.01" for t in (
        "pqc_scan_code", "pqc_endpoint_check", "quantum_optimize", "quantum_hardware_job", "quantum_mandate_request",
        "quantum_run_circuit", "vault_keygen", "vault_seal", "vault_open", "vault_receipt", "privilege_benchmark",
        "dreamweaver_run", "dreamscape_open", "dreamscape_submit", "qagent_scan", "qagent_challenge", "qagent_prove",
        "qagent_quantum_task", "qagent_quantum_proof", "inspector_pass", "inspector_report", "inspector_patrol",
        "qagent_human_request")},
    "qagent_enroll": "1",
    "quantum_pricing": "0.001", "quantum_status": "0.001", "accelerator_info": "0.001",
    "quantum_mandate_revoke": "0.01",
    # Privi Car (car_web.PRICES): reads $0.001, records $0.01, keys $0.05, plans $0.10-$0.25, passport $1, history $2.
    "car_info": "0.001", "car_vin_check": "0.001", "car_verify": "0.001", "car_key_check": "0.001",
    "car_record_add": "0.01", "car_key_revoke": "0.01", "car_edge_job": "0.01", "car_key_issue": "0.05",
    "car_charge_plan": "0.10", "car_route": "0.25", "car_fleet_assign": "0.25", "car_register": "1", "car_history": "2",
    # Privi Quantum Toolkit (toolkit.PRICES): planning tools $0.01-$0.05, signed supplier scorecard $1.
    "pqc_certificate_check": "0.05", "pqc_harvest_risk": "0.05", "pqc_size_impact": "0.01",
    "quantum_circuit_stats": "0.01", "pqc_supplier_score": "1",
}

# No tool is free. The x402 payment-required reply states each price, so agents can learn prices by calling.
ALWAYS_FREE: tuple[str, ...] = ()

PRICE_ENV = {
    "pqc_readiness_package": "QUANTUM_PRICE_READINESS",
    "pqc_crypto_inventory": "QUANTUM_PRICE_INVENTORY",
    "quantum_advantage_receipt": "QUANTUM_PRICE_RECEIPT",
    "quantum_run_hardware": "QUANTUM_PRICE_HARDWARE",
    "genius_stablecoin_check": "QUANTUM_PRICE_GENIUS_CHECK",
}

CDP_FACILITATOR = "https://api.cdp.coinbase.com/platform/v2/x402"


def usd_to_atomic(usd: str) -> str:
    """'0.01' -> '10000' (USDC has 6 decimals)."""
    whole, _, frac = usd.strip().partition(".")
    frac = (frac + "000000")[:6]
    value = int(whole or "0") * 1_000_000 + int(frac or "0")
    if value <= 0:
        raise ValueError(f"price must be positive: {usd}")
    return str(value)


@dataclass
class PaySettings:
    payments_enabled: bool = False
    network_key: str = "base"
    pay_to: str = ""
    facilitator_url: str = CDP_FACILITATOR
    facilitator_auth: str = ""
    cdp_key_id: str = ""
    cdp_key_secret: str = ""
    facilitator_ready: bool = True
    db_path: str = "quantum.db"
    prices_usd: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_PRICES_USD))

    @classmethod
    def from_env(cls, db_path: str = "quantum.db") -> "PaySettings":
        pay_to = os.getenv("QUANTUM_PAY_TO", "").strip()
        flag = os.getenv("QUANTUM_PAYMENTS_ENABLED")
        enabled = bool(pay_to) if flag is None else flag.strip().lower() in ("1", "true", "yes", "on")
        s = cls(
            payments_enabled=enabled,
            network_key=os.getenv("QUANTUM_NETWORK", "base"),
            pay_to=pay_to,
            facilitator_url=os.getenv("QUANTUM_FACILITATOR_URL", CDP_FACILITATOR).rstrip("/"),
            facilitator_auth=os.getenv("QUANTUM_FACILITATOR_AUTH", ""),
            cdp_key_id=os.getenv("CDP_API_KEY_ID", "").strip().strip("\"'"),
            cdp_key_secret=os.getenv("CDP_API_KEY_SECRET", "").strip().strip("\"'"),
            db_path=db_path,
        )
        for tool, env in PRICE_ENV.items():
            if os.getenv(env):
                s.prices_usd[tool] = os.environ[env].strip()
        _toolkit = ("pqc_certificate_check", "pqc_harvest_risk", "pqc_size_impact", "quantum_circuit_stats", "pqc_supplier_score")
        for tool in [t for t in s.prices_usd if t.startswith("car_") or t in _toolkit]:      # QUANTUM_PRICE_CAR_ROUTE=0.5, ...
            env = "QUANTUM_PRICE_" + tool.upper()
            if os.getenv(env):
                s.prices_usd[tool] = os.environ[env].strip()
        s.validate()
        return s

    def validate(self) -> None:
        if self.network_key not in NETWORKS:
            raise ValueError(f"QUANTUM_NETWORK must be one of {list(NETWORKS)}")
        for usd in self.prices_usd.values():
            usd_to_atomic(usd)
        if not self.payments_enabled:
            return
        p = self.pay_to
        if not (p.startswith("0x") and len(p) == 42):
            raise ValueError("QUANTUM_PAY_TO must be a 0x... Base address")
        if self.network_key == "base" and "x402.org" in self.facilitator_url:
            raise ValueError("Base mainnet needs a production facilitator (the Coinbase CDP facilitator)")
        if "api.cdp.coinbase.com" in self.facilitator_url and not (self.cdp_key_id and self.cdp_key_secret):
            # Preserve payments_enabled, but never execute or settle an unverified call.
            # Let public health and the separately authenticated quantum cloud boot.
            self.facilitator_ready = False

    @property
    def network(self) -> dict:
        return NETWORKS[self.network_key]

    def price_table(self) -> dict[str, str]:
        if not self.payments_enabled:
            return {t: "free (payments not configured on this server)" for t in self.prices_usd}
        return {t: f"${p} USDC per call (x402, Base)" for t, p in self.prices_usd.items()}
