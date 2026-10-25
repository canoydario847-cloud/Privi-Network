#!/usr/bin/env python3
"""Research-only ECI wage reference for PRVI; NEVER a price peg or mint instruction."""
from decimal import Decimal, InvalidOperation
import argparse
import json

BASE_SUPPLY = 1_000_000_000

def payroll_reference(base_eci: str, observed_eci: str, base_usd: str = "1") -> dict:
    """Calculate a USD reference target, without changing tokens or promising redemption."""
    try:
        base, current, price = map(Decimal, (base_eci, observed_eci, base_usd))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("ECI and USD values must be decimal numbers") from exc
    if any(not x.is_finite() or x <= 0 for x in (base, current, price)):
        raise ValueError("ECI and reference USD values must be positive finite decimals")
    return {
        "status": "research-only-unbacked-reference",
        "target_usd_per_prvi": str(price * current / base),
        "max_native_prvi_supply": BASE_SUPPLY,
        "mint_authorized": False,
        "redemption_guaranteed": False,
        "source": "BLS Employment Cost Index, wages and salaries; values supplied by operator",
    }

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-eci", required=True)
    parser.add_argument("--observed-eci", required=True)
    parser.add_argument("--base-usd", default="1")
    args = parser.parse_args()
    print(json.dumps(payroll_reference(args.base_eci, args.observed_eci, args.base_usd), indent=2))
