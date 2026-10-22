"""Read-only Privi cross-chain asset discovery; NO unverified token swaps.

AI provider APIs are not blockchains. An unaffiliated token using an AI brand
name is NOT that vendor's official payment asset. No bridge contracts,
custody, token approvals or execution endpoints are enabled here.
"""
import json
import os
import re

PROVIDER_STATUS = [
    {"ai": "chatgpt", "provider": "OpenAI", "type": "AI API",
     "official_crypto_token_verified": False, "network_bridge_supported": False},
    {"ai": "claude", "provider": "Anthropic", "type": "AI API",
     "official_crypto_token_verified": False, "network_bridge_supported": False},
    {"ai": "grok", "provider": "xAI", "type": "AI API",
     "official_crypto_token_verified": False, "network_bridge_supported": False},
    {"ai": "hey-jose", "provider": "Privi World Co", "type": "Privi AI service",
     "official_crypto_token_verified": False, "network_bridge_supported": False},
]

HEX_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")


def validated_assets():
    """Optional read-only operator allowlist; never infer identity from ticker."""
    raw = os.getenv("PRIVI_REVIEWED_ASSETS_JSON", "[]")
    try:
        assets = json.loads(raw)
    except ValueError:
        return []
    if not isinstance(assets, list) or len(assets) > 25:
        return []
    result = []
    seen = set()
    for a in assets:
        if not isinstance(a, dict):
            return []  # fail closed on malformed data
        symbol = a.get("symbol")
        chain = a.get("chain_id")
        address = a.get("contract")
        decimals = a.get("decimals")
        if (not isinstance(symbol, str) or not re.fullmatch("[A-Z0-9]{2,12}", symbol)
            or type(chain) is not int or chain <= 0
            or type(decimals) is not int or not (0 <= decimals <= 36)
            or not isinstance(address, str) or not HEX_ADDRESS.fullmatch(address)
            or int(address, 16) == 0):
            return []
        ident = (chain, address.lower())
        if ident in seen:
            return []
        seen.add(ident)
        result.append({
            "id": f"evm:{chain}:{address.lower()}",
            "symbol": symbol, "chain_id": chain,
            "contract": address.lower(), "decimals": decimals,
            "type": "erc20", "reviewed": True,
            "swap_enabled": False, "provider_affiliation": "not_asserted"
        })
    return result


def inventory(native_config=None):
    """Registry is display-only. No route quotation or token balance assumptions."""
    native = None
    if native_config:
        chain_id, _rpc, _treasury, _unit, _conf, _genesis = native_config
        native = {"id": f"native-prvi:{chain_id}", "symbol": "PRVI",
                  "chain_id": chain_id, "type": "native",
                  "contract": None, "swap_enabled": False,
                  "production_payment_configured": True,
                  "provider_affiliation": "privi"}
    return {"privi": native or {"id": "native-prvi:unverified", "symbol": "PRVI",
                    "type": "native", "swap_enabled": False,
                    "production_payment_configured": False},
            "reviewed_assets": validated_assets(),
            "agent_providers": PROVIDER_STATUS,
            "routes": [],
            "bridge_live": False, "swap_live": False,
            "warning": ("No audited PRVI cross-chain bridge or exchange routes are configured. "
                        "Third-party AI-themed tokens are not automatically official vendor tokens. "
                        "No transaction should be signed for a simulated route.")}
