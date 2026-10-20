#!/usr/bin/env python3
"""Deterministic Privi Point of Position (PoP) ledger-position accounting.

Source: Dario Canoy's 2026 Point of Position research paper:
  F = min(1, reports / 50)
  T = min(1, verified_days / 365)
  L = 1 + (0.6 F + 0.4 T) * 1.5

This module uses exact integer basis points, not floating-point consensus
arithmetic. Proposed micro-PRVI positions are test-only *units of account*,
NEVER price, a financial claim, token mint, consensus, staking or payout.

Native Privi-only: no BTC/ETH/BSC oracle, foreign ledger or pairing.
"""
import hashlib
import re

POP_ZONES = {
    "GRID/READINGS": 1200,
    "FLEET/ASSETS": 1600,
    "ENERGY/READINGS": 1400,
    "IOT/GENERAL": 1000,
    "ASSETS/VALUE": 2000,
}
COMPANY = re.compile(r"^[A-Z0-9_-]{1,24}$")
HEX = re.compile(r"^0x[0-9a-fA-F]{64}$")


def stamp(company_id: str, zone: str, sequence: int) -> str:
    if not isinstance(company_id, str) or COMPANY.fullmatch(company_id) is None:
        raise ValueError("PoP company ID invalid")
    if zone not in POP_ZONES:
        raise ValueError("Privi PoP zone invalid")
    if not isinstance(sequence, int) or isinstance(sequence, bool) or not 1 <= sequence <= 2**53 - 1:
        raise ValueError("PoP sequence invalid")
    return f"PoP:{company_id}:{zone}:{sequence:06d}"


def hash_text(value: str) -> str:
    return "0x" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def position(packet: dict) -> dict:
    name = stamp(packet.get("companyId"), packet.get("popZone"), packet.get("sequence"))
    return {
        "pop_stamp": name,
        "pop_stamp_hash": hash_text(name),
        "pop_zone": packet["popZone"],
        "pop_zone_hash": hash_text(packet["popZone"]),
        "company_id_hash": hash_text(packet["companyId"]),
    }


def leverage_bps(sealed_reports: int, chain_days: int) -> int:
    if not all(isinstance(i, int) and not isinstance(i, bool) and 0 <= i <= 2**53 - 1
               for i in (sealed_reports, chain_days)):
        raise ValueError("PoP counts and days must be nonnegative bounded integers")
    # L_bps = 10_000 + 9_000 * F + 6_000 * T.
    return (
        10000
        + (9000 * min(50, sealed_reports)) // 50
        + (6000 * min(365, chain_days)) // 365
    )


def proposal(zone: str, sealed_reports: int, chain_days: int) -> dict:
    if zone not in POP_ZONES:
        raise ValueError("Unknown Privi PoP zone")
    bps = leverage_bps(sealed_reports, chain_days)
    micro = POP_ZONES[zone] * bps // 10000
    return {
        "pop_protocol": "Point of Position",
        "pop_consensus_status": "NOT_IMPLEMENTED_IN_CURRENT_COSMOS_EVM",
        "pop_verified": True,  # only populated after a verified Privi receipt
        "pop_sealed_reports": sealed_reports,
        "pop_duration_days": chain_days,
        "pop_leverage_basis_points": bps,
        "pop_zone_base_micro_prvi": POP_ZONES[zone],
        "proposed_micro_prvi": micro,
        "proposed_prvi": f"{micro / 1_000_000:.6f}",
        "valuation_status": "PROPOSAL_ONLY_NOT_MINTED",
    }
