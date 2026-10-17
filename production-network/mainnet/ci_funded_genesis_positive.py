#!/usr/bin/env python3
"""Privi 1-billion-coin POSITIVE executable genesis rehearsal, strictly CI-only.

Creates five SYNTHETIC allocation recipients on a short-lived, isolated
privi-ci-nonproduction-999 network. Generates ONE disposable validator key,
collects an SDK-signed gentx, checks the actual initialized genesis totals,
and attempts local InitChain + at least one committed block via loopback RPC.

NO real Privi mainnet coins exist or are minted by this test. No real
wallets, independent validators, signers, blockchain deployment, public RPC,
bridging, or real-money transactions are involved. All ephemeral keys and
genesis state are destroyed on function exit. CI must never upload them.

A positive CI result is NOT seven-validator production release approval.
"""
import argparse
from contextlib import suppress
import json
import os
import re
from pathlib import Path
import subprocess
import tempfile
import time
import tomllib
import urllib.error
import urllib.request

from bech32_accounts import valid_privi_address
from ci_runtime_init import CAP, CID, inspect
from ci_init_chain_cap_negative import hardened_local_comet_config
from test_bech32_accounts import test_address

DENOM = "aprvi"
ONE = 10**18
DISTRIBUTION = (
    ("community", 400_000_000),
    ("ecosystem", 200_000_000),
    ("staking_reserve", 200_000_000),
    ("treasury", 100_000_000),
    ("contributors", 100_000_000),
)
# Only 1 synthetic CI signer; enough to prove positive chain init, not enough
# for Privi financial mainnet independence/reliability requirements.
VALIDATOR_KEY_NAME = "ci-disposable-validator"
LOCAL_RPC = "http://127.0.0.1:26657/status"
MAX_OUTPUT = 1_000_000


def allocations(validator_address):
    if not valid_privi_address(validator_address):
        raise ValueError("Generated test validator must use checksum-valid privi HRP")
    rows = []
    # Synthetic, keyless account addresses are test fixtures and are NOT
    # any founder or real operator wallet. No funds survive this CI run.
    for i, (category, coins) in enumerate(DISTRIBUTION):
        address = validator_address if i == 0 else test_address(40 + i)
        rows.append({"category": category, "address": address,
                     "amount_base_units": coins * ONE})
    if len({r["address"] for r in rows}) != len(rows):
        raise ValueError("Synthetic recipients must be distinct")
    if sum(r["amount_base_units"] for r in rows) != CAP:
        raise ValueError("Synthetic allocations must total 1 billion PRVI exactly")
    return rows


def check_funded_genesis(genesis, expected_rows):
    errors = inspect(genesis)
    state = genesis.get("app_state") or {}
    bank = state.get("bank") or {}
    expected = {row["address"]: row["amount_base_units"] for row in expected_rows}
    actual = {}
    for entry in bank.get("balances") or []:
        addr = entry.get("address")
        if not isinstance(addr, str) or addr in actual:
            errors.append("Malformed or duplicated synthetic funded account")
            continue
        funds = entry.get("coins") or []
        if len(funds) != 1 or funds[0].get("denom") != DENOM:
            errors.append("Wrong or extra denomination in funded account")
            continue
        try:
            actual[addr] = int(funds[0]["amount"])
        except (ValueError, KeyError, TypeError):
            errors.append("Malformed synthetic account allocation amount")
    if actual != expected:
        errors.append("Synthetic bank allocation amounts differ from 1B fixture")
    supply = bank.get("supply") or []
    if len(supply) != 1 or supply[0].get("denom") != DENOM \
            or str(supply[0].get("amount")) != str(CAP):
        errors.append("Declared synthetic PRVI supply is not exactly 1 billion")
    if len(expected_rows) != len(DISTRIBUTION):
        errors.append("Synthetic distribution categories incomplete")
    if not valid_privi_address(expected_rows[0]["address"]):
        errors.append("Invalid funded validator checksum")
    gentxs = (state.get("genutil") or {}).get("gen_txs") or []
    if len(gentxs) != 1:
        errors.append("Synthetic funded genesis must contain exactly one validator gentx")
    return errors


def run(cmd, *, env, label, timeout=35):
    # Never log subprocess output: ephemeral keygen may print mnemonics.
    out = subprocess.run(cmd, env=env, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, timeout=timeout)
    if out.returncode:
        raise ValueError(label + " failed; process output intentionally redacted")
    if len(out.stdout) > MAX_OUTPUT or len(out.stderr) > MAX_OUTPUT:
        raise ValueError(label + " returned excessive output")
    return out.stdout


def read_local_height():
    try:
        with urllib.request.urlopen(LOCAL_RPC, timeout=1) as response:
            if response.status != 200:
                return 0
            data = json.loads(response.read(16384))
        value = (data.get("result") or {}).get("sync_info") or {}
        return int(value.get("latest_block_height") or 0)
    except (OSError, ValueError, TypeError, urllib.error.URLError):
        return 0


def hardened_local_app_config(text):
    """Disable network services in the ephemeral CI node's app.toml.

    Go examples can ship with grpc.enable=true even if REST/JSON-RPC are off.
    Parse & edit only exact TOML sections/keys; then parse-check the output.
    """
    if not isinstance(text, str):
        raise ValueError("Expected app TOML content")
    lines = text.splitlines(keepends=True)
    section = ""
    networks = {"api", "grpc", "grpc-web", "json-rpc", "rosetta"}
    result = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped.strip("[]")
        if section in networks:
            match = re.match(r'^(\\s*)(enabled?)(\\s*=\\s*)(true|false)(\\s*(?:#.*)?)
    """Only inspect actual network services, not unrelated enable flags."""
    if not isinstance(text, str):
        raise ValueError("Invalid CI app config content")
    try:
        settings = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError("Invalid app TOML") from exc
    for section in ("api", "grpc", "grpc-web", "json-rpc", "rosetta"):
        cfg = settings.get(section) or {}
        if not isinstance(cfg, dict) or cfg.get("enable") is True or cfg.get("enabled") is True:
            raise ValueError("CI network service must remain disabled: " + section)
    return True


def prove(binary):
    binary = Path(binary).resolve(strict=True)
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise ValueError("Executable CI-only node required")
    with tempfile.TemporaryDirectory(prefix="privi-ci-funded-positive-") as tmp:
        root = Path(tmp)
        os.chmod(root, 0o700)
        home = root / "disposable-testnet"
        env = os.environ.copy()
        env["HOME"] = str(root)
        env["DAEMON_HOME"] = str(home)
        base = [str(binary), "--home", str(home)]

        run(base + ["init", "ci-only-funded-genesis", "--chain-id", CID],
            env=env, label="Disposable Privi node init")
        # Key generation is allowed ONLY for isolated synthetic CI. No recovery
        # phrases or private keys are printed, copied or persisted outside tmp.
        run(base + ["keys", "add", VALIDATOR_KEY_NAME, "--keyring-backend", "test"],
            env=env, label="Ephemeral validator identity generation")
        address = run(base + ["keys", "show", VALIDATOR_KEY_NAME, "-a",
                              "--keyring-backend", "test"],
                      env=env, label="Ephemeral validator account retrieval").decode().strip()
        ledger = allocations(address)
        for entry in ledger:
            run(base + ["genesis", "add-genesis-account", entry["address"],
                        str(entry["amount_base_units"]) + DENOM,
                        "--keyring-backend", "test"],
                env=env, label="Synthetic " + entry["category"] + " genesis allocation")
        run(base + ["genesis", "gentx", VALIDATOR_KEY_NAME, str(ONE) + DENOM,
                    "--chain-id", CID, "--keyring-backend", "test"],
            env=env, label="Synthetic single validator gentx")
        run(base + ["genesis", "collect-gentxs"], env=env,
            label="Synthetic genesis signed gentx collection")
        run(base + ["genesis", "validate-genesis"], env=env,
            label="Synthetic genesis SDK validation")

        path = home / "config" / "genesis.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        failures = check_funded_genesis(document, ledger)
        if failures:
            raise ValueError("Synthetic 1B PRVI genesis check failed: " + "; ".join(failures))
        config = home / "config" / "config.toml"
        config.write_text(hardened_local_comet_config(config.read_text(encoding="utf-8")),
                          encoding="utf-8")
        # No external listeners, no relay, no Ethereum RPC or P2P network.
        app = home / "config" / "app.toml"
        contents = app.read_text(encoding="utf-8")
        # Explicitly turn off default-enabled gRPC, REST, JSON-RPC,
        # Rosetta and gRPC-Web before starting the isolated test node.
        app.write_text(hardened_local_app_config(contents), encoding="utf-8")
        log = root / "discarded-private-node-output.log"
        with log.open("wb") as output:
            proc = subprocess.Popen(
                base + ["start", "--chain-id", CID, "--minimum-gas-prices", "0aprvi"],
                env=env, stdout=output, stderr=subprocess.STDOUT
            )
            try:
                deadline = time.monotonic() + 40
                height = 0
                while time.monotonic() < deadline:
                    if proc.poll() is not None:
                        raise ValueError("Synthetic funded validator node exited before first block; logs redacted")
                    height = read_local_height()
                    if height >= 1:
                        break
                    time.sleep(0.5)
                if height < 1:
                    raise ValueError("Synthetic funded validator did not commit block within 40 seconds")
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=5)
        result = {
            "status": "SYNTHETIC_FUNDED_1B_PRVI_POSITIVE_INITCHAIN_PASSED",
            "synthetic_chain_id": CID,
            "synthetic_wallet_categories": [row["category"] for row in ledger],
            "synthetic_total_prvi": "1000000000",
            "synthetic_supply_aprvi": str(CAP),
            "validated_one_disposable_validator_gentx": True,
            "first_block_committed": True,
            "financial_mainnet_deployed": False,
            "real_coins_or_operator_keys_created": False,
            "ephemeral_genesis_and_keys_deleted": True
        }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = prove(args.binary)
    except (ValueError, OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        parser.exit(1, "PRVI FUNDED GENESIS CI FAILED: " + str(exc) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
, line.rstrip("\\r\\n"))
            if match:
                newline = "\\n" if line.endswith("\\n") else ""
                line = match.group(1) + match.group(2) + match.group(3) + "false" + match.group(5) + newline
        result.append(line)
    output = "".join(result)
    require_private_app_listeners(output)
    return output


def require_private_app_listeners(text):
    """Only inspect actual network services, not unrelated enable flags."""
    if not isinstance(text, str):
        raise ValueError("Invalid CI app config content")
    try:
        settings = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError("Invalid app TOML") from exc
    for section in ("api", "grpc", "grpc-web", "json-rpc", "rosetta"):
        cfg = settings.get(section) or {}
        if not isinstance(cfg, dict) or cfg.get("enable") is True or cfg.get("enabled") is True:
            raise ValueError("CI network service must remain disabled: " + section)
    return True


def prove(binary):
    binary = Path(binary).resolve(strict=True)
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise ValueError("Executable CI-only node required")
    with tempfile.TemporaryDirectory(prefix="privi-ci-funded-positive-") as tmp:
        root = Path(tmp)
        os.chmod(root, 0o700)
        home = root / "disposable-testnet"
        env = os.environ.copy()
        env["HOME"] = str(root)
        env["DAEMON_HOME"] = str(home)
        base = [str(binary), "--home", str(home)]

        run(base + ["init", "ci-only-funded-genesis", "--chain-id", CID],
            env=env, label="Disposable Privi node init")
        # Key generation is allowed ONLY for isolated synthetic CI. No recovery
        # phrases or private keys are printed, copied or persisted outside tmp.
        run(base + ["keys", "add", VALIDATOR_KEY_NAME, "--keyring-backend", "test"],
            env=env, label="Ephemeral validator identity generation")
        address = run(base + ["keys", "show", VALIDATOR_KEY_NAME, "-a",
                              "--keyring-backend", "test"],
                      env=env, label="Ephemeral validator account retrieval").decode().strip()
        ledger = allocations(address)
        for entry in ledger:
            run(base + ["genesis", "add-genesis-account", entry["address"],
                        str(entry["amount_base_units"]) + DENOM,
                        "--keyring-backend", "test"],
                env=env, label="Synthetic " + entry["category"] + " genesis allocation")
        run(base + ["genesis", "gentx", VALIDATOR_KEY_NAME, str(ONE) + DENOM,
                    "--chain-id", CID, "--keyring-backend", "test"],
            env=env, label="Synthetic single validator gentx")
        run(base + ["genesis", "collect-gentxs"], env=env,
            label="Synthetic genesis signed gentx collection")
        run(base + ["genesis", "validate-genesis"], env=env,
            label="Synthetic genesis SDK validation")

        path = home / "config" / "genesis.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        failures = check_funded_genesis(document, ledger)
        if failures:
            raise ValueError("Synthetic 1B PRVI genesis check failed: " + "; ".join(failures))
        config = home / "config" / "config.toml"
        config.write_text(hardened_local_comet_config(config.read_text(encoding="utf-8")),
                          encoding="utf-8")
        # No external listeners, no relay, no Ethereum RPC or P2P network.
        app = home / "config" / "app.toml"
        contents = app.read_text(encoding="utf-8")
        # This is an ephemeral runner with all real wallet access excluded.
        # Default JSON RPC is disabled, and only Comet local RPC is used.
        require_private_app_listeners(contents)
        log = root / "discarded-private-node-output.log"
        with log.open("wb") as output:
            proc = subprocess.Popen(
                base + ["start", "--chain-id", CID, "--minimum-gas-prices", "0aprvi"],
                env=env, stdout=output, stderr=subprocess.STDOUT
            )
            try:
                deadline = time.monotonic() + 40
                height = 0
                while time.monotonic() < deadline:
                    if proc.poll() is not None:
                        raise ValueError("Synthetic funded validator node exited before first block; logs redacted")
                    height = read_local_height()
                    if height >= 1:
                        break
                    time.sleep(0.5)
                if height < 1:
                    raise ValueError("Synthetic funded validator did not commit block within 40 seconds")
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=5)
        result = {
            "status": "SYNTHETIC_FUNDED_1B_PRVI_POSITIVE_INITCHAIN_PASSED",
            "synthetic_chain_id": CID,
            "synthetic_wallet_categories": [row["category"] for row in ledger],
            "synthetic_total_prvi": "1000000000",
            "synthetic_supply_aprvi": str(CAP),
            "validated_one_disposable_validator_gentx": True,
            "first_block_committed": True,
            "financial_mainnet_deployed": False,
            "real_coins_or_operator_keys_created": False,
            "ephemeral_genesis_and_keys_deleted": True
        }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = prove(args.binary)
    except (ValueError, OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        parser.exit(1, "PRVI FUNDED GENESIS CI FAILED: " + str(exc) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
