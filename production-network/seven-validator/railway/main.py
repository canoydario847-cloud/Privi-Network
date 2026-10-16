#!/usr/bin/env python3
"""Isolated, valueless Privi seven-validator Railway STAGING topology.

Bootstraps once on its own volume, then distributes each node's state through
Railway private networking with an individual bearer token. Never for mainnet.
"""
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen

COUNT = 7
CHAIN = "local-privi-seven-4221"
HOME = Path("/data/evmd")
ROOT = Path("/data")
BASE_HOST = "privi-validator-"
BOOTSTRAP_PORT = 8099
NODE_NAMES = [f"{BASE_HOST}{i}.railway.internal" for i in range(COUNT)]
HEX_ID = re.compile(r"^[0-9a-fA-F]{40}$")


def die(message):
    raise SystemExit("Privi Railway staging: " + message)


def run(*args):
    return subprocess.run(args, check=True, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE).stdout.strip()


def require_tokens():
    raw = os.environ.get("PRIVI_BOOTSTRAP_TOKENS_JSON", "")
    try:
        tokens = json.loads(raw)
    except json.JSONDecodeError:
        die("PRIVI_BOOTSTRAP_TOKENS_JSON is invalid")
    if not isinstance(tokens, dict) or set(tokens) != set(map(str, range(COUNT))):
        die("bootstrap requires exactly seven separately assigned tokens")
    if any(not isinstance(v, str) or len(v) < 32 for v in tokens.values()):
        die("each bootstrap token needs at least 32 characters")
    if len(set(tokens.values())) != COUNT:
        die("bootstrap tokens must be distinct")
    return tokens


def edit_section(filename, section, changes):
    """Fail closed if a pinned-upstream TOML key moves or disappears."""
    path = Path(filename)
    lines = path.read_text().splitlines(keepends=True)
    current = None
    seen = set()
    for n, line in enumerate(lines):
        match = re.match(r"^\s*\[([^\]]+)\]\s*$", line.strip())
        if match:
            current = match.group(1)
            continue
        if current != section:
            continue
        match = re.match(r"^\s*([A-Za-z_]+)\s*=", line)
        if match and match.group(1) in changes:
            key = match.group(1)
            if key in seen:
                die(f"duplicate key in {section}: {key}")
            lines[n] = f"{key} = {json.dumps(changes[key])}\n"
            seen.add(key)
    if seen != set(changes):
        die(f"upstream TOML layout changed ({section}): {sorted(set(changes)-seen)}")
    path.write_text("".join(lines))


def configure_node(home, node_idx, peer_ids):
    if not (home / "config/genesis.json").is_file():
        die("node missing genesis.json")
    peers = ",".join(f"{peer_ids[i]}@{NODE_NAMES[i]}:26656"
                     for i in range(COUNT) if i != node_idx)
    config = home / "config/config.toml"
    edit_section(config, "p2p", {
        "laddr": "tcp://[::]:26656",
        "persistent_peers": peers,
        "addr_book_strict": False,
        "pex": False,
    })
    edit_section(config, "rpc", {"laddr": "tcp://[::]:26657"})
    edit_section(config, "mempool", {"type": "app"})
    # Config files and private validator state are never committed to GitHub.


def bootstrap():
    tokens = require_tokens()
    root = ROOT / "cluster"
    bundles = ROOT / "bundles"
    ready = ROOT / "bootstrap-ready.json"
    if not ready.is_file():
        if root.exists() or bundles.exists():
            die("partial bootstrap state exists; refusing to regenerate signing identities")
        root.mkdir(mode=0o700)
        print("Initializing seven NEW disposable upstream TEST validator identities", flush=True)
        run("/usr/local/bin/evmd", "--home", "/tmp/privi-setup-home",
            "testnet", "init-files", "--validator-count", str(COUNT),
            "--chain-id", CHAIN, "--starting-ip-address", "192.168.77.10",
            "--keyring-backend=test", "--use-docker=true", "-o", str(root))
        peer_ids = []
        hashes = []
        validator_keys = []
        for i in range(COUNT):
            node = root / f"node{i}/evmd"
            for rel in ("config/config.toml", "config/genesis.json",
                        "config/node_key.json", "config/priv_validator_key.json"):
                if not (node / rel).is_file():
                    die(f"initializer missing node {i} {rel}")
            peerid = run("/usr/local/bin/evmd", "--home", str(node), "comet", "show-node-id")
            if not HEX_ID.fullmatch(peerid):
                die(f"upstream node ID invalid for node {i}")
            peer_ids.append(peerid.lower())
            hashes.append(hashlib.sha256((node / "config/genesis.json").read_bytes()).hexdigest())
            validator_keys.append(json.loads((node / "config/priv_validator_key.json").read_text())["address"])
        if len(set(peer_ids)) != COUNT or len(set(validator_keys)) != COUNT:
            die("duplicate signing identity or Comet peer ID")
        if len(set(hashes)) != 1:
            die("seven validators have different genesis files")
        bundles.mkdir(mode=0o700)
        for i in range(COUNT):
            node = root / f"node{i}/evmd"
            configure_node(node, i, peer_ids)
            with tarfile.open(bundles / f"node{i}.tgz", "w:gz") as tar:
                tar.add(node, arcname="evmd", recursive=True)
        ready.write_text(json.dumps({"chain": CHAIN, "genesis_sha256": hashes[0],
                                     "nodes": COUNT, "peer_ids": peer_ids}) + "\n")
        ready.chmod(0o600)
        print("Initial validator bundles ready; genesis SHA256: " + hashes[0], flush=True)
    else:
        manifest = json.loads(ready.read_text())
        if manifest.get("chain") != CHAIN or manifest.get("nodes") != COUNT:
            die("existing cluster manifest does not match pinned staging configuration")
        if not all((bundles / f"node{i}.tgz").is_file() for i in range(COUNT)):
            die("some validator bundles missing; refusing to generate new ones")
        print("Using existing immutable staging bootstrap and validator identities", flush=True)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            match = re.fullmatch(r"/bundle/([0-6])", self.path)
            if not match:
                self.send_error(404)
                return
            i = match.group(1)
            supplied = self.headers.get("Authorization", "").removeprefix("Bearer ")
            if not hmac.compare_digest(supplied, tokens[i]):
                self.send_error(403)
                return
            path = bundles / f"node{i}.tgz"
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(path.stat().st_size))
            self.end_headers()
            with path.open("rb") as f:
                shutil.copyfileobj(f, self.wfile)

        def log_message(self, *_):
            # No access logs containing tokens or secret-bearing filenames.
            pass

    class PrivateServer(ThreadingHTTPServer):
        address_family = socket.AF_INET6

    print(f"Private bootstrap is serving seven unique bundles on port {BOOTSTRAP_PORT}", flush=True)
    PrivateServer(("::", BOOTSTRAP_PORT), Handler).serve_forever()


def extract_bundle(raw, target):
    """Extract a single node archive without trusting tar path metadata."""
    if len(raw) > 60_000_000:
        die("node bundle exceeds 60MB")
    target.mkdir(mode=0o700)
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
        members = tar.getmembers()
        if len(members) > 2000:
            die("excessive archive entries")
        for m in members:
            parts = Path(m.name).parts
            if not parts or parts[0] != "evmd" or ".." in parts or m.issym() or m.islnk() or m.isdev():
                die("unsafe validator archive member")
        tar.extractall(target, filter="data")
    home = target / "evmd"
    if not (home / "config/genesis.json").is_file() or not (home / "config/priv_validator_key.json").is_file():
        die("validator archive missing essential configuration")
    return home


def validator():
    idx_string = os.environ.get("PRIVI_NODE_INDEX", "")
    if idx_string not in [str(i) for i in range(COUNT)]:
        die("PRIVI_NODE_INDEX must be 0..6")
    idx = int(idx_string)
    token = os.environ.get("PRIVI_NODE_BOOTSTRAP_TOKEN", "")
    if len(token) < 32:
        die("missing node-specific bootstrap token")
    if HOME.exists():
        if not (HOME / "config/genesis.json").is_file() or not (HOME / "config/priv_validator_key.json").is_file():
            die("partial validator home found; refusing to overwrite signed chain state")
        print(f"Validator {idx} restoring persistent state from its own volume", flush=True)
    else:
        other = [p.name for p in ROOT.iterdir() if p.name not in ("lost+found",)]
        if other:
            die(f"unexpected preexisting volume contents: {other}")
        url = f"http://privi-bootstrap.railway.internal:{BOOTSTRAP_PORT}/bundle/{idx}"
        payload = None
        for attempt in range(36):
            try:
                request = Request(url, headers={"Authorization": "Bearer " + token})
                with urlopen(request, timeout=20) as response:
                    payload = response.read(60_000_001)
                break
            except Exception:
                if attempt == 35:
                    die("private bootstrap unavailable or denied node token")
                time.sleep(5)
        temp = ROOT / f".incoming-{idx}"
        if temp.exists():
            die("partial previous node download exists; refusing to overwrite")
        extracted = extract_bundle(payload, temp)
        extracted.rename(HOME)
        shutil.rmtree(temp)
        print(f"Validator {idx} initialized once from private bootstrap; genesis SHA256: "
              + hashlib.sha256((HOME / "config/genesis.json").read_bytes()).hexdigest(), flush=True)
    # Railway volumes are initially root-owned; run evmd itself as uid 1025.
    # Never generate or overwrite signing identities after an initialized volume exists.
    if not (HOME / "data/priv_validator_state.json").is_file():
        die("missing consensus signing state; refusing to start")
    run("chown", "-R", "1025:1025", str(HOME))
    args = ["su-exec", "1025:1025", "/usr/local/bin/evmd", "start",
            "--home", str(HOME), "--log_format", "plain",
            "--minimum-gas-prices", "0.0001atest",
            "--json-rpc.enable", "true" if idx == 0 else "false",
            "--json-rpc.api", "eth,net,web3", "--chain-id", CHAIN]
    print(f"Starting Railway Privi TEST validator {idx}; financial PRVI mainnet remains OFF", flush=True)
    os.execvp(args[0], args)


def main():
    if os.environ.get("PRIVI_RAILWAY_ROLE") == "bootstrap":
        bootstrap()
    elif os.environ.get("PRIVI_RAILWAY_ROLE") == "validator":
        validator()
    else:
        die("PRIVI_RAILWAY_ROLE must be bootstrap or validator")


if __name__ == "__main__":
    main()
