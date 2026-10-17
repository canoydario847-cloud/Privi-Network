#!/usr/bin/env python3
"""Read-only Privi validator COLD RECOVERY evidence preflight.

Does NOT restore keys, copy last-sign state, connect to RPC, start a signer,
approve a financial mainnet, or prove that the original machine was fenced.
Requires independent operator-authenticated *assertions* and a local signer
state that has NOT rolled back below the operator's signed checkpoint.

An operator signature proves the signer made a statement. It cannot prove
the original host is actually powered off or HSM credentials revoked.
Physical/administrative fencing MUST be independently checked before any
production signer is launched. This program never authorizes that launch.
"""
import argparse
import base64
import binascii
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

MAX_JSON_BYTES = 65536
MAX_AGE = timedelta(hours=24)
# Public statement; no private signing bytes, mnemonic, seed or HSM material.
FIELDS = frozenset({
    "schema_version", "status", "operator_id", "cosmos_chain_id",
    "genesis_sha256", "consensus_pubkey_b64",
    "minimum_sign_state", "original_signer_fenced_claim",
    "remote_signer_fenced_claim", "created_at", "expires_at", "nonce"
})
STATUS = "COLD_RECOVERY_OPERATOR_ATTESTATION_NO_AUTOMATIC_START"


def strict_json_file(path, *, sensitive=False):
    file = Path(path)
    if file.is_symlink() or not file.is_file():
        raise ValueError("Recovery input must be a regular, non-symlink file")
    mode = file.stat().st_mode
    if not stat.S_ISREG(mode):
        raise ValueError("Recovery input must be a regular file")
    if sensitive and mode & 0o077:
        raise ValueError("Sensitive validator file must be readable/writable only by its owner")
    if file.stat().st_size <= 0 or file.stat().st_size > MAX_JSON_BYTES:
        raise ValueError("Recovery input outside safe JSON size bounds")
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Malformed recovery JSON input") from exc
    if not isinstance(data, dict):
        raise ValueError("Recovery input JSON object required")
    return data


def state_tuple(payload):
    """Strict, canonical nonnegative Comet last-sign height/round/step."""
    if not isinstance(payload, dict):
        raise ValueError("Missing validator signing-state object")
    result = []
    for field in ("height", "round", "step"):
        value = payload.get(field)
        if type(value) not in (int, str) or not re.fullmatch(r"(0|[1-9]\d{0,17})", str(value)):
            raise ValueError("Invalid last-sign " + field)
        result.append(int(value))
    return tuple(result)


def decode_pub(value):
    if type(value) is not str:
        raise ValueError("Expected Ed25519 public key")
    try:
        key = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("Malformed Ed25519 public key encoding") from exc
    if len(key) != 32:
        raise ValueError("Ed25519 consensus public key must be 32 bytes")
    return key


def parse_time(value):
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("Timestamp must be UTC RFC3339 with Z suffix")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Malformed signed recovery time") from exc


def signature_bytes(value):
    if not isinstance(value, str):
        raise ValueError("Missing recovery Ed25519 signature")
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("Malformed recovery signature") from exc
    if len(raw) != 64:
        raise ValueError("Recovery signature must be 64 bytes")
    return raw


def canonical(message):
    return json.dumps(message, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def verify_signed_statement(bundle, trusted_operator_key, *, now=None):
    if not isinstance(bundle, dict) or set(bundle) != {"statement", "signature_b64"}:
        raise ValueError("Expected signed recovery statement and detached signature")
    message = bundle["statement"]
    if not isinstance(message, dict) or set(message) != FIELDS:
        raise ValueError("Unknown or missing recovery attestation fields")
    if message.get("schema_version") != 1 or message.get("status") != STATUS:
        raise ValueError("Only review-only recovery attestations are supported")
    if message.get("original_signer_fenced_claim") is not True or message.get("remote_signer_fenced_claim") is not True:
        raise ValueError("Fencing and remote-signer disabling assertions required")
    nonce = message.get("nonce")
    if not isinstance(nonce, str) or not re.fullmatch(r"[0-9a-f]{32,64}", nonce):
        raise ValueError("Recovery statement must include a fresh random nonce")
    if not isinstance(message.get("operator_id"), str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{2,63}", message["operator_id"]):
        raise ValueError("Operator ID missing or malformed")
    chain = message.get("cosmos_chain_id")
    if not isinstance(chain, str) or not re.fullmatch(r"[a-z][a-z0-9-]{2,63}", chain):
        raise ValueError("Invalid recovery chain ID")
    if not isinstance(message.get("genesis_sha256"), str) or not re.fullmatch(r"[a-f0-9]{64}", message["genesis_sha256"]):
        raise ValueError("Invalid signed genesis digest")
    decode_pub(message.get("consensus_pubkey_b64"))
    state_tuple(message.get("minimum_sign_state"))
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("Verifier requires timezone-aware reference time")
    start, expiry = parse_time(message.get("created_at")), parse_time(message.get("expires_at"))
    if expiry <= start or expiry - start > MAX_AGE or start > current or current >= expiry:
        raise ValueError("Recovery attestation expired, not yet active, or over 24 hours old")
    if not isinstance(trusted_operator_key, bytes) or len(trusted_operator_key) != 32:
        raise ValueError("Trusted operator Ed25519 key must be 32 bytes")
    try:
        Ed25519PublicKey.from_public_bytes(trusted_operator_key).verify(
            signature_bytes(bundle["signature_b64"]), canonical(message))
    except InvalidSignature as exc:
        raise ValueError("Operator recovery attestation signature invalid") from exc
    return message


def check_recovery(home, bundle, trusted_operator_key, *,
                   trusted_chain_id, trusted_consensus_key, now=None):
    """Read-only check. PASS means documentation consistency, NOT safe-to-start."""
    if not isinstance(trusted_chain_id, str) or not trusted_chain_id:
        raise ValueError("Trusted independent chain ID required")
    if not isinstance(trusted_consensus_key, bytes) or len(trusted_consensus_key) != 32:
        raise ValueError("Trusted independent validator consensus key required")
    message = verify_signed_statement(bundle, trusted_operator_key, now=now)
    if trusted_chain_id != message["cosmos_chain_id"]:
        raise ValueError("Trusted chain differs from signed recovery statement")
    if decode_pub(message["consensus_pubkey_b64"]) != trusted_consensus_key:
        raise ValueError("Trusted validator consensus key differs from signed record")

    home = Path(home)
    cfg = home / "config"
    if home.is_symlink() or cfg.is_symlink() or (home / "data").is_symlink():
        raise ValueError("Signer directory symlinks forbidden")
    genesis_path = cfg / "genesis.json"
    genesis = strict_json_file(genesis_path)
    if genesis.get("chain_id") != trusted_chain_id:
        raise ValueError("Restored genesis chain ID is not reviewed chain")
    expected = hashlib.sha256(genesis_path.read_bytes()).hexdigest()
    if expected != message["genesis_sha256"]:
        raise ValueError("Restored genesis hash differs from signed original")

    keydata = strict_json_file(cfg / "priv_validator_key.json", sensitive=True)
    pub = keydata.get("pub_key")
    if not isinstance(pub, dict) or pub.get("type") not in ("tendermint/PubKeyEd25519", "cometbft/PubKeyEd25519"):
        raise ValueError("Restored validator signing key has incorrect curve/type")
    if decode_pub(pub.get("value")) != trusted_consensus_key:
        raise ValueError("Restored signer does not match trusted public consensus key")

    statefile = home / "data" / "priv_validator_state.json"
    sign_state = state_tuple(strict_json_file(statefile, sensitive=True))
    signed_minimum = state_tuple(message["minimum_sign_state"])
    if sign_state < signed_minimum:
        raise ValueError("Stale signing state: potential double-sign; restore is blocked")
    return {
        "status": "OFFLINE_RECOVERY_EVIDENCE_CHECK_PASSED_NOT_AUTHORIZED_TO_START",
        "operator_id": message["operator_id"],
        "chain_id": trusted_chain_id,
        "validated_original_public_consensus_key": True,
        "matched_genesis_digest": True,
        "non_decreasing_last_sign_state": True,
        "operator_fencing_claim_signature_verified": True,
        "physical_fencing_independently_verified": False,
        "remote_signer_shutdown_independently_verified": False,
        "validator_start_authorized": False,
        "financial_mainnet_activated": False,
    }


def main():
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument("--home", type=Path, required=True, help="Offline validator home. Never a running signer.")
    a.add_argument("--signed-assertion", type=Path, required=True, help="Public operator-signed JSON statement")
    a.add_argument("--trusted-operator-ed25519-hex", required=True,
                   help="Trusted operator public key obtained from independent registry")
    a.add_argument("--trusted-consensus-ed25519-hex", required=True,
                   help="Trusted validator consensus key from independent roster")
    a.add_argument("--trusted-chain-id", required=True)
    opts = a.parse_args()
    try:
        operator_key = bytes.fromhex(opts.trusted_operator_ed25519_hex)
        consensus_key = bytes.fromhex(opts.trusted_consensus_ed25519_hex)
        bundle = strict_json_file(opts.signed_assertion)
        result = check_recovery(opts.home, bundle, operator_key,
                                trusted_chain_id=opts.trusted_chain_id,
                                trusted_consensus_key=consensus_key)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        a.exit(1, "PRVI COLD RECOVERY BLOCKED: " + str(exc) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
