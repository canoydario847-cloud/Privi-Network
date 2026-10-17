#!/usr/bin/env python3
"""Read-only seven-validator consensus + EVM PRVI rehearsal proof.

Run only from a vetted private read-only RPC gateway against VALueless rehearsal.
Never transfers coins, runs signing keys, enables public RPC, or launches mainnet.
"""
import argparse
import json
from pathlib import Path
import sys

TESTNET = Path(__file__).resolve().parents[1] / "testnet"
sys.path.insert(0, str(TESTNET))
from consensus_audit import audit, get, validator_set
from evm_smoke import RPC, check as check_evm


def proof(urls, cosmos_chain_id, evm_url, evm_chain_id):
    if len(urls) != 7 or len(set(urls)) != 7:
        raise ValueError("Exactly seven unique validator RPC endpoints required")
    if not isinstance(cosmos_chain_id, str) or not cosmos_chain_id.startswith("privi-"):
        raise ValueError("unapproved Cosmos chain ID")
    if type(evm_chain_id) is not int or evm_chain_id in (1, 56, 97, 4221, 262144, 31337):
        raise ValueError("demo or invalid EVM ID is prohibited")
    outcome = audit(urls, expected=cosmos_chain_id)
    if outcome["nodes"] != 7 or outcome["votingValidators"] != 7:
        raise ValueError("Expected seven unique live voting validators")
    height = outcome["blockHeight"]
    powers = validator_set(urls[0], height)
    if len(powers) != 7:
        raise ValueError("Unexpected validator set")
    if any(3 * power >= sum(powers.values()) for power in powers.values()):
        raise ValueError("A validator has >=1/3 voting power")
    commit = get(urls[0], f"/commit?height={height}")["signed_header"]["commit"]
    signers = {sig.get("validator_address", "").upper()
               for sig in commit["signatures"]
               if str(sig.get("block_id_flag")) in ("2", "BLOCK_ID_FLAG_COMMIT")
               and sig.get("signature")}
    if len(signers.intersection(powers)) != 7:
        raise ValueError("All seven must sign the same reviewed block")
    evm = check_evm(RPC(evm_url), expected=evm_chain_id)
    if evm["blockHeight"] < height - 10:
        raise ValueError("EVM JSON-RPC height lags too far behind CometBFT")
    return {
        "status": "TECHNICAL_REHEARSAL_EVIDENCE_ONLY_NOT_RELEASE_APPROVAL",
        "cosmos": outcome,
        "evm": evm,
        "all_seven_commit_signatures_present": True,
        "not_testnet": cosmos_chain_id != "local-privi-seven-4221",
        "limitations": [
            "RPC responses are observed evidence; they are not cryptographic proof of operator independence",
            "Source code audits, economics, restoration, slashing and governance drills are separate gates",
            "Passing does NOT deploy or authorize financial mainnet"
        ],
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--rpc", action="append", default=[], help="Seven private CometBFT read-only RPC URLs")
    p.add_argument("--cosmos-chain-id", required=True)
    p.add_argument("--evm-rpc", required=True)
    p.add_argument("--evm-chain-id", type=int, required=True)
    p.add_argument("--out", type=Path, help="New proof JSON file; never overwrites existing evidence")
    a = p.parse_args()
    try:
        result = proof(a.rpc, a.cosmos_chain_id, a.evm_rpc, a.evm_chain_id)
        blob = json.dumps(result, sort_keys=True, indent=2) + "\n"
        if a.out:
            with a.out.open("x", encoding="utf-8") as target:
                target.write(blob)
        else:
            print(blob, end="")
        return 0
    except Exception as exc:
        print("REHEARSAL NOT VERIFIED: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
