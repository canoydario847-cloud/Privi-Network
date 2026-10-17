#!/usr/bin/env python3
"""CI-ONLY Privi 1B PRVI four-validator funded/genesis/consensus rehearsal.

All four genesis keyrings, consensus/Comet node keys, gentxs, signing files,
bank accounts and logs are temporary synthetic CI assets. No operator owns a
production key. No production authority, user wallet, mainnet issuance, remote
RPC or Railway deployment is involved. Everything is deleted on exit.

Do NOT use this to declare the seven-INDEPENDENT-operator release gate passed.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import tomllib
import urllib.error
import urllib.request

from ci_runtime_init import CID, CAP, inspect
from ci_funded_genesis_positive import (
    DENOM, ONE, DISTRIBUTION, hardened_local_app_config, run
)
from genesis_operator_binding import parse_gentxs

COUNT = 4
COMET_RPC = 26657
COMET_P2P = 26656
BALANCE_PER_SECONDARY = ONE  # Each validator self-bonds exactly 1 test PRVI
BLOCK_HEIGHT = 2
STARTUP_SECONDS = 95
LOCALHOST = "127.0.0.1"


def synthetic_funded_rows(addresses):
    """Five budget categories, split only COMMUNITY among four validators."""
    if len(addresses) != COUNT or len(set(addresses)) != COUNT:
        raise ValueError("Four unique ephemeral accounts required")
    # Do not import or use a user's external EVM wallet in any genesis.
    from bech32_accounts import valid_privi_address
    if not all(valid_privi_address(a) for a in addresses):
        raise ValueError("Validator addresses must be valid Privi native accounts")
    from test_bech32_accounts import test_address
    rows = [
        {"address": addresses[0], "category": "community",
         "amount": 400_000_000 * ONE - (COUNT-1) * BALANCE_PER_SECONDARY}
    ]
    rows.extend({
        "address": a, "category": "community",
        "amount": BALANCE_PER_SECONDARY
    } for a in addresses[1:])
    for i, (category, coins) in enumerate(DISTRIBUTION[1:]):
        rows.append({
            "address": test_address(80+i),
            "category": category, "amount": coins * ONE
        })
    if len({r["address"] for r in rows}) != len(rows):
        raise ValueError("Duplicate synthetic bank addresses")
    if sum(r["amount"] for r in rows) != CAP:
        raise ValueError("Synthetic allocation must total exact 1B PRVI")
    subtotals = {}
    for row in rows:
        subtotals[row["category"]] = subtotals.get(row["category"], 0) + row["amount"]
    for category, coins in DISTRIBUTION:
        if subtotals.get(category) != coins * ONE:
            raise ValueError("Privi category total differs from proposal: " + category)
    return rows


def check_four_funded_genesis(genesis, rows, consensus_keys):
    """Structural review of REAL CLI-created SDK genesis, not fabricated txs."""
    errors = inspect(genesis)
    bank = (genesis.get("app_state") or {}).get("bank") or {}
    actual = {}
    for b in bank.get("balances", []):
        if not isinstance(b, dict) or not isinstance(b.get("coins"), list) or len(b["coins"]) != 1:
            errors.append("Unexpected bank balance object")
            continue
        c = b["coins"][0]
        if c.get("denom") != DENOM or not re.fullmatch(r"[1-9][0-9]*", str(c.get("amount"))):
            errors.append("Wrong/zero/invalid denomination in bank balances")
            continue
        if b.get("address") in actual:
            errors.append("Duplicate account in bank genesis")
        actual[b.get("address")] = int(c["amount"])
    if actual != {r["address"]: r["amount"] for r in rows}:
        errors.append("Funded genesis bank ledger differs from exact 1B synthetic allocations")
    supply = bank.get("supply") or []
    if len(supply) != 1 or supply[0] != {"denom": DENOM, "amount": str(CAP)}:
        errors.append("Funded genesis declared native supply is not exactly 10^27 aprvi")
    try:
        signed = parse_gentxs(genesis)
        if set(signed) != set(consensus_keys) or len(signed) != COUNT:
            errors.append("Four signed genesis validator keys differ from actual local consensus keys")
    except (ValueError, TypeError, KeyError) as exc:
        errors.append("Four genesis gentx validation failed: " + str(exc))
    return errors


def strict_toml(config):
    try:
        return tomllib.loads(config)
    except (ValueError, tomllib.TOMLDecodeError) as exc:
        raise ValueError("Invalid disposable CometBFT TOML") from exc


def private_four_node_comet_config(text, index, peer_ids):
    """Configures loopback-only RPC/P2P, four distinct ports, app mempool."""
    if not isinstance(text, str) or index not in range(COUNT) or len(peer_ids) != COUNT:
        raise ValueError("Bad disposable consensus network configuration")
    if len(set(peer_ids)) != COUNT or not all(re.fullmatch(r"[a-f0-9]{40}", p) for p in peer_ids):
        raise ValueError("Four unique Comet node identities required")
    peers = ",".join(
        f"{peer_ids[i]}@{LOCALHOST}:{COMET_P2P+i}"
        for i in range(COUNT) if i != index
    )
    replacements = {
        "rpc": {"laddr": f'"tcp://{LOCALHOST}:{COMET_RPC+index}"'},
        "p2p": {
            "laddr": f'"tcp://{LOCALHOST}:{COMET_P2P+index}"',
            "persistent_peers": f'"{peers}"',
            "addr_book_strict": "false",
            "allow_duplicate_ip": "true",
            "pex": "false",
        },
        "mempool": {"type": '"app"'},
    }
    found = {sec: set() for sec in replacements}
    section = ""
    updated = []
    for line in text.splitlines(keepends=True):
        match = re.fullmatch(r"\[([a-z0-9_]+)\]", line.strip())
        if match:
            section = match.group(1)
        m = re.fullmatch(r"(\s*)([a-z_]+)(\s*=\s*)([^#\r\n]*)(\s*(?:#.*)?)(\r?\n?)", line)
        if m and section in replacements and m.group(2) in replacements[section]:
            field = m.group(2)
            if field in found[section]:
                raise ValueError("Duplicate Comet key: " + section + "." + field)
            found[section].add(field)
            new = replacements[section][field]
            line = m.group(1) + field + m.group(3) + new + m.group(5) + m.group(6)
        updated.append(line)
    for sec, options in replacements.items():
        if found[sec] != set(options):
            raise ValueError("Comet config missing required " + sec + " keys")
    value = "".join(updated)
    parsed = strict_toml(value)
    for sec, options in replacements.items():
        for key, raw in options.items():
            expected = (raw.strip('"') if raw.startswith('"') else raw == "true")
            if parsed[sec][key] != expected:
                raise ValueError("Comet section rewrite did not take effect")
    if any(parsed["p2p"].get("seeds", "") for _ in range(1)):
        raise ValueError("Seeds forbidden in CI isolated consensus")
    return value


def node_id(home):
    """Derived from Comet node_key.json in isolated key material, never logged."""
    raw = json.loads((home / "config" / "node_key.json").read_text(encoding="utf-8"))
    secret = base64.b64decode(raw["priv_key"]["value"], validate=True)
    if len(secret) != 64:
        raise ValueError("Unexpected local Comet node key format")
    return hashlib.sha256(secret[-32:]).digest()[:20].hex()


def consensus_pubkey(home):
    data = json.loads((home / "config" / "priv_validator_key.json").read_text(encoding="utf-8"))
    raw = base64.b64decode(data["pub_key"]["value"], validate=True)
    if len(raw) != 32:
        raise ValueError("Unexpected Comet consensus public key")
    return raw


def local_rpc(index, path):
    try:
        with urllib.request.urlopen(
            f"http://{LOCALHOST}:{COMET_RPC+index}/{path}", timeout=1.2
        ) as conn:
            if conn.status != 200:
                return None
            return json.loads(conn.read(250000))
    except (OSError, ValueError, urllib.error.URLError):
        return None


def consensus_evidence(keys):
    """All four must commit the exact same height-2 hash, with 4 keyset."""
    statuses = []
    block_hashes = []
    for i in range(COUNT):
        status = local_rpc(i, "status")
        block = local_rpc(i, f"block?height={BLOCK_HEIGHT}")
        if not status or not block:
            return None
        result = status.get("result") or {}
        height = int((result.get("sync_info") or {}).get("latest_block_height") or 0)
        if height < BLOCK_HEIGHT:
            return None
        statuses.append((result.get("node_info") or {}).get("id"))
        block_hashes.append(((block.get("result") or {}).get("block_id") or {}).get("hash"))
    if len(set(statuses)) != COUNT or not all(statuses):
        return None
    if len(set(block_hashes)) != 1 or not all(block_hashes):
        return None
    votes = local_rpc(0, f"validators?height={BLOCK_HEIGHT}")
    if not votes:
        return None
    valrows = ((votes.get("result") or {}).get("validators") or [])
    pubkeys = set()
    powers = []
    for row in valrows:
        try:
            key = base64.b64decode(row["pub_key"]["value"], validate=True)
            power = int(row["voting_power"])
        except (KeyError, ValueError, TypeError):
            return None
        pubkeys.add(key)
        powers.append(power)
    if len(pubkeys) != COUNT or pubkeys != set(keys) or len(powers) != COUNT:
        return None
    if min(powers) <= 0 or max(powers) * 3 >= sum(powers):
        return None
    return {"height": BLOCK_HEIGHT, "validators": COUNT,
            "equal_hash": True, "distinct_comet_nodes": True,
            "no_operator_exceeds_one_third_power": True}


def prove(binary):
    binary = Path(binary).resolve(strict=True)
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise ValueError("CI-only executable node required")
    with tempfile.TemporaryDirectory(prefix="privi-ci-four-funded-") as tmp:
        root = Path(tmp)
        os.chmod(root, 0o700)
        env = os.environ.copy()
        env["HOME"] = str(root)
        homes = [root / f"validator-{i}" for i in range(COUNT)]
        # Init four separate actual Comet identities and four wallet keyrings.
        addresses = []
        for i, home in enumerate(homes):
            base = [str(binary), "--home", str(home)]
            run(base + ["init", "CI-Ephemeral-Privi-" + str(i), "--chain-id", CID],
                env=env, label="Initialize ephemeral validator home")
            name = "ci-validator-" + str(i)
            run(base + ["keys", "add", name, "--keyring-backend", "test"],
                env=env, label="Generate disposable validator signing identity")
            address = run(base + ["keys", "show", name, "-a",
                                 "--keyring-backend", "test"], env=env,
                          label="Retrieve synthetic signer account").decode("utf-8").strip()
            addresses.append(address)
        rows = synthetic_funded_rows(addresses)
        primary = [str(binary), "--home", str(homes[0])]
        for row in rows:
            run(primary + ["genesis", "add-genesis-account", row["address"],
                           str(row["amount"]) + DENOM, "--keyring-backend", "test"],
                env=env, label="Add CI-only synthetic funded recipient")
        # Every signer must sign on precisely the same shared funded genesis.
        source = homes[0] / "config" / "genesis.json"
        for home in homes[1:]:
            shutil.copy2(source, home / "config" / "genesis.json")
        for i, home in enumerate(homes):
            base = [str(binary), "--home", str(home)]
            run(base + ["genesis", "gentx", "ci-validator-" + str(i),
                        str(ONE) + DENOM, "--chain-id", CID,
                        "--keyring-backend", "test"],
                env=env, label="Sign distinct disposable validator gentx")
            if i:
                directory = home / "config" / "gentx"
                files = list(directory.glob("*.json"))
                if len(files) != 1:
                    raise ValueError("Unexpected disposable gentx output")
                target = homes[0] / "config" / "gentx" / files[0].name
                if target.exists():
                    raise ValueError("Duplicate gentx filename")
                shutil.copy2(files[0], target)
        run(primary + ["genesis", "collect-gentxs"], env=env,
            label="Collect four disposable validator gentxs")
        run(primary + ["genesis", "validate-genesis"], env=env,
            label="SDK validate four-validator PRVI funded genesis")
        genesis_bytes = source.read_bytes()
        genesis = json.loads(genesis_bytes)
        keys = [consensus_pubkey(home) for home in homes]
        if len(set(keys)) != COUNT:
            raise ValueError("Four independently generated CI consensus keys required")
        problems = check_four_funded_genesis(genesis, rows, keys)
        if problems:
            raise ValueError("Four-validator exact-cap bank/genesis check blocked: " + "; ".join(problems))
        # Same canonical genesis, but never share local node/validator keys.
        for home in homes[1:]:
            (home / "config" / "genesis.json").write_bytes(genesis_bytes)
        ids = [node_id(home) for home in homes]
        for i, home in enumerate(homes):
            comet = home / "config" / "config.toml"
            comet.write_text(
                private_four_node_comet_config(comet.read_text(encoding="utf-8"), i, ids),
                encoding="utf-8")
            app = home / "config" / "app.toml"
            app.write_text(hardened_local_app_config(app.read_text(encoding="utf-8")),
                           encoding="utf-8")
        procs = []
        logs = []
        try:
            for i, home in enumerate(homes):
                outfile = (root / f"validator-{i}-private.log").open("wb")
                logs.append(outfile)
                proc = subprocess.Popen(
                    [str(binary), "--home", str(home), "start",
                     "--chain-id", CID, "--minimum-gas-prices", "0aprvi"],
                    env=env, stdout=outfile, stderr=subprocess.STDOUT)
                procs.append(proc)
            deadline = time.monotonic() + STARTUP_SECONDS
            evidence = None
            while time.monotonic() < deadline:
                if any(p.poll() is not None for p in procs):
                    raise ValueError("One or more CI validators exited before block quorum; logs redacted")
                evidence = consensus_evidence(keys)
                if evidence:
                    break
                time.sleep(1)
            if evidence is None:
                raise ValueError("Four synthetic PRVI validators did not reach common block quorum")
        finally:
            for p in procs:
                if p.poll() is None:
                    p.terminate()
            for p in procs:
                if p.poll() is None:
                    try:
                        p.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        p.kill()
                        p.wait(timeout=5)
            for f in logs:
                f.close()
        return {
            "status": "FOUR_DISPOSABLE_VALIDATORS_1B_PRVI_CONSENSUS_PASSED",
            "synthetic_genesis_supply_aprvi": str(CAP),
            "validators": COUNT,
            "category_amounts_prvi": {category: str(coins) for category, coins in DISTRIBUTION},
            "evidence": evidence,
            "keys_and_test_funds_destroyed": True,
            "financial_mainnet_deployed": False,
            "real_PRVI_issued": False
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    opts = parser.parse_args()
    try:
        result = prove(opts.binary)
    except (OSError, ValueError, TypeError, KeyError, subprocess.TimeoutExpired) as err:
        parser.exit(1, "PRVI FOUR VALIDATOR CI BLOCKED: " + str(err) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
