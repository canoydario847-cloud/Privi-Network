#!/usr/bin/env python3
"""PRVI launch readiness scorecard — always fail-closed for financial mainnet.

Reports engineering progress toward the eight launch gates without granting GO.
Exit codes:
  0 = scorecard ran; financial mainnet still NO-GO (expected)
  2 = scorecard itself could not run or research markers broken
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# File lives at production-network/ops/launch_readiness_scorecard.py
REPO = Path(__file__).resolve().parents[2]

GATES = [
    ("1_chain_identity_binary", "Chain identity and binary"),
    ("2_genesis_supply", "Genesis and supply"),
    ("3_independent_validators", "Independent validators"),
    ("4_public_testnet_ci", "Public testnet and CI"),
    ("5_security", "Security"),
    ("6_operations", "Operations"),
    ("7_legal_comms", "Legal and communications"),
    ("8_final_approval", "Final approval"),
]


def exists(*parts: str) -> bool:
    return REPO.joinpath(*parts).is_file()


def engineering_artifacts() -> dict:
    """Files that show build progress — not gate evidence."""
    return {
        "pop_engine": exists("production-network/mainnet/pop_candidate/engine.cjs"),
        "pop_round_machine": exists("production-network/mainnet/pop_candidate/round_machine.cjs"),
        "pop_message_bus": exists("production-network/mainnet/pop_candidate/message_bus.cjs"),
        "pop_worker_bus": exists("production-network/mainnet/pop_candidate/worker_bus.cjs"),
        "pop_research_ci": exists(".github/workflows/privi-pop-research-safety.yml"),
        "pop_mainnet_guard": exists("production-network/mainnet/pop_mainnet_guard.py"),
        "ops_mainnet_gate": exists("production-network/ops/mainnet_gate.py"),
        "launch_gate_doc": exists("production-network/ops/MAINNET_LAUNCH_GATE.md"),
        "genesis_worksheet": exists(
            "production-network/mainnet/GENESIS_ALLOCATION_WORKSHEET.json"
        ),
        "hardcap_requirements": exists(
            "production-network/ops/PRVI_HARDCAP_INTEGRATION_REQUIREMENTS.md"
        ),
        "validator_recovery_plan": exists(
            "production-network/ops/VALIDATOR_FAILURE_RECOVERY_TEST_PLAN.md"
        ),
        "path_to_launch": exists("production-network/ops/PATH_TO_LAUNCH.md"),
        "candidate_binary_pin": exists("production-network/ops/candidate_binary_pin.py"),
        "candidate_binary_pin_template": exists(
            "production-network/ops/candidate_binary_pin.UNPINNED.json"
        ),
    }


def research_markers_ok() -> list[str]:
    problems = []
    engine = REPO / "production-network/mainnet/pop_candidate/engine.cjs"
    if not engine.is_file():
        problems.append("engine.cjs missing")
        return problems
    text = engine.read_text(encoding="utf-8", errors="replace")
    if "attested-position-research-not-live-consensus" not in text:
        problems.append("engine.cjs missing research mode marker")
    compact = text.replace(" ", "")
    if "productionConsensus:false" not in compact:
        problems.append("engine.cjs missing productionConsensus:false")
    return problems


def gate_statuses(artifacts: dict) -> dict:
    if artifacts.get("candidate_binary_pin"):
        binary_note = (
            "Testnet pin verifier present; artifact SHA-256 still UNPINNED; "
            "not a production binary"
        )
    else:
        binary_note = "No pinned Privi-custom production binary"
    notes = {
        "1_chain_identity_binary": binary_note,
        "2_genesis_supply": (
            "Worksheet present but unfilled; offline cap model only"
            if artifacts.get("genesis_worksheet")
            else "Genesis worksheet missing"
        ),
        "3_independent_validators": "No production operator attestations",
        "4_public_testnet_ci": (
            "Research CI present; multi-host public testnet not evidenced"
            if artifacts.get("pop_research_ci")
            else "Research CI missing"
        ),
        "5_security": "No external audit package on pinned release",
        "6_operations": "Recovery plan doc only; no production ops evidence",
        "7_legal_comms": "Disclosures / launch counsel not recorded",
        "8_final_approval": "No GO signatures",
    }
    return {
        key: {"title": title, "status": "BLOCKED", "note": notes[key]}
        for key, title in GATES
    }


def main() -> int:
    if not (REPO / "production-network").is_dir():
        print("BLOCKED: cannot locate production-network/", file=sys.stderr)
        return 2

    artifacts = engineering_artifacts()
    marker_problems = research_markers_ok()
    gates = gate_statuses(artifacts)
    present = sum(1 for v in artifacts.values() if v)

    report = {
        "document": "PRVI_LAUNCH_READINESS_SCORECARD",
        "verdict": "NO_GO",
        "production_mainnet_activated": False,
        "financial_prvi_issued": False,
        "engineering_artifacts_present": present,
        "engineering_artifacts_total": len(artifacts),
        "engineering_artifacts": artifacts,
        "research_marker_problems": marker_problems,
        "gates": gates,
        "blocked_gate_count": len(gates),
        "message": (
            "Financial mainnet remains NO-GO. Engineering artifacts measure "
            "build progress only and never authorize activation."
        ),
    }
    print(json.dumps(report, indent=2))
    if marker_problems:
        print(
            "WARNING: research production markers incomplete: "
            + "; ".join(marker_problems),
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
