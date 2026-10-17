#!/usr/bin/env python3
"""Verify proposed consensus identities against independent public operator roster.

Supported Cosmos genesis inputs:
 A. CometBFT genesis.validators with Ed25519 consensus public keys/power.
 B. Cosmos SDK genutil.gen_txs MsgCreateValidator messages with Ed25519 public
    consensus keys, self-delegated aprvi and nonempty transaction signatures.

Does NOT cryptographically verify gentx signatures, beneficial ownership,
staking initial state, actual InitChain validator updates, or release signatures.
Those are mandatory external review and runtime launch checks.

Never creates keys, signs, funds, transfers, connects to RPC, or deploys nodes.
"""
import base64
import binascii
import re


def decode_key(value):
    """Return exact 32-byte Ed25519 raw public key or raise ValueError."""
    if not isinstance(value, str) or not value:
        raise ValueError("missing Ed25519 consensus key")
    try:
        if re.fullmatch(r"[a-fA-F0-9]{64}", value):
            key = bytes.fromhex(value)
        else:
            key = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("invalid consensus key encoding") from exc
    if len(key) != 32:
        raise ValueError("consensus key must decode to 32 bytes")
    return key


def read_public_key(candidate):
    """Read Cosmos / Comet Ed25519 JSON public key; other curves blocked."""
    if not isinstance(candidate, dict):
        raise ValueError("missing public consensus key object")
    kind = candidate.get("@type") or candidate.get("type")
    if kind not in ("/cosmos.crypto.ed25519.PubKey", "tendermint/PubKeyEd25519",
                    "cometbft/PubKeyEd25519"):
        raise ValueError("consensus public key must be Ed25519")
    raw = candidate.get("key", candidate.get("value"))
    return decode_key(raw)


def canonical_integer(value, positive=True):
    if type(value) not in (str, int):
        raise ValueError("voting power/amount must be exact decimal integer")
    raw = str(value)
    if not re.fullmatch(r"(0|[1-9][0-9]*)", raw) or len(raw) > 42:
        raise ValueError("noncanonical or excessively large integer")
    parsed = int(raw)
    if positive and parsed == 0:
        raise ValueError("voting power/delegation must be positive")
    return parsed


def parse_comet_validators(genesis):
    vals = genesis.get("validators", [])
    if not isinstance(vals, list):
        raise ValueError("Comet validators must be an array")
    pairs = {}
    for i, row in enumerate(vals):
        if not isinstance(row, dict):
            raise ValueError(f"Comet validator {i} invalid")
        key = read_public_key(row.get("pub_key"))
        power = canonical_integer(row.get("power"))
        if key in pairs:
            raise ValueError("duplicate consensus key in Comet genesis validators")
        pairs[key] = power
    return pairs


def parse_gentxs(genesis):
    state = genesis.get("app_state")
    if not isinstance(state, dict):
        raise ValueError("genesis app_state missing")
    genutil = state.get("genutil")
    if genutil is None:
        return {}
    if not isinstance(genutil, dict) or not isinstance(genutil.get("gen_txs"), list):
        raise ValueError("genutil.gen_txs must be an array")
    pairs = {}
    for i, tx in enumerate(genutil["gen_txs"]):
        if not isinstance(tx, dict):
            raise ValueError(f"gentx {i} malformed")
        body, auth, sigs = tx.get("body"), tx.get("auth_info"), tx.get("signatures")
        if not isinstance(body, dict) or not isinstance(auth, dict):
            raise ValueError(f"gentx {i} is missing body/auth_info")
        if not isinstance(sigs, list) or not sigs:
            raise ValueError(f"gentx {i} is not signed")
        for signature in sigs:
            if not isinstance(signature, str):
                raise ValueError(f"gentx {i} has invalid signature")
            try:
                raw = base64.b64decode(signature, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise ValueError(f"gentx {i} has malformed signature") from exc
            if len(raw) < 64:
                raise ValueError(f"gentx {i} signature too short")
        messages = body.get("messages")
        if not isinstance(messages, list) or len(messages) != 1:
            raise ValueError(f"gentx {i} must contain exactly one MsgCreateValidator")
        msg = messages[0]
        if not isinstance(msg, dict) or msg.get("@type") != "/cosmos.staking.v1beta1.MsgCreateValidator":
            raise ValueError(f"gentx {i} must be MsgCreateValidator")
        key = read_public_key(msg.get("pubkey", msg.get("pub_key")))
        val_addr = msg.get("validator_address")
        if not isinstance(val_addr, str) or not val_addr.startswith("privivaloper1"):
            raise ValueError(f"gentx {i} has wrong native validator prefix")
        value = msg.get("value")
        if not isinstance(value, dict) or value.get("denom") != "aprvi":
            raise ValueError(f"gentx {i} must self-delegate native aprvi")
        canonical_integer(value.get("amount"))
        if key in pairs:
            raise ValueError("duplicate consensus key across genesis gentxs")
        if val_addr in pairs.values():
            raise ValueError("duplicate valoper address across genesis gentxs")
        pairs[key] = val_addr
    return pairs


def validate_binding(genesis, roster):
    """Return errors (fail-closed), never supply missing operator identities."""
    errors = []
    if not isinstance(genesis, dict) or not isinstance(roster, dict):
        return ["Final genesis and independent roster must both be JSON objects"]
    rows = roster.get("operators")
    if not isinstance(rows, list) or len(rows) < 7:
        return ["At least seven independent real operators are required"]
    reviewed = {}
    powers = {}
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append(f"operator row {i} malformed")
            continue
        try:
            key = decode_key(row.get("consensus_pubkey"))
            power = canonical_integer(row.get("voting_power"))
            if key in reviewed:
                raise ValueError("same consensus key assigned to multiple operators")
            reviewed[key] = row.get("operator_id")
            powers[key] = power
        except ValueError as exc:
            errors.append(f"operator row {i}: {exc}")
    if len(reviewed) != len(rows):
        errors.append("Independent operator roster has missing/duplicate consensus keys")
    try:
        comet = parse_comet_validators(genesis)
    except ValueError as exc:
        comet = {}
        errors.append(f"Invalid Comet genesis validator set: {exc}")
    try:
        gentxs = parse_gentxs(genesis)
    except ValueError as exc:
        gentxs = {}
        errors.append(f"Invalid SDK genesis gentxs: {exc}")
    if not comet and not gentxs:
        errors.append("No Comet genesis validators or signed staking gentxs: genesis not deployable")
    if comet and set(comet) != set(reviewed):
        errors.append("Comet initial consensus keyset does not match independent roster")
    if gentxs and set(gentxs) != set(reviewed):
        errors.append("Genesis gentx consensus keyset does not match independent roster")
    if comet and gentxs and set(comet) != set(gentxs):
        errors.append("Comet validator and SDK gentx consensus keysets conflict")
    if comet:
        for key, voting_power in comet.items():
            if key in powers and powers[key] != voting_power:
                errors.append("Genesis voting power differs from independently reviewed roster")
    if powers and any(3 * p >= sum(powers.values()) for p in powers.values()):
        errors.append("Initial voting power concentrated at >= one third")
    if len(reviewed) < 7:
        errors.append("Insufficient independently reviewed unique public consensus keys")
    return sorted(set(errors))
